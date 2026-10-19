"""Mac entry point, with a frozen-app smoke check for the build runner."""
from pathlib import Path
import sys
import tkinter as tk
from uvvis_plotter import App


def main():
    smoke = len(sys.argv) == 3 and sys.argv[1] == '--smoke-test'
    root = tk.Tk()
    if smoke:
        root.withdraw()
    app = App(root)
    if smoke:
        import numpy as np
        from matplotlib.figure import Figure
        folder = Path(sys.argv[2])
        folder.mkdir(parents=True, exist_ok=True)
        app.spectra = [dict(x=np.array([400., 500., 600.]), y=np.array([0.2, 1., 0.5]),
                           label='Synthetic trial check', color='blue', show=True, export=True)]
        app.refresh_list(0)
        root.update()
        app.update()
        assert len(app.ax.lines) == 1
        figure = Figure(figsize=(6, 4))
        app.update('export', figure)
        assert len(figure.axes[0].lines) == 1
        for suffix in ('png', 'pdf', 'svg'):
            figure.savefig(folder / ('smoke.' + suffix), dpi=100)
        root.destroy()
        (folder / 'ready.txt').write_text('GUI and PNG/PDF/SVG export passed', encoding='utf-8')
    else:
        root.mainloop()


if __name__ == '__main__':
    main()
