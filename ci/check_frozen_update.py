"""Windows-only full installer smoke test in a disposable installation.

Reinstalls the same test binary under a simulated future manifest version.
This does not publish a release or replace the real installed application.
"""
from pathlib import Path
import base64
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


def main():
    if sys.platform != 'win32':
        raise SystemExit('This integration smoke test is for Windows.')
    built = ROOT / 'dist' / 'XRD Plotter.exe'
    private = serialization.load_pem_private_key(
        (ROOT / '.release-keys' / 'update-signing-key.pem').read_bytes(), password=None)
    with tempfile.TemporaryDirectory(prefix='xrd-update-smoke-') as directory:
        folder = Path(directory)
        install = folder / 'installed'
        install.mkdir()
        target = install / 'XRD Plotter.exe'
        package, helper = folder / 'package.exe', folder / 'helper.exe'
        for path in (target, package, helper):
            shutil.copy2(built, path)
        payload = {'schema': 1, 'version': '0.0.3', 'notes': 'Isolated smoke test only', 'assets': {
            'windows-x86_64': {'url': 'https://example.test/test.exe', 'format': 'exe',
                'size': package.stat().st_size, 'sha256': hashlib.sha256(package.read_bytes()).hexdigest()}}}
        envelope = {'payload': payload, 'signature': base64.b64encode(private.sign(updater.canonical(payload))).decode()}
        release = updater.verify_manifest(envelope, updater.bundled_config()['public_key'], '0.0.2')
        parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(180)'])
        job = {'target': str(target), 'package': str(package), 'release': release,
               'parent_pid': parent.pid, 'parent_bootloader_pid': 0,
               'ready': str(folder / 'helper-ready'), 'health': str(folder / 'new-app-ready'),
               'result': str(folder / 'result.json')}
        job_file = folder / 'job.json'
        job_file.write_text(json.dumps(job), encoding='utf-8')
        process = None
        try:
            with (folder / 'installer.log').open('wb') as log:
                process = subprocess.Popen([str(helper), '--apply-update', str(job_file)],
                    env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1'),
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
            assert Path(result['backup']).exists()
            print('Frozen helper readiness, parent-exit wait, replacement, GUI restart and backup verified.')
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
