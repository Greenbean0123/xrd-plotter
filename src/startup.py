"""Show a responsive startup window before importing scientific libraries."""
import sys
import time
import traceback
from pathlib import Path
from queue import Queue, Empty
from threading import Thread


def launch():
    if len(sys.argv) == 3 and sys.argv[1] == '--apply-update':
        from update_installer import run
        raise SystemExit(run(sys.argv[2]))
    if '--output' in sys.argv or any(arg.startswith('--output=') for arg in sys.argv) or any(
            arg in sys.argv for arg in ('--version', '--help', '-h')):
        import xrd_plotter
        xrd_plotter.main()
        return
    import tkinter as tk
    from tkinter import ttk, messagebox
    root = tk.Tk()
    root.title('XRD Plotter')
    root.geometry('520x170')
    root.configure(background='#f3f5f9')
    panel = ttk.Frame(root, padding=28)
    panel.pack(fill='both', expand=True)
    ttk.Label(panel, text='XRD Plotter', font=('Helvetica', 20, 'bold')).pack(anchor='w')
    status = ttk.Label(panel, text='Loading plotting libraries…')
    status.pack(anchor='w', pady=(12, 8))
    progress = ttk.Progressbar(panel, mode='indeterminate')
    progress.pack(fill='x')
    progress.start(15)
    results = Queue()
    started = time.perf_counter()

    def prepare():
        try:
            import xrd_plotter
            # Parse defaults off the UI thread and warm the reference cache.
            folder = xrd_plotter.default_input_dir()
            for index, arg in enumerate(sys.argv[:-1]):
                if arg == '--input-dir':
                    folder = Path(sys.argv[index + 1])
            for arg in sys.argv:
                if arg.startswith('--input-dir='):
                    folder = Path(arg.split('=', 1)[1])
            results.put(('status', 'Loading default patterns and reference cards…'))
            for path in xrd_plotter.discover(folder)[1]:
                try:
                    xrd_plotter.read_card(path)
                except Exception:
                    pass  # The GUI reports invalid files while keeping valid defaults available.
            results.put(('ready', (xrd_plotter, folder)))
        except Exception:
            results.put(('error', traceback.format_exc()))

    def poll():
        try:
            while True:
                kind, value = results.get_nowait()
                if kind == 'status':
                    status.configure(text=value)
                elif kind == 'error':
                    progress.stop()
                    status.configure(text='Startup failed.')
                    messagebox.showerror('XRD Plotter', value, parent=root)
                    root.destroy()
                    return
                elif kind == 'ready':
                    module, folder = value
                    progress.stop()
                    # GUI widgets and all Tk calls remain on the main thread.
                    module.gui(str(folder), root=root)
                    root._startup_seconds = time.perf_counter() - started
                    import os
                    health = os.environ.pop('XRD_UPDATE_HEALTH_FILE', '')
                    if health:
                        root.after(250, lambda: Path(health).write_text('ready'))
                    return
        except Empty:
            root.after(50, poll)

    # Give the window an opportunity to paint before starting imports.
    root.after(100, lambda: Thread(target=prepare, daemon=True).start())
    root.after(150, poll)
    root.mainloop()


if __name__ == '__main__':
    launch()
