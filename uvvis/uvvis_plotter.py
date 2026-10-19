"""Standalone UV-Vis desktop plotter. English UI; experimental files stay local."""
import csv
import math
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.ticker import AutoMinorLocator
import uvvis_updates

VERSION = '0.0.1'


def read_spectrum(path):
    text = Path(path).read_bytes()
    for encoding in ('utf-8-sig', 'utf-16', 'cp1252'):
        try:
            content = text.decode(encoding)
            break
        except UnicodeError:
            continue
    else:
        raise ValueError('Cannot decode this file.')
    lines = content.splitlines()
    marker = next((i for i, s in enumerate(lines) if s.strip().upper().startswith('XYDATA')), None)
    rows = []
    started = False
    for number, line in enumerate(lines, 1):
        if marker is not None and number <= marker + 1:
            continue
        if not line.strip():
            continue
        delimiter = '\t' if '\t' in line else ';' if ';' in line else ','
        cells = next(csv.reader([line], delimiter=delimiter))
        if len(cells) < 2:
            cells = line.split()
        try:
            pair = [float(cells[0]), float(cells[1])]
        except (ValueError, IndexError):
            if started:
                if marker is not None:
                    break
                raise ValueError(f'Invalid numeric data on line {number}.')
            continue
        if not all(math.isfinite(v) for v in pair):
            raise ValueError(f'Non-finite data on line {number}.')
        rows.append(pair)
        started = True
    if len(rows) < 2:
        raise ValueError('At least two wavelength / absorbance rows are required.')
    data = np.asarray(rows)
    data = data[np.argsort(data[:, 0], kind='stable')]
    return data[:, 0], data[:, 1]


def normalize(x, y, mode, low=None, high=None):
    if mode == 'Raw absorbance':
        return y.copy(), None
    selected = y
    if mode == 'Maximum in wavelength range':
        if low is None or high is None or not np.isfinite([low, high]).all() or low >= high:
            raise ValueError('Normalization range must have a finite minimum below its maximum.')
        selected = y[(x >= low) & (x <= high)]
        if not len(selected):
            raise ValueError('No data points inside the normalization range.')
    peak = float(selected.max())
    if peak <= 0:
        raise ValueError('Normalization requires a positive maximum absorbance.')
    return y / peak, peak


