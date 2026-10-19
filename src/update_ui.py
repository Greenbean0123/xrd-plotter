"""Tk update controls; worker threads never access Tk widgets."""
from pathlib import Path
from queue import Queue, Empty
from threading import Thread
import json
import time
import updater


def attach(root, parent, version, before_restart=None):
    from tkinter import ttk, messagebox, simpledialog
    events = Queue()
    state = {'busy': False, 'closed': False, 'installer': None}
    frame = ttk.Frame(parent)
    frame.pack(fill='x', pady=(5, 0))
    status = ttk.Label(frame, text=f'Version {version}', wraplength=330)
    status.pack(anchor='w')

    def busy(value):
        state['busy'] = value
        check_button.configure(state='disabled' if value else 'normal')
        settings_button.configure(state='disabled' if value else 'normal')

    def work(function, kind, *args):
        def run():
            try:
                events.put((kind, function(*args)))
            except Exception as error:
                events.put(('error', str(error)))
        Thread(target=run, daemon=True).start()

    def check(manual=True):
        if state['busy']:
            return
        state['manual'] = manual
        busy(True)
        status.configure(text='Checking for updates…')
        work(updater.check, 'checked', version)

    def settings():
        config = updater.preferences()
        url = simpledialog.askstring('Update Settings',
            'HTTPS address of the signed update manifest\nLeave empty to disable update checks:',
            initialvalue=config['manifest_url'], parent=root)
        if url is None:
            return
        automatic = messagebox.askyesno('Update Settings', 'Check for updates automatically after startup?', parent=root)
        try:
            updater.save_preferences(url.strip(), automatic)
            status.configure(text='Update settings saved.' if url.strip() else 'Update server not configured.')
        except Exception as error:
            messagebox.showerror('Update Settings', str(error), parent=root)

    buttons = ttk.Frame(frame)
    buttons.pack(fill='x', pady=3)
    check_button = ttk.Button(buttons, text='Check for Updates', command=check)
    check_button.pack(side='left', fill='x', expand=True)
    settings_button = ttk.Button(buttons, text='Update Settings', command=settings)
    settings_button.pack(side='left', padx=(5, 0))

    def poll():
        if state['closed']:
            return
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == 'error':
                    busy(False)
                    status.configure(text=value)
                    if state.get('manual', True):
                        messagebox.showerror('XRD Plotter update', value, parent=root)
                elif kind == 'checked':
                    if value is None:
                        busy(False)
                        status.configure(text=f'Version {version} is up to date.')
                        if state.get('manual'):
                            messagebox.showinfo('XRD Plotter update', 'You are using the latest version.', parent=root)
                    else:
                        state['release'] = value
                        question = (f"Version {value['version']} is available.\n\n{value['notes'][:3000]}\n\n"
                                    'Download, install and restart now? Your input files will not be changed.')
                        if not messagebox.askyesno('Update and Restart', question, parent=root):
                            busy(False)
                            status.configure(text=f"Update {value['version']} is available.")
                            continue
                        try:
                            updater.installed_target()
                        except Exception as error:
                            events.put(('error', str(error)))
                            continue
                        status.configure(text='Downloading update…')
                        state['manual'] = True
                        last = [0.0]
                        def progress(done, total):
                            now = time.monotonic()
                            if now - last[0] > 0.15 or done == total:
                                events.put(('progress', (done, total)))
                                last[0] = now
                        work(lambda release=value: updater.download(release, progress), 'downloaded')
                elif kind == 'progress':
                    done, total = value
                    status.configure(text=f'Downloading update… {done * 100 // total}%')
                elif kind == 'downloaded':
                    status.configure(text='Preparing update installer…')
                    work(updater.start_installer, 'installer', value, state['release'])
                elif kind == 'installer':
                    process, ready = value
                    state['installer'] = (process, ready, time.monotonic() + 180)
                    status.configure(text='Verifying and preparing replacement…')
        except Empty:
            pass
        if state['installer']:
            process, ready, deadline = state['installer']
            if ready.exists():
                try:
                    if before_restart:
                        before_restart()
                    (ready.parent / 'install-approved').write_text('approved')
                    state['closed'] = True
                    root.destroy()
                    return
                except Exception as error:
                    (ready.parent / 'cancel').write_text('cancelled')
                    events.put(('error', f'Could not save the update session: {error}'))
                    state['installer'] = None
            elif process.poll() is not None or time.monotonic() > deadline:
                if process.poll() is None:
                    (ready.parent / 'cancel').write_text('cancelled')
                result = ready.parent / 'result.json'
                try:
                    error = json.loads(result.read_text(encoding='utf-8')).get('error', 'Installer failed to start.')
                except (OSError, ValueError):
                    error = f'Installer did not become ready. See {ready.parent / "installer.log"}'
                events.put(('error', error))
                state['installer'] = None
        root.after(100, poll)

    def destroyed(event):
        if event.widget is root:
            state['closed'] = True
    root.bind('<Destroy>', destroyed, add='+')
    root.after(100, poll)
    config = updater.preferences()
    if config['manifest_url'] and config['automatic']:
        root.after(2500, lambda: check(False))
    elif not config['manifest_url']:
        status.configure(text=f'Version {version} · Update server not configured')
