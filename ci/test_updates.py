"""Tests use temporary installs and test-only keys; no real app is replaced."""
from pathlib import Path
import base64
import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import updater
import update_installer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.private = Ed25519PrivateKey.generate()
        self.public = base64.b64encode(self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        self.bytes = b'test package data'
        self.payload = {'schema': 1, 'version': '0.0.3', 'notes': 'Test release', 'assets': {
            'windows-x86_64': {'url': 'https://example.test/app.exe', 'size': len(self.bytes),
              'sha256': hashlib.sha256(self.bytes).hexdigest(), 'format': 'exe'}}}

    def signed(self):
        return {'payload': self.payload, 'signature': base64.b64encode(
            self.private.sign(updater.canonical(self.payload))).decode()}

    def release(self):
        return updater.verify_manifest(self.signed(), self.public, '0.0.2', 'windows-x86_64')

    def test_signed_update_and_numeric_versions(self):
        self.assertEqual(self.release()['version'], '0.0.3')
        self.assertIsNone(updater.verify_manifest(self.signed(), self.public, '0.0.3', 'windows-x86_64'))
        self.assertIsNone(updater.verify_manifest(self.signed(), self.public, '0.0.4', 'windows-x86_64'))
        self.assertGreater(updater.version_tuple('0.0.10'), updater.version_tuple('0.0.9'))

    def test_modified_manifest_and_wrong_key_are_rejected(self):
        envelope = self.signed()
        envelope['payload']['assets']['windows-x86_64']['url'] = 'https://other.test/malware.exe'
        with self.assertRaisesRegex(ValueError, 'signature'):
            updater.verify_manifest(envelope, self.public, '0.0.2', 'windows-x86_64')
        with self.assertRaises(ValueError):
            updater.verify_manifest(self.signed(), base64.b64encode(b'x' * 32).decode(), '0.0.2', 'windows-x86_64')

    def test_wrong_architecture_and_insecure_urls(self):
        with self.assertRaisesRegex(ValueError, 'does not include'):
            updater.verify_manifest(self.signed(), self.public, '0.0.2', 'macos-arm64')
        for url in ('http://example.test/app', 'file:///tmp/app', 'https://name:secret@example.test/app'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                updater.require_https(url)

    def test_download_checks_content_before_installing(self):
        with patch.object(updater, 'data_directory', return_value=self.root), patch.object(
                updater, 'open_https', return_value=io.BytesIO(self.bytes)):
            file = updater.download(self.release())
        self.assertEqual(file.read_bytes(), self.bytes)
        for bad_bytes in (b'wrong data', b'x' * (len(self.bytes) + 1)):
            with self.subTest(length=len(bad_bytes)), patch.object(updater, 'data_directory', return_value=self.root), patch.object(
                    updater, 'open_https', return_value=io.BytesIO(bad_bytes)), self.assertRaises(ValueError):
                updater.download(self.release())
        self.assertFalse(list(self.root.rglob('*.partial')))

    def test_no_server_is_explicit_and_network_free(self):
        with patch.object(updater, 'open_https') as network:
            with self.assertRaisesRegex(ValueError, 'No update server'):
                updater.check('0.0.2', {'manifest_url': '', 'public_key': self.public})
            network.assert_not_called()

    def test_zip_traversal_and_escaping_links(self):
        for filename in ('../bad', '/tmp/bad', 'XRD Plotter.app/../../bad', 'Other.app/a'):
            package = self.root / 'bad.zip'
            with zipfile.ZipFile(package, 'w') as archive:
                archive.writestr(filename, b'bad')
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                update_installer.validate_zip(package)
        package = self.root / 'symlink.zip'
        with zipfile.ZipFile(package, 'w') as archive:
            info = zipfile.ZipInfo('XRD Plotter.app/link')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, '../outside')
        with self.assertRaises(ValueError):
            update_installer.validate_zip(package)

    def test_mac_framework_relative_symlinks_are_allowed(self):
        package = self.root / 'framework.zip'
        with zipfile.ZipFile(package, 'w') as archive:
            info = zipfile.ZipInfo('XRD Plotter.app/Contents/Frameworks/Test.framework/Test')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, 'Versions/Current/Test')
        update_installer.validate_zip(package)

    def test_symlink_ancestor_cannot_hide_an_escape(self):
        package = self.root / 'symlink-chain.zip'
        with zipfile.ZipFile(package, 'w') as archive:
            for name, target in [('XRD Plotter.app/dir', '.'),
                                 ('XRD Plotter.app/dir/link', '../outside')]:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, target)
        with self.assertRaises(ValueError):
            update_installer.validate_zip(package)

    def test_successful_transaction_keeps_backup(self):
        target, staged, health = [self.root / name for name in ('app.exe', 'new.exe', 'ready')]
        target.write_text('old')
        staged.write_text('new')
        def launch(path, marker=None):
            marker.write_text('ready')
            return None
        backup = update_installer.replace_and_restart(target, staged, health, launch_app=launch, timeout=1)
        self.assertEqual(target.read_text(), 'new')
        self.assertEqual(backup.read_text(), 'old')

    def test_failed_startup_rolls_back_and_reopens_old_app(self):
        target, staged, health = [self.root / name for name in ('app.exe', 'new.exe', 'ready')]
        target.write_text('old')
        staged.write_text('broken new')
        launched = []
        class Failed:
            def poll(self):
                return 1
        def launch(path, marker=None):
            launched.append(path.read_text())
            return Failed()
        with self.assertRaisesRegex(RuntimeError, 'exited'):
            update_installer.replace_and_restart(target, staged, health, launch_app=launch, timeout=1)
        self.assertEqual(target.read_text(), 'old')
        self.assertEqual(launched, ['broken new', 'old'])

    def test_current_process_is_detected(self):
        self.assertTrue(update_installer.process_alive(os.getpid()))
        self.assertFalse(update_installer.process_alive(0))


if __name__ == '__main__':
    unittest.main()
