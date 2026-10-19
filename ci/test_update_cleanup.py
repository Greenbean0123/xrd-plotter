"""Cleanup must never remove failed updates, user data or unrelated installers."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import updater
import update_cleanup


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.patch = patch.object(updater, 'data_directory', return_value=self.base)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.target = self.base / 'installed' / 'XRD Plotter.exe'
        self.target.parent.mkdir()
        self.target.write_text('new program')
        self.backup = self.target.with_name('XRD Plotter.previous-1234abcd.exe')
        self.backup.write_text('old program')
        self.folder = self.base / 'updates' / ('a' * 32)
        self.folder.mkdir(parents=True)
        (self.folder / 'package.exe').write_text('download')
        (self.folder / 'helper').mkdir()
        (self.folder / 'helper' / 'helper.exe').write_text('helper')
        (self.folder / 'job.json').write_text(json.dumps({'target': str(self.target),
            'health': str(self.folder / 'new-app-ready')}))
        (self.folder / 'new-app-ready').write_text('ready')
        self.result = {'success': True, 'backup': str(self.backup)}
        self.write_result()

    def write_result(self):
        result = self.folder / 'result.json'
        result.write_text(json.dumps(self.result))
        os.utime(result, (time.time() - 10,) * 2)

    def test_success_preserves_default_data_and_manual_installer(self):
        defaults = self.base / 'defaultpattern'
        defaults.mkdir()
        reference = defaults / 'my-reference.xy'
        reference.write_text('data')
        manual = self.base / 'old-installer.exe'
        manual.write_text('keep')
        self.assertTrue(update_cleanup.cleanup(self.folder, self.target))
        self.assertFalse(self.folder.exists())
        self.assertFalse(self.backup.exists())
        self.assertTrue(self.target.exists() and reference.exists() and manual.exists())

    def test_failure_preserves_recovery(self):
        self.result['success'] = False
        self.write_result()
        self.assertFalse(update_cleanup.cleanup(self.folder, self.target))
        self.assertTrue(self.backup.exists() and self.folder.exists())

    def test_running_helper_is_preserved(self):
        self.result['helper_pid'] = os.getpid()
        self.write_result()
        self.assertFalse(update_cleanup.cleanup(self.folder, self.target))
        self.assertTrue(self.backup.exists())

    def test_unrelated_backup_is_preserved(self):
        self.result['backup'] = str(self.target)
        self.write_result()
        self.assertFalse(update_cleanup.cleanup(self.folder, self.target))
        self.assertTrue(self.target.exists())

    def test_no_health_preserves_recovery(self):
        (self.folder / 'new-app-ready').unlink()
        self.assertFalse(update_cleanup.cleanup(self.folder, self.target))
        self.assertTrue(self.backup.exists())

    def test_outside_transaction_directory_is_rejected(self):
        self.assertFalse(update_cleanup.cleanup(self.base, self.target))
        self.assertTrue(self.target.exists())


if __name__ == '__main__':
    unittest.main()