class App:
    MODES = ('Global maximum', 'Maximum in wavelength range', 'Raw absorbance')

    def __init__(self, root):
        self.root = root
        root.title(f'UV-Vis Plotter {VERSION}')
        icon = Path(__file__).with_name('assets') / 'uvvis.ico'
        if sys.platform == 'win32' and icon.exists():
            root.iconbitmap(str(icon))
        else:
            png = icon.with_suffix('.png')
            if png.exists():
                self._icon = tk.PhotoImage(file=str(png))
                root.iconphoto(True, self._icon)
        root.geometry('1280x820')
        root.minsize(1050, 680)
        self.spectra = []
        self.variables = {}
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TButton', padding=6)
        scroll_panel = ttk.Frame(root)
        scroll_panel.pack(side='left', fill='y')
        scroll = tk.Canvas(scroll_panel, width=315, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_panel, orient='vertical', command=scroll.yview)
        scrollbar.pack(side='right', fill='y')
        scroll.pack(side='left', fill='y', expand=True)
        scroll.configure(yscrollcommand=scrollbar.set)
        self.sidebar_scroll = scroll
        self._wheel_remainder = 0.0
        sidebar = ttk.Frame(scroll, padding=16)
        window = scroll.create_window((0, 0), window=sidebar, anchor='nw', width=315)
        sidebar.bind('<Configure>', lambda event: scroll.configure(scrollregion=scroll.bbox('all')))
        scroll.bind('<Configure>', lambda event: scroll.itemconfigure(window, width=event.width))
        ttk.Label(sidebar, text='UV-Vis Plotter', font=('Segoe UI', 20, 'bold')).pack(anchor='w')
        ttk.Label(sidebar, text='Absorbance spectra', foreground='#64748b').pack(anchor='w', pady=(0, 12))
        buttons = ttk.Frame(sidebar)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='Add CSV files', command=self.add_files).pack(side='left')
        ttk.Button(buttons, text='Remove', command=self.remove).pack(side='right')
        self.listbox = tk.Listbox(sidebar, height=5, exportselection=False)
        self.listbox.pack(fill='x', pady=8)
        self.listbox.bind('<<ListboxSelect>>', self.select)
        self.show_curve = tk.BooleanVar(value=True)
        self.export_curve = tk.BooleanVar(value=True)
        row = ttk.Frame(sidebar)
        row.pack(fill='x')
        ttk.Checkbutton(row, text='Show selected', variable=self.show_curve, command=self.change_selection).pack(side='left')
        ttk.Checkbutton(row, text='Export selected', variable=self.export_curve, command=self.change_selection).pack(side='right')
        ttk.Label(sidebar, text='List: [Show / Export] curve name', foreground='#64748b').pack(anchor='w')
        self.field(sidebar, 'Curve label', 'label', '')
        ttk.Button(sidebar, text='Apply label / choose color', command=self.edit_curve).pack(fill='x', pady=4)
        self.field(sidebar, 'Plot title', 'title', '')
        ttk.Label(sidebar, text='Normalization').pack(anchor='w', pady=(10, 3))
        self.mode = tk.StringVar(value=self.MODES[0])
        ttk.Combobox(sidebar, textvariable=self.mode, values=self.MODES, state='readonly').pack(fill='x')
        self.mode.trace_add('write', self.mode_changed)
        row = ttk.Frame(sidebar)
        row.pack(fill='x', pady=4)
        self.field(row, 'From (nm)', 'norm_low', '600', side='left')
        self.field(row, 'To (nm)', 'norm_high', '1300', side='right')
        ttk.Label(sidebar, text='Each curve uses its own maximum.\nRange mode scales the entire curve.', foreground='#64748b').pack(anchor='w', pady=4)
        for title, low, high in [('X axis (nm)', 'xmin', 'xmax'), ('Y axis', 'ymin', 'ymax')]:
            row = ttk.LabelFrame(sidebar, text=title, padding=6)
            row.pack(fill='x', pady=5)
            self.field(row, 'Minimum', low, '', side='left')
            self.field(row, 'Maximum', high, '', side='right')
        ttk.Label(sidebar, text='Blank axis limits = automatic', foreground='#64748b').pack(anchor='w')
        self.legend = tk.BooleanVar(value=True)
        self.grid = tk.BooleanVar(value=True)
        row = ttk.Frame(sidebar)
        row.pack(fill='x', pady=5)
        ttk.Checkbutton(row, text='Legend', variable=self.legend, command=self.update).pack(side='left')
        ttk.Checkbutton(row, text='Grid', variable=self.grid, command=self.update).pack(side='right')
        row = ttk.LabelFrame(sidebar, text='Figure size', padding=6)
        row.pack(fill='x', pady=5)
        self.field(row, 'Width (inches)', 'width', '9', side='left')
        self.field(row, 'Height (inches)', 'height', '5.5', side='right')
        self.field(sidebar, 'Export resolution (DPI)', 'dpi', '300')
        ttk.Button(sidebar, text='Update plot', command=self.update).pack(fill='x', pady=4)
        ttk.Button(sidebar, text='Export figure', command=self.export_figure).pack(fill='x', pady=4)
        ttk.Button(sidebar, text='Export plotted data', command=self.export_data).pack(fill='x', pady=4)
        uvvis_updates.attach(root, sidebar, VERSION)
        self.status = tk.StringVar(value='Add CSV files to begin.')
        ttk.Label(root, textvariable=self.status, padding=8, relief='sunken').pack(side='bottom', fill='x')
        panel = ttk.Frame(root, padding=12)
        panel.pack(fill='both', expand=True)
        self.figure = Figure(figsize=(9, 5.5), dpi=100, facecolor='white')
        self.ax = self.figure.add_subplot(111)
        self.preview = ttk.Frame(panel)
        self.preview.pack(fill='both', expand=True)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.preview)
        NavigationToolbar2Tk(self.canvas, panel)
        # A scoped bind tag runs before native Entry/Combobox/Listbox bindings.
        # Scrolling settings must not change the normalization dropdown value.
        wheel_tag = f'UVVisSidebarWheel{id(self)}'
        for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            root.bind_class(wheel_tag, sequence, self.scroll_sidebar)
        def bind_sidebar(widget):
            widget.bindtags((wheel_tag,) + widget.bindtags())
            for child in widget.winfo_children():
                bind_sidebar(child)
        bind_sidebar(scroll_panel)
        self.preview.bind('<Configure>', self.fit_preview)
        self.update()

    def scroll_sidebar(self, event):
        button = getattr(event, 'num', None)
        if button in (4, 5):
            steps = -1 if button == 4 else 1
        else:
            delta = getattr(event, 'delta', 0)
            self._wheel_remainder -= delta / (1 if sys.platform == 'darwin' else 120)
            steps = math.trunc(self._wheel_remainder)
            self._wheel_remainder -= steps
        if steps:
            # Long data lists retain their own scrolling until a boundary.
            if event.widget is self.listbox:
                low, high = self.listbox.yview()
                if (steps < 0 and low > 0) or (steps > 0 and high < 1):
                    self.listbox.yview_scroll(steps, 'units')
                    return 'break'
            self.sidebar_scroll.yview_scroll(steps, 'units')
        return 'break'

    def field(self, parent, caption, name, default, side=None):
        box = ttk.Frame(parent)
        box.pack(side=side or 'top', fill='x', expand=True, pady=2)
        ttk.Label(box, text=caption).pack(anchor='w')
        var = tk.StringVar(value=default)
        self.variables[name] = var
        entry = ttk.Entry(box, textvariable=var, width=14)
        entry.pack(fill='x', padx=(0, 4))
        entry.bind('<Return>', lambda event: self.update())

    def mode_changed(self, *args):
        if hasattr(self, 'canvas'):
            self.update()

    def select(self, event=None):
        selected = self.listbox.curselection()
        if selected:
            self.variables['label'].set(self.spectra[selected[0]]['label'])
            self.show_curve.set(self.spectra[selected[0]].get('show', True))
            self.export_curve.set(self.spectra[selected[0]].get('export', True))

    def change_selection(self):
        selected = self.listbox.curselection()
        if selected:
            self.spectra[selected[0]].update(show=self.show_curve.get(), export=self.export_curve.get())
            self.refresh_list(selected[0])
            self.update()

    def refresh_list(self, selected=None):
        self.listbox.delete(0, 'end')
        for curve in self.spectra:
            flags = ('Y' if curve.get('show', True) else '-') + ' / ' + ('Y' if curve.get('export', True) else '-')
            self.listbox.insert('end', f"[{flags}] {curve['label']}")
        if selected is not None and selected < len(self.spectra):
            self.listbox.selection_set(selected)

    def dimensions(self):
        width, height, dpi = (self.number(k) for k in ('width', 'height', 'dpi'))
        if width is None or height is None or dpi is None or not (1 <= width <= 40 and 1 <= height <= 40 and 72 <= dpi <= 1200):
            raise ValueError('Figure size must be 1–40 inches and DPI 72–1200.')
        if width * height * dpi * dpi > 100_000_000:
            raise ValueError('Export exceeds 100 million pixels. Reduce size or DPI.')
        return width, height, dpi

    def fit_preview(self, event=None):
        try:
            width, height, _ = self.dimensions()
        except ValueError:
            return
        available_w, available_h = self.preview.winfo_width(), self.preview.winfo_height()
        scale = min(available_w / width, available_h / height)
        self.canvas.get_tk_widget().place(relx=.5, rely=.5, anchor='center', width=max(1, int(width * scale)), height=max(1, int(height * scale)))

    def add_files(self):
        paths = filedialog.askopenfilenames(filetypes=[('Spectrum files', '*.csv *.txt *.dat'), ('All files', '*.*')])
        errors = []
        colors = ['#176b87', '#dc6546', '#4b9664', '#8a65b5', '#bd9532']
        for path in paths:
            try:
                x, y = read_spectrum(path)
                self.spectra.append(dict(x=x, y=y, label=Path(path).stem, color=colors[len(self.spectra) % len(colors)], show=True, export=True))
            except Exception as exc:
                errors.append(f'{Path(path).name}: {exc}')
        if len(self.spectra) == 1 and not self.variables['title'].get():
            self.variables['title'].set(self.spectra[0]['label'])
        self.refresh_list(len(self.spectra) - 1 if self.spectra else None)
        self.select()
        self.update()
        if errors:
            messagebox.showerror('Import errors', '\n'.join(errors))

    def remove(self):
        selected = self.listbox.curselection()
        if selected:
            del self.spectra[selected[0]]
            self.listbox.delete(selected[0])
            self.update()

    def edit_curve(self):
        selected = self.listbox.curselection()
        if not selected:
            return
        i = selected[0]
        curve = self.spectra[i]
        curve['label'] = self.variables['label'].get().strip() or curve['label']
        color = colorchooser.askcolor(curve['color'], title='Curve color')[1]
        if color:
            curve['color'] = color
        self.refresh_list(i)
        self.update()

    def number(self, key):
        value = self.variables[key].get().strip()
        if not value:
            return None
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Limits must be finite numbers.')
        return number

    def prepare(self, purpose='show'):
        limits = [self.number(k) for k in ('xmin', 'xmax', 'ymin', 'ymax')]
        for lo, hi in (limits[:2], limits[2:]):
            if lo is not None and hi is not None and lo >= hi:
                raise ValueError('Axis minimum must be below maximum.')
        mode = self.mode.get()
        low, high = (self.number('norm_low'), self.number('norm_high')) if mode == self.MODES[1] else (None, None)
        processed = []
        for curve in self.spectra:
            if not curve.get(purpose, True):
                continue
            try:
                values, peak = normalize(curve['x'], curve['y'], mode, low, high)
            except ValueError as exc:
                raise ValueError(f"{curve['label']}: {exc}") from exc
            processed.append((curve, values, peak))
        return limits, processed

    def update(self, purpose='show', target=None):
        try:
            self.dimensions()
            limits, processed = self.prepare(purpose)
            original = self.ax, self.figure
            if target is not None:
                self.figure = target
                self.ax = target.add_subplot(111)
            self.ax.clear()
            for curve, y, peak in processed:
                self.ax.plot(curve['x'], y, color=curve['color'], linewidth=1.8, label=curve['label'])
            self.ax.set_title(self.variables['title'].get(), fontsize=19, pad=20)
            self.ax.set_xlabel('Wavelength (nm)', fontsize=13, labelpad=10)
            self.ax.set_ylabel('Absorbance (a.u.)' if self.mode.get() == self.MODES[2] else 'Normalized absorbance (a.u.)', fontsize=13, labelpad=10)
            if self.grid.get():
                self.ax.grid(True, color='#d6d6d6', linewidth=1)
            else:
                self.ax.grid(False)
            self.ax.set_axisbelow(True)
            self.ax.tick_params(labelsize=11)
            self.ax.xaxis.set_minor_locator(AutoMinorLocator())
            for spine in self.ax.spines.values():
                spine.set_color('#b8b8b8')
            if processed:
                if self.legend.get():
                    self.ax.legend(frameon=False, fontsize=9)
                self.ax.margins(x=0, y=.08)
            self.ax.set_xlim(left=limits[0], right=limits[1])
            self.ax.set_ylim(bottom=limits[2], top=limits[3])
            self.figure.tight_layout(pad=2)
            if target is None:
                self.fit_preview()
                self.canvas.draw()
            details = '; '.join(f"{c['label']}: max = {p:.6g}" for c, y, p in processed if p is not None)
            self.status.set(f'{len(processed)} spectrum/spectra | {self.mode.get()} | {details}')
            return processed
        except Exception as exc:
            messagebox.showerror('Cannot plot', str(exc))
            return None
        finally:
            if target is not None and 'original' in locals():
                self.ax, self.figure = original

    def export_figure(self):
        try:
            width, height, dpi = self.dimensions()
        except ValueError as exc:
            messagebox.showerror('Export failed', str(exc))
            return
        figure = Figure(figsize=(width, height), dpi=100, facecolor='white')
        processed = self.update('export', figure)
        if not processed:
            if processed is not None:
                messagebox.showinfo('Export', 'Select at least one spectrum for export.')
            return
        path = filedialog.asksaveasfilename(defaultextension='.png', filetypes=[('PNG', '*.png'), ('PDF', '*.pdf'), ('SVG', '*.svg')])
        if path:
            try:
                figure.savefig(path, dpi=dpi, facecolor='white')
                self.status.set(f'Saved figure: {path}')
            except Exception as exc:
                messagebox.showerror('Export failed', str(exc))

    def export_data(self):
        try:
            _, processed = self.prepare('export')
        except ValueError as exc:
            messagebox.showerror('Export failed', str(exc))
            return
        if not processed:
            return
        path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if path:
            try:
                with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(['Spectrum', 'Wavelength (nm)', 'Raw absorbance', 'Plotted absorbance', 'Normalization divisor', 'Normalization mode'])
                    for curve, y, peak in processed:
                        writer.writerows((curve['label'], x, raw, value, peak if peak is not None else '', self.mode.get()) for x, raw, value in zip(curve['x'], curve['y'], y))
                self.status.set(f'Saved data: {path}')
            except Exception as exc:
                messagebox.showerror('Export failed', str(exc))


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
