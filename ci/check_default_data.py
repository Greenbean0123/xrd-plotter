"""Desktop regression for persistent startup folders and reference-only plots."""
from pathlib import Path
import shutil
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import default_data
import updater
import xrd_plotter


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


with tempfile.TemporaryDirectory() as directory:
    base = Path(directory)
    with patch.object(updater, 'data_directory', return_value=base):
        folder = default_data.choose_folder(base / 'my defaults')
        assert xrd_plotter.default_input_dir() == folder
        assert default_data.selected_folder() == folder
        reference = next((ROOT / 'demo-data').glob('*.xy'))
        shutil.copy2(reference, folder / 'references' / reference.name)
        (folder / 'references' / 'Broken.cif').write_text('invalid CIF')
        (folder / 'references' / 'CSV card.csv').write_text('2theta,intensity\n20,100\n40,50\n')
        samples, cards = default_data.discover(folder)
        assert not samples and len(cards) == 3
        root = tk.Tk()
        try:
            with patch('tkinter.messagebox.showwarning') as warning, patch('tkinter.messagebox.showerror') as error, patch.object(xrd_plotter, 'make_figure', wraps=xrd_plotter.make_figure) as plot:
                xrd_plotter.gui(str(folder), root=root)
                root.update()
                assert warning.call_count == 1
                assert not error.called, error.call_args
                widgets = list(descendants(root))
                tree = next(w for w in widgets if isinstance(w, ttk.Treeview))
                assert len(tree.get_children()) == 2
                assert plot.called
                assert not plot.call_args.args[0] and len(plot.call_args.args[1]) == 2
                reload_button = next(w for w in widgets if isinstance(w, ttk.Button) and w.cget('text') == 'Reload Defaults')
                (folder / 'references' / 'CSV card.csv').unlink()
                with patch('tkinter.messagebox.askyesno', return_value=True):
                    reload_button.invoke()
                root.update()
                assert len(tree.get_children()) == 1
                assert not error.called, error.call_args
        finally:
            root.destroy()
print('Persistent selection, nested reference CSV, reference-only startup, invalid-file warning and reload passed.')
