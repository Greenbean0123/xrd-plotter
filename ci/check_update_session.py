"""Desktop regression: restoring a previous release's update session."""
from pathlib import Path
import json
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import updater
import xrd_plotter


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


with tempfile.TemporaryDirectory() as directory:
    data = Path(directory)
    sample = (ROOT / 'demo-data' / 'Synthetic Demo A.csv').resolve()
    snapshot = {'groups': {'samples': [[{'path': str(sample)}, 'Saved custom label', '#ff6600',
                    {'_order_id': 'saved-pattern', '_visible': True}]], 'cards': []},
                'order': ['saved-pattern'], 'variables': {'color': '#ff0000', 'dpi': '200', 'title': 'Saved plot'},
                'palette': ['#ff0000', '#00ff00'], 'theme': 'Dark', 'scale': '125%'}
    (data / 'update-session.json').write_text(json.dumps(snapshot), encoding='utf-8')
    with patch.object(updater, 'data_directory', return_value=data):
        root = tk.Tk()
        try:
            xrd_plotter.gui(str(xrd_plotter.default_input_dir()), root=root)
            widgets = list(descendants(root))
            book = next(w for w in widgets if isinstance(w, ttk.Notebook))
            settings = root.nametowidget(book.tabs()[2])
            book.select(settings)
            root.update()
            combos = [w for w in descendants(settings) if isinstance(w, ttk.Combobox)]
            assert next(w for w in combos if 'Dark' in w.cget('values')).get() == 'Dark'
            assert next(w for w in combos if '125%' in w.cget('values')).get() == '125%'
            assert root.cget('background') == '#182130'
            tree = next(w for w in widgets if isinstance(w, ttk.Treeview))
            assert tree.get_children() == ('saved-pattern',)
            assert tree.item('saved-pattern', 'values')[1].endswith('Saved custom label')
            entries = [w for w in widgets if isinstance(w, ttk.Entry)]
            assert any(w.get() == '#ff0000' for w in entries)
            assert any(w.get() == 'Saved plot' for w in entries)
            assert not (data / 'update-session.json').exists()
        finally:
            root.destroy()
print('Saved labels, ordering, colors, layout, dark mode and UI scale restored successfully.')
