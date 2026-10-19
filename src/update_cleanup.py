"""Remove only successful updater transactions for the installed application."""
import json
from pathlib import Path
import re
import shutil
import sys
import time
from threading import Thread
import updater


def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def cleanup(directory, target):
    """Keep recovery files unless health, success and every path agree."""
    directory, target = Path(directory), Path(target).resolve()
    base = (updater.data_directory() / 'updates').resolve()
    if directory.is_symlink() or directory.resolve().parent != base or not re.fullmatch(r'[0-9a-f]{32}', directory.name):
        return False
    directory = directory.resolve()
    try:
        job = json.loads((directory / 'job.json').read_text(encoding='utf-8'))
        result_file = directory / 'result.json'
        result = json.loads(result_file.read_text(encoding='utf-8'))
        if result.get('success') is not True or not target.exists():
            return False
        if Path(job['target']).resolve() != target:
            return False
        health = directory / 'new-app-ready'
        if Path(job['health']).resolve() != health or health.read_text() != 'ready':
            return False
        if time.time() - result_file.stat().st_mtime < 2:
            return False
        helper_pid = result.get('helper_pid')
        if helper_pid:
            from update_installer import process_alive
            if process_alive(int(helper_pid)):
                return False
        backup = Path(result['backup'])
        expected = re.escape(target.stem) + r'\.previous-[0-9a-f]{8}' + re.escape(target.suffix)
        if backup.is_symlink() or backup.resolve().parent != target.parent or not re.fullmatch(expected, backup.name):
            return False
        remove(backup)
        # Keep transaction metadata until bulky files (including the helper) are gone.
        metadata = {'job.json', 'result.json', 'new-app-ready'}
        for child in directory.iterdir():
            if child.name not in metadata:
                if not child.is_symlink() and child.resolve().parent != directory:
                    return False
                remove(child)
        for name in metadata:
            (directory / name).unlink(missing_ok=True)
        directory.rmdir()
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def schedule():
    """Retry after helper exit; later launches also recover interrupted cleanup."""
    if not getattr(sys, 'frozen', False):
        return
    def worker():
        try:
            target = updater.installed_target()
            base = updater.data_directory() / 'updates'
            for _ in range(15):
                if not base.is_dir():
                    return
                pending = False
                for directory in list(base.iterdir()):
                    if directory.is_dir() and re.fullmatch(r'[0-9a-f]{32}', directory.name):
                        if not cleanup(directory, target):
                            pending = True
                if not pending:
                    return
                time.sleep(2)
        except (OSError, ValueError):
            pass
    Thread(target=worker, daemon=True, name='xrd-update-cleanup').start()
