"""Detached, transactional installer executed from a copy of the running app."""
from pathlib import Path, PurePosixPath
import ctypes
import hashlib
import json
import os
import plistlib
import shutil
import signal
import stat
import struct
import subprocess
import sys
import time
import uuid
import zipfile
import updater


def process_alive(pid):
    if pid <= 0:
        return False
    if sys.platform == 'win32':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        try:
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def validate_zip(package):
    with zipfile.ZipFile(package) as archive:
        total = 0
        paths = []
        links = {}
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in item.filename:
                raise ValueError('Unsafe path in update ZIP.')
            if not path.parts or path.parts[0] not in ('XRD Plotter.app', '__MACOSX'):
                raise ValueError('Update ZIP must contain XRD Plotter.app.')
            paths.append(path)
            total += item.file_size
            if total > 2 * updater.MAX_DOWNLOAD:
                raise ValueError('Unpacked update is too large.')
            if stat.S_ISLNK(item.external_attr >> 16):
                link = archive.read(item).decode('utf-8')
                if link.startswith('/') or '\\' in link:
                    raise ValueError('Unsafe symlink in update ZIP.')
                links[path.parts] = PurePosixPath(link).parts
        # Resolve the entire symlink graph, including symlink ancestors. Checking
        # each link in isolation would miss an escaping chain through a parent.
        for path in paths:
            if any(path.parts[:index] in links for index in range(1, len(path.parts))):
                raise ValueError('Update ZIP contains entries beneath a symlink directory.')
            pending, components, followed = list(path.parts), [], 0
            while pending:
                part = pending.pop(0)
                if part == '..':
                    if len(components) <= 1:
                        raise ValueError('Update symlink escapes its application bundle.')
                    components.pop()
                elif part != '.':
                    components.append(part)
                    key = tuple(components)
                    if key in links:
                        followed += 1
                        if followed > 40:
                            raise ValueError('Cyclic or excessively deep update symlinks.')
                        components.pop()
                        pending = list(links[key]) + pending
            if not components or components[0] != path.parts[0]:
                raise ValueError('Update symlink escapes its application bundle.')


def prepare_replacement(package, target, release):
    staged = target.with_name(f'.xrd-update-{uuid.uuid4().hex}{target.suffix}')
    if release['asset']['format'] == 'exe':
        with package.open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise ValueError('Update is not a Windows executable.')
            stream.seek(0x3c)
            pe_offset = struct.unpack('<I', stream.read(4))[0]
            stream.seek(pe_offset)
            if stream.read(4) != b'PE\x00\x00' or struct.unpack('<H', stream.read(2))[0] != 0x8664:
                raise ValueError('Update is not an x64 Windows executable.')
        shutil.copy2(package, staged)
    else:
        validate_zip(package)
        extracted = package.parent / ('extract-' + uuid.uuid4().hex)
        extracted.mkdir()
        subprocess.run(['ditto', '-x', '-k', str(package), str(extracted)], check=True, timeout=120)
        app = extracted / 'XRD Plotter.app'
        with (app / 'Contents' / 'Info.plist').open('rb') as stream:
            info = plistlib.load(stream)
        if (info.get('CFBundleIdentifier') != 'org.xrdplotter.app' or
                info.get('CFBundleShortVersionString') != release['version']):
            raise ValueError('The Mac application identity or version does not match the release.')
        executable = app / 'Contents' / 'MacOS' / info['CFBundleExecutable']
        expected_arch = release['platform'].split('-', 1)[1]
        if expected_arch not in subprocess.check_output(['lipo', '-archs', str(executable)], text=True).split():
            raise ValueError('The Mac application architecture does not match this computer.')
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True, timeout=60)
        shutil.copytree(app, staged, symlinks=True)
    return staged


def rename_with_retry(source, destination):
    deadline = time.monotonic() + 15
    while True:
        try:
            source.replace(destination)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def launch(target, health=None):
    executable = target / 'Contents' / 'MacOS' / 'XRD Plotter' if target.suffix == '.app' else target
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
    env.pop('XRD_UPDATE_HEALTH_FILE', None)
    if health:
        env['XRD_UPDATE_HEALTH_FILE'] = str(health)
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {'start_new_session': True}
    return subprocess.Popen([str(executable)], cwd=target.parent, env=env, **kwargs)


def replace_and_restart(target, staged, health, launch_app=launch, timeout=120):
    backup = target.with_name(f'{target.stem}.previous-{uuid.uuid4().hex[:8]}{target.suffix}')
    rename_with_retry(target, backup)
    process = None
    try:
        rename_with_retry(staged, target)
        process = launch_app(target, health)
        deadline = time.monotonic() + timeout
        while not health.exists():
            if process.poll() is not None:
                raise RuntimeError('The updated application exited before it was ready.')
            if time.monotonic() >= deadline:
                raise RuntimeError('The updated application did not become ready in time.')
            time.sleep(0.2)
        return backup
    except Exception:
        if process is not None and process.poll() is None:
            # Stop only the updater-started process tree before restoring Windows files.
            if sys.platform == 'win32':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        if target.exists():
            failed = target.with_name(f'{target.stem}.failed-{uuid.uuid4().hex[:8]}{target.suffix}')
            rename_with_retry(target, failed)
        rename_with_retry(backup, target)
        launch_app(target)
        raise


def run(job_path):
    job = json.loads(Path(job_path).read_text(encoding='utf-8'))
    result_path = Path(job['result'])
    try:
        from app_version import __version__
        release = updater.verify_manifest(job['release']['envelope'], updater.bundled_config()['public_key'], __version__)
        if release is None:
            raise ValueError('The update must be newer than the current application.')
        package, target = Path(job['package']).resolve(), Path(job['target']).resolve()
        with package.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if package.stat().st_size != release['asset']['size'] or digest != release['asset']['sha256'].lower():
            raise ValueError('The downloaded package changed after verification.')
        if target.suffix != ('.app' if sys.platform == 'darwin' else '.exe'):
            raise ValueError('Invalid application target.')
        staged = prepare_replacement(package, target, release)
        Path(job['ready']).write_text('ready')
        deadline = time.monotonic() + 90
        approval = Path(job['ready']).parent / 'install-approved'
        cancellation = Path(job['ready']).parent / 'cancel'
        pids = [int(job['parent_pid'])]
        if sys.platform == 'win32':
            pids.append(int(job['parent_bootloader_pid']))
        while not approval.exists() or any(process_alive(pid) for pid in pids):
            if cancellation.exists():
                raise RuntimeError('Update installation was cancelled; the installed app was not changed.')
            if time.monotonic() >= deadline:
                raise TimeoutError('The running application did not exit; update was not installed.')
            time.sleep(0.25)
        if cancellation.exists():
            raise RuntimeError('Update installation was cancelled.')
        backup = replace_and_restart(target, staged, Path(job['health']))
        result_path.write_text(json.dumps({'success': True, 'backup': str(backup), 'helper_pid': os.getpid()}), encoding='utf-8')
    except Exception as error:
        result_path.write_text(json.dumps({'success': False, 'error': str(error)}), encoding='utf-8')
        import traceback
        traceback.print_exc()
        if process_alive(int(job.get('parent_pid', 0))):
            return 1  # The running application's UI reports preparation errors.
        # The original app may already have exited; show errors without a terminal.
        try:
            import tkinter as tk
            from tkinter import messagebox
            window = tk.Tk()
            window.withdraw()
            messagebox.showerror('XRD Plotter update', f'{error}\n\nDetails: {result_path.parent}', parent=window)
            window.destroy()
        except Exception:
            pass
        return 1
    return 0
