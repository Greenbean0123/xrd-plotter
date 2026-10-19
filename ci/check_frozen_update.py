"""Windows-only full installer smoke test in a disposable installation.

Reinstalls the same test binary under a simulated future manifest version.
This does not publish a release or replace the real installed application.
"""
from pathlib import Path
import base64
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cryptography.hazmat.primitives import serialization
import updater
from app_version import __version__


def main():
    if sys.platform != 'win32':
        raise SystemExit('This integration smoke test is for Windows.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-binary', type=Path)
    parser.add_argument('--old-version')
    parser.add_argument('--new-binary', type=Path, default=ROOT / 'dist' / 'XRD Plotter.exe')
    args = parser.parse_args()
    if args.old_binary and not args.old_version:
        parser.error('--old-version is required with --old-binary')
    built = args.new_binary
    old_binary = args.old_binary or built
    old_version = args.old_version or __version__
    parts = list(updater.version_tuple(__version__))
    parts[-1] += 1
    next_version = __version__ if args.old_binary else '.'.join(map(str, parts))
    private = serialization.load_pem_private_key(
        (ROOT / '.release-keys' / 'update-signing-key.pem').read_bytes(), password=None)
    with tempfile.TemporaryDirectory(prefix='xrd-update-smoke-') as directory:
        folder = Path(directory)
        install = folder / 'installed'
        install.mkdir()
        target = install / 'XRD Plotter.exe'
        package, helper = folder / 'package.exe', folder / 'helper.exe'
        shutil.copy2(old_binary, target)
        shutil.copy2(old_binary, helper)
        shutil.copy2(built, package)
        payload = {'schema': 1, 'version': next_version, 'notes': 'Isolated smoke test only', 'assets': {
            'windows-x86_64': {'url': 'https://example.test/test.exe', 'format': 'exe',
                'size': package.stat().st_size, 'sha256': hashlib.sha256(package.read_bytes()).hexdigest()}}}
        envelope = {'payload': payload, 'signature': base64.b64encode(private.sign(updater.canonical(payload))).decode()}
        release = updater.verify_manifest(envelope, updater.bundled_config()['public_key'], old_version)
        parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(180)'])
        job = {'target': str(target), 'package': str(package), 'release': release,
               'parent_pid': parent.pid, 'parent_bootloader_pid': 0,
               'ready': str(folder / 'helper-ready'), 'health': str(folder / 'new-app-ready'),
               'result': str(folder / 'result.json')}
        job_file = folder / 'job.json'
        job_file.write_text(json.dumps(job), encoding='utf-8')
        profile = folder / 'profile'
        session_file = profile / 'XRD Plotter' / 'update-session.json'
        session_file.parent.mkdir(parents=True)
        session_file.write_text(json.dumps({
            'groups': {'samples': [[{'path': str(ROOT / 'demo-data' / 'Synthetic Demo A.csv')},
                'Saved update pattern', '#ff6600', {'_order_id': 'saved-pattern', '_visible': True}]], 'cards': []},
            'order': ['saved-pattern'], 'variables': {'color': '#ff0000', 'dpi': '200'},
            'palette': ['#ff0000', '#00ff00'], 'theme': 'Dark', 'scale': '125%',
        }), encoding='utf-8')
        process = None
        try:
            with (folder / 'installer.log').open('wb') as log:
                process = subprocess.Popen([str(helper), '--apply-update', str(job_file)],
                    env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1', LOCALAPPDATA=str(profile)),
                    creationflags=subprocess.CREATE_NO_WINDOW, stdout=log, stderr=log)
            deadline = time.monotonic() + 60
            while not Path(job['ready']).exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise AssertionError((folder / 'installer.log').read_text(errors='replace'))
                time.sleep(0.2)
            # Installer is ready, but cannot change the existing app before approval/exit.
            assert target.exists() and not list(install.glob('*.previous-*.exe'))
            (folder / 'install-approved').write_text('approved')
            parent.terminate()
            parent.wait(timeout=10)
            assert process.wait(timeout=150) == 0, (folder / 'installer.log').read_text(errors='replace')
            result = json.loads(Path(job['result']).read_text(encoding='utf-8'))
            assert result['success'], result
            assert Path(job['health']).read_text() == 'ready'
            assert not session_file.exists(), 'Previous-version update session was not restored'
            assert Path(result['backup']).exists()
            print(f'Frozen update {old_version} -> {next_version}: helper readiness, parent-exit wait, replacement, GUI restart and backup verified.')
        finally:
            if parent.poll() is None:
                parent.terminate()
                parent.wait(timeout=10)
            # Stop only executables from this test's verified temporary directory.
            env = dict(os.environ, XRD_TEST_TARGET=str(target), XRD_TEST_HELPER=str(helper))
            subprocess.run(['powershell', '-NoProfile', '-Command',
                "Get-Process | Where-Object { $_.Path -eq $env:XRD_TEST_TARGET -or $_.Path -eq $env:XRD_TEST_HELPER } | Stop-Process"],
                env=env, capture_output=True)
            if process is not None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            time.sleep(1)


if __name__ == '__main__':
    main()
