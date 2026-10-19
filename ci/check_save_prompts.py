"""Verify the persisted export confirmation switch against real PNG exports."""
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import updater
import ui_preferences
import xrd_plotter

def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)

with tempfile.TemporaryDirectory() as directory:
    base = Path(directory)
    with patch.object(updater, 'data_directory', return_value=base):
        root = tk.Tk()
        try:
            xrd_plotter.gui(str(ROOT / 'demo-data'), root=root)
            widgets = list(descendants(root))
            switch = next(w for w in widgets if isinstance(w, ttk.Checkbutton) and w.cget('text') == 'Show save success messages')
            export = next(w for w in widgets if isinstance(w, ttk.Button) and w.cget('text') == 'PNG')
            assert ui_preferences.load()['save_success_prompt']
            with patch('tkinter.filedialog.asksaveasfilename', return_value=str(base / 'plot.png')), patch('tkinter.messagebox.showinfo') as notice, patch('tkinter.messagebox.showerror') as error:
                switch.invoke()
                assert not ui_preferences.load()['save_success_prompt']
                export.invoke()
                assert (base / 'plot.png').is_file()
                assert not notice.called and not error.called
                switch.invoke()
                assert ui_preferences.load()['save_success_prompt']
                export.invoke()
                assert notice.call_count == 1 and not error.called
                switch.invoke()
        finally:
            root.destroy()
        root = tk.Tk()
        try:
            xrd_plotter.gui(str(ROOT / 'demo-data'), root=root)
            switch = next(w for w in descendants(root) if isinstance(w, ttk.Checkbutton) and w.cget('text') == 'Show save success messages')
            assert not root.getvar(switch.cget('variable'))
        finally:
            root.destroy()
print('Real PNG exports honor the switch; preference survives a fresh GUI.')
