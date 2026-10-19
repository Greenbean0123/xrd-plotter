"""Persistent startup data, independent of the installed application."""
import json
from pathlib import Path
import updater


def preference_path():
    return updater.data_directory() / 'startup-data.json'


def selected_folder():
    try:
        value = json.loads(preference_path().read_text(encoding='utf-8'))['folder']
        return Path(value).expanduser()
    except (OSError, ValueError, KeyError, TypeError):
        return None


def prepare_folder(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name in ('patterns', 'references'):
        (folder / name).mkdir(exist_ok=True)
    readme = folder / 'README.txt'
    if not readme.exists():
        readme.write_text('XRD Plotter startup data\n\n'
            'patterns/: sample CSV files (2theta, Yobs, Bkg columns).\n'
            'references/: PDF, CIF, XY or reference CSV files.\n'
            'Files load automatically on startup. Use Reload Defaults after adding files.\n'
            'Legacy files in this folder also work: CSV samples and PDF/CIF/XY references.\n'
            'Application updates do not remove this folder.\n', encoding='utf-8')
    return folder


def choose_folder(folder):
    folder = prepare_folder(Path(folder).expanduser().resolve())
    target = preference_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'folder': str(folder)}), encoding='utf-8')
    temporary.replace(target)
    return folder


def discover(folder):
    folder = Path(folder)
    def files(directory, extensions):
        if not directory.is_dir():
            return []
        return sorted((p for p in directory.iterdir() if p.is_file() and
                       p.suffix.lower() in extensions), key=lambda p: p.name.casefold())
    samples = files(folder, ('.csv',)) + files(folder / 'patterns', ('.csv',))
    cards = files(folder, ('.pdf', '.cif', '.xy')) + files(
        folder / 'references', ('.pdf', '.cif', '.xy', '.csv'))
    return samples, cards
