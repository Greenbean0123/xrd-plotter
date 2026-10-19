"""Run with Python from this folder; no network or user dialogs required."""
import tempfile
from pathlib import Path
from unittest.mock import patch
import tkinter as tk
import numpy as np
from PIL import Image
from matplotlib.figure import Figure
from uvvis_plotter import App
from uvvis_updates import release_candidate


def main():
    root = tk.Tk()
    root.withdraw()
    with patch('uvvis_updates.attach'):
        app = App(root)
    try:
        x, y = np.array([600., 700., 800.]), np.array([1., 2., 3.])
        app.spectra = [dict(x=x, y=y, label='Shown', color='blue', show=True, export=False),
                       dict(x=x, y=y, label='Exported', color='red', show=False, export=True)]
        app.refresh_list(0)
        app.select()
        app.update()
        assert [line.get_label() for line in app.ax.lines] == ['Shown']
        # Invoke actual checkbox commands, including Matplotlib's grid-off behavior.
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        controls = {str(w.cget('text')): w for w in descendants(root) if w.winfo_class() == 'TCheckbutton'}
        controls['Grid'].invoke()
        controls['Legend'].invoke()
        assert app.ax.get_legend() is None
        assert not any(line.get_visible() for line in app.ax.get_xgridlines())
        controls['Grid'].invoke()
        controls['Legend'].invoke()
        assert app.ax.get_legend() is not None
        assert any(line.get_visible() for line in app.ax.get_xgridlines())
        root.deiconify()
        root.geometry('1050x680')
        root.update()
        widgets = list(descendants(root))
        entry = next(w for w in widgets if w.winfo_class() == 'TEntry')
        dropdown = next(w for w in widgets if w.winfo_class() == 'TCombobox')
        app.sidebar_scroll.yview_moveto(0)
        entry.event_generate('<MouseWheel>', delta=-120)
        root.update()
        assert app.sidebar_scroll.yview()[0] > 0
        entry.event_generate('<MouseWheel>', delta=120)
        root.update()
        assert app.sidebar_scroll.yview()[0] == 0
        dropdown.event_generate('<MouseWheel>', delta=-120)
        root.update()
        assert app.sidebar_scroll.yview()[0] > 0
        assert app.mode.get() == app.MODES[0]
        assert not any('UVVisSidebarWheel' in tag for tag in app.canvas.get_tk_widget().bindtags())
        # High-resolution wheels accumulate fractional deltas.
        app.sidebar_scroll.yview_moveto(0)
        for _ in range(4):
            entry.event_generate('<MouseWheel>', delta=-30)
        root.update()
        assert app.sidebar_scroll.yview()[0] > 0
        root.withdraw()
        figure = Figure(figsize=(6, 4))
        app.update('export', figure)
        assert [line.get_label() for line in figure.axes[0].lines] == ['Exported']
        assert app.ax.lines[0].get_label() == 'Shown'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sized.png'
            figure.savefig(path, dpi=100)
            with Image.open(path) as image:
                assert image.size == (600, 400)
            path = Path(folder) / 'selected.csv'
            with patch('uvvis_plotter.filedialog.asksaveasfilename', return_value=str(path)):
                app.export_data()
            text = path.read_text(encoding='utf-8-sig')
            assert 'Exported' in text and 'Shown' not in text
        releases = [{'tag_name': 'v99.0.0'}, {'tag_name': 'uvvis-v0.0.2'},
                    {'tag_name': 'uvvis-v8.0.0', 'prerelease': True}]
        assert release_candidate(releases, '0.0.1')[1]['tag_name'] == 'uvvis-v0.0.2'
        assert release_candidate(releases, '0.0.2')[0] == 'current'
        assert release_candidate([{'tag_name': 'v99.0.0'}], '0.0.1')[0] == 'unpublished'
        print('PASS: sidebar wheel over controls, dropdown stability, high-resolution wheel, checkbox commands, show/export selection, CSV, dimensions, GitHub version filtering.')
    finally:
        root.destroy()


if __name__ == '__main__':
    main()
