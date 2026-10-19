"""Background GitHub release checks, isolated from XRD releases and settings."""
import json
import os
import sys
from pathlib import Path
from queue import Queue, Empty
import re
from threading import Thread
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import webbrowser

DEFAULT_REPOSITORY = 'Greenbean0123/xrd-plotter'
TAG_PREFIX = 'uvvis-v'


def settings_path():
    base = Path.home() / 'Library' / 'Application Support' if sys.platform == 'darwin' else Path(os.environ.get('LOCALAPPDATA', Path.home()))
    return base / 'UV-Vis Plotter' / 'updates.json'


def preferences():
    result = dict(repository=DEFAULT_REPOSITORY, automatic=True)
    try:
        data = json.loads(settings_path().read_text(encoding='utf-8'))
        validate_repository(data['repository'])
        result.update(repository=data['repository'], automatic=data['automatic'] is True)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return result


def validate_repository(repository):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Enter a GitHub repository as owner/repository.')


def release_candidate(releases, version):
    current = tuple(map(int, version.split('.')))
    candidates = []
    for release in releases:
        match = re.fullmatch(re.escape(TAG_PREFIX) + r'(\d+)\.(\d+)\.(\d+)', release.get('tag_name', ''))
        if match and not release.get('draft') and not release.get('prerelease'):
            candidates.append((tuple(map(int, match.groups())), release))
    if not candidates:
        return 'unpublished', None
    newest, release = max(candidates, key=lambda pair: pair[0])
    return ('available', release) if newest > current else ('current', None)


def check(repository, version):
    validate_repository(repository)
    releases = []
    # Paginate so XRD release history cannot hide a UV-Vis version.
    for page in range(1, 11):
        request = Request(f'https://api.github.com/repos/{repository}/releases?per_page=100&page={page}',
                          headers={'User-Agent': 'UV-Vis-Plotter', 'Accept': 'application/vnd.github+json'})
        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
        except HTTPError as exc:
            if exc.code == 404:
                raise ValueError('GitHub repository was not found or is private.') from exc
            raise
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('GitHub response is too large.')
        batch = json.loads(raw)
        if not isinstance(batch, list):
            raise ValueError('Unexpected GitHub response.')
        releases.extend(batch)
        if len(batch) < 100:
            return release_candidate(releases, version)
    raise ValueError('Release history is too long. Use a dedicated UV-Vis repository.')


def attach(root, parent, version):
    import tkinter as tk
    from tkinter import ttk, messagebox
    config = preferences()
    events = Queue()
    state = dict(busy=False, closed=False)
    frame = ttk.LabelFrame(parent, text=f'Updates · v{version}', padding=6)
    frame.pack(fill='x', pady=8)
    automatic = tk.BooleanVar(value=config['automatic'])
    status = ttk.Label(frame, text='Ready to check for updates.', wraplength=260)

    def save():
        try:
            config.update(automatic=automatic.get())
            path = settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(config, indent=2), encoding='utf-8')
            return True
        except Exception as exc:
            messagebox.showerror('Update settings', str(exc), parent=root)
            return False

    def start(manual=True):
        if state['busy'] or not save():
            return
        state.update(busy=True, manual=manual)
        button.configure(state='disabled')
        status.configure(text='Checking GitHub…')
        selected_repository = config['repository']
        def worker():
            try:
                events.put(('result', (selected_repository, check(selected_repository, version))))
            except Exception as exc:
                events.put(('error', str(exc)))
        Thread(target=worker, daemon=True).start()

    ttk.Checkbutton(frame, text='Check automatically on startup', variable=automatic, command=save).pack(anchor='w')
    button = ttk.Button(frame, text='Check for Updates', command=start)
    button.pack(fill='x')
    status.pack(anchor='w', pady=4)

    def poll():
        if state['closed']:
            return
        try:
            while True:
                kind, value = events.get_nowait()
                state['busy'] = False
                button.configure(state='normal')
                if kind == 'error':
                    status.configure(text=f'Update check failed: {value}')
                    if state.get('manual'):
                        messagebox.showerror('Update check', value, parent=root)
                    continue
                repo, (result, release) = value
                if result == 'available':
                    tag = release['tag_name']
                    status.configure(text=f'{tag} is available.')
                    if messagebox.askyesno('UV-Vis update', f'{tag} is available.\nOpen the GitHub release page to download it?', parent=root):
                        webbrowser.open(f'https://github.com/{repo}/releases/tag/{tag}')
                else:
                    text = 'No published UV-Vis releases yet.' if result == 'unpublished' else f'Version {version} is up to date.'
                    status.configure(text=text)
                    if state.get('manual'):
                        messagebox.showinfo('Update check', text, parent=root)
        except Empty:
            pass
        root.after(150, poll)

    def destroyed(event):
        if event.widget is root:
            state['closed'] = True
    root.bind('<Destroy>', destroyed, add='+')
    root.after(150, poll)
    if config['automatic']:
        root.after(2500, lambda: start(False))
