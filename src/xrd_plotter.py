"""XRD stacked plotter. Run without arguments for GUI, or --input-dir DIR --output BASE."""
from pathlib import Path
import argparse
import sys
import csv
import json
import re
from app_version import __version__
import numpy as np
import pdfplumber
import matplotlib
from matplotlib.figure import Figure
from matplotlib.ticker import MultipleLocator
from card_formats import read_cif, read_xy, card_title, auto_formula_title
from card_cache import load_card


def palette_colors(colors, count):
    """Repeat a user-defined ordered color list across sample patterns."""
    from matplotlib.colors import to_hex
    if count < 1:
        return []
    if not colors:
        raise ValueError('Add at least one color to the custom palette')
    validated = [to_hex(color) for color in colors]
    return [validated[i % len(validated)] for i in range(count)]


def read_sample(path):
    """Read ragged refinement CSV: only theta, observation and background are required."""
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        header = [s.strip().lstrip('#').lower().replace(' ', '') for s in next(reader)]
        def column(names):
            for name in names:
                if name in header:
                    return header.index(name)
            raise ValueError(f'{Path(path).name}: missing column {names}')
        ix = column(['twotheta', '2theta', 'two_theta'])
        iy = column(['yobs', 'obs', 'observed', 'intensity'])
        ib = column(['bkg', 'background', 'bg'])
        rows = []
        for line, row in enumerate(reader, 2):
            if not row or not any(s.strip() for s in row):
                continue
            try:
                rows.append([float(row[i]) for i in (ix, iy, ib)])
            except (ValueError, IndexError) as e:
                raise ValueError(f'{Path(path).name}: invalid data on line {line}') from e
    a = np.asarray(rows, dtype=float)
    if a.ndim != 2 or len(a) < 2 or not np.isfinite(a).all():
        raise ValueError(f'{path}: need at least two finite data rows')
    a = a[np.argsort(a[:, 0], kind='stable')]
    corrected = a[:, 1] - a[:, 2]
    maximum = float(corrected.max())
    if maximum <= 0:
        raise ValueError(f'{path}: max(obs - background) must be positive')
    return dict(path=str(path), label=Path(path).stem, x=a[:, 0], obs=a[:, 1],
                background=a[:, 2], corrected=corrected, normalized=corrected / maximum,
                normalization_max=maximum)


def read_card(path, wavelength=1.54059, upper_angle=100):
    return load_card(path, wavelength, upper_angle, _parse_card)


def _parse_card(path, wavelength=1.54059, upper_angle=100):
    path = Path(path)
    if path.suffix.lower() == '.cif':
        return read_cif(path, wavelength, upper_angle)
    if path.suffix.lower() == '.xy':
        return read_xy(path)
    if path.suffix.lower() not in ('.csv', '.pdf'):
        raise ValueError('Supported card formats: PDF, CSV, CIF and XY')
    if path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        peaks = [[float(r['2theta']), float(r['intensity'])] for r in rows]
        return dict(path=str(path), label=auto_formula_title(path.stem), peaks=np.asarray(peaks), records=rows)
    records = {}
    texts = []
    # Each line may contain two independent seven-column records.
    pattern = re.compile(r'(?<![\d.])(?P<n>\d+)\s+(?P<t>\d+\.\d+)\s+(?P<d>\d+\.\d+)\s+(?P<i>\d+\.\d+)\s+(?P<h>-?\d+)\s+(?P<k>-?\d+)\s+(?P<l>-?\d+)(?![\d.])')
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            texts.append(text)
            in_table = False
            for line in text.splitlines():
                if 'No.' in line and '2Theta' in line and 'Intensity' in line:
                    in_table = True
                    continue
                if in_table and line.startswith('Note:'):
                    in_table = False
                if in_table:
                    for match in pattern.finditer(line):
                        r = match.groupdict()
                        n = int(r['n'])
                        record = dict(no=n, **{'2theta': float(r['t'])}, d=float(r['d']),
                                      intensity=float(r['i']), h=int(r['h']), k=int(r['k']), l=int(r['l']))
                        if n in records and records[n] != record:
                            raise ValueError(f'{path.name}: conflicting peak row {n}')
                        records[n] = record
    if not records or sorted(records) != list(range(1, max(records) + 1)):
        raise ValueError(f'{path.name}: cannot read complete peak table; use a CSV with 2theta,intensity columns')
    text = '\n'.join(texts)
    name = re.search(r'^Name:\s*(.*?)\s+I/Ic', text, re.M)
    formula = re.search(r'^Formula:\s*(.*)$', text, re.M)
    number = re.search(r'PDF Card No\.:\s*(\S+)', text)
    wavelength = re.search(r'calculated with wavelength\s*=\s*([\d.]+)', text)
    rows = [records[n] for n in sorted(records)]
    label = card_title(name.group(1) if name else path.stem,
                       formula.group(1) if formula else '', number.group(1) if number else '')
    return dict(path=str(path), label=label, records=rows,
                card_number=number.group(1) if number else '',
                wavelength=float(wavelength.group(1)) if wavelength else None,
                peaks=np.array([[r['2theta'], r['intensity']] for r in rows]))


def make_figure(samples, cards, xmin=10, xmax=90, title='', color='#0000dd', spacing=1.35, dpi=400, width_cm=34.29, height_cm=None, xlabel='2θ (°)', ylabel='', wavelength=1.54059, display_order=None):
    if not isinstance(dpi, (int, float)) or not np.isfinite(dpi) or dpi <= 0 or int(dpi) != dpi:
        raise ValueError('DPI must be a positive whole number')
    if not samples and not cards:
        fig = Figure(figsize=(width_cm / 2.54, height_cm / 2.54 if height_cm else 4.5), facecolor='white')
        fig.text(0.5, 0.5, 'No visible patterns', ha='center', va='center', color='#64748b', fontsize=14)
        return fig
    if xmax <= xmin or spacing < 1.05:
        raise ValueError('Require xmax > xmin and spacing >= 1.05')
    matplotlib.rcParams.update({'font.family': 'sans-serif', 'font.sans-serif': ['DejaVu Sans', 'Arial'],
                               'font.size': 12, 'svg.fonttype': 'none', 'pdf.fonttype': 42})
    total = len(samples) + len(cards)
    if not np.isfinite(width_cm) or width_cm <= 0:
        raise ValueError('Image width must be positive (cm)')
    if height_cm is not None and (not np.isfinite(height_cm) or height_cm <= 0):
        raise ValueError('Image height must be positive (cm), or leave it blank for automatic height')
    height_inches = height_cm / 2.54 if height_cm is not None else max(4.5, total * 1.12)
    fig = Figure(figsize=(width_cm / 2.54, height_inches), facecolor='white')
    left = 0.08 if ylabel else 0.055
    ax = fig.add_axes([left, 0.14, 0.98 - left, 0.81])
    top_to_bottom = samples + cards
    if display_order is not None:
        ranks = {identifier: index for index, identifier in enumerate(display_order)}
        top_to_bottom = sorted(top_to_bottom, key=lambda row: ranks.get(row.get('order_id'), len(ranks)))
    rows = list(reversed(top_to_bottom))
    bottoms = []
    for i, row in enumerate(rows):
        base = i * spacing
        if 'normalized' in row:
            mask = (row['x'] >= xmin) & (row['x'] <= xmax)
            if not mask.any():
                raise ValueError(f"{row['label']}: no data in selected range")
            ax.plot(row['x'][mask], row['normalized'][mask] + base, color=row.get('color') or color, lw=0.85)
            bottoms.append(base + min(0, row['normalized'][mask].min()))
        else:
            peaks = row['peaks']
            if len(peaks) == 0 or not np.isfinite(peaks).all() or peaks[:, 1].max() <= 0 or (row.get('kind') != 'profile' and (peaks[:, 1] < 0).any()):
                raise ValueError(f"{row['label']}: invalid card peaks")
            mask = (peaks[:, 0] >= xmin) & (peaks[:, 0] <= xmax)
            # Coincident lines remain separate, preserving the supplied table intensities.
            ax.hlines(base, xmin, xmax, color='#777777', lw=0.45)
            if row.get('kind') == 'profile':
                ax.plot(peaks[mask, 0], base + peaks[mask, 1] / peaks[:, 1].max(), color='black', lw=0.85)
                bottoms.append(base + min(0, peaks[mask, 1].min() / peaks[:, 1].max()) if mask.any() else base)
            else:
                ax.vlines(peaks[mask, 0], base, base + peaks[mask, 1] / peaks[:, 1].max(), color='black', lw=0.85)
                bottoms.append(base)
        label_style = row.get('label_style', {})
        ax.text(xmin + (xmax - xmin) * label_style.get('x_percent', 99.2) / 100,
                base + label_style.get('y_offset', 1.08),
                auto_formula_title(row['label']) if 'normalized' not in row else row['label'],
                ha=label_style.get('alignment', 'right'), va='bottom',
                fontsize=label_style.get('font_size', 11),
                bbox=dict(facecolor='white', edgecolor='none', pad=0.8))
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(min(bottoms) - 0.06, (total - 1) * spacing + 1.45)
    ax.set_xlabel(xlabel, fontsize=14)
    ax.set_ylabel(ylabel, fontsize=14)
    ax.set_yticks([])
    ax.xaxis.set_major_locator(MultipleLocator(5))
    ax.xaxis.set_minor_locator(MultipleLocator(1))
    ax.tick_params(axis='x', which='major', direction='out', length=7, width=1)
    ax.tick_params(axis='x', which='minor', direction='out', length=4, width=0.8)
    for spine in ax.spines.values():
        spine.set_linewidth(1)
    if title:
        fig.suptitle(title, fontsize=14, y=0.99)
    return fig


def export(fig, base, samples, cards, settings):
    base = Path(base)
    base.parent.mkdir(parents=True, exist_ok=True)
    for ext in ('png', 'pdf', 'svg'):
        fig.savefig(str(base) + '.' + ext, dpi=settings.get('dpi', 400))
    export_data(base.parent / (base.name + '_data'), samples, cards, settings)


def export_data(data_dir, samples, cards, settings):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(samples, 1):
        np.savetxt(data_dir / f'sample_{i:02d}_processed.csv',
                   np.column_stack([s[k] for k in ['x', 'obs', 'background', 'corrected', 'normalized']]),
                   delimiter=',', header='2theta,obs,background,obs_minus_background,normalized', comments='')
    for i, card in enumerate(cards, 1):
        with (data_dir / f'card_{i:02d}_peaks.csv').open('w', newline='', encoding='utf-8-sig') as f:
            fields = list(card['records'][0])
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(card['records'])
    metadata = dict(settings=settings, formula='(obs - background) / max(obs - background)',
                    normalization_scope='entire scan, before display range filtering', negative_values='preserved',
                    samples=[{k: s[k] for k in ['path', 'label', 'normalization_max', 'color', 'label_style'] if k in s} for s in samples],
                    cards=[{k: v for k, v in c.items() if k not in ['peaks', 'records']} for c in cards])
    (data_dir / 'processing.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')


def gui(initial_dir, root=None):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser
    from tkinter import font as tkfont
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    owns_root = root is None
    root = tk.Tk() if owns_root else root
    for child in root.winfo_children():
        child.destroy()
    icon_base = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
    icon_path = icon_base / 'assets' / 'xrd-plotter-icon.png'
    if icon_path.is_file():
        from PIL import Image, ImageTk
        root._app_icon = ImageTk.PhotoImage(Image.open(icon_path).resize((128, 128)))
        root.iconphoto(True, root._app_icon)
    root.title(f'XRD Plotter {__version__} - ' + ('Mac' if sys.platform == 'darwin' else 'Win'))
    root.geometry('1380x900')
    root.configure(background='#f3f5f9')
    ui_font = tkfont.nametofont('TkDefaultFont').actual('family')
    native_font_size = abs(int(tkfont.nametofont('TkDefaultFont').actual('size')))
    base_ui_size = max(13, native_font_size) if sys.platform == 'darwin' else max(10, native_font_size)
    theme_choice = tk.StringVar(value='Light')
    scale_choice = tk.StringVar(value='100%')
    if sys.platform == 'darwin':
        try:
            import subprocess
            appearance = subprocess.run(['/usr/bin/defaults', 'read', '-g', 'AppleInterfaceStyle'],
                                        capture_output=True, text=True, timeout=2)
            if appearance.returncode == 0 and 'dark' in appearance.stdout.lower():
                theme_choice.set('Dark')
        except (OSError, subprocess.TimeoutExpired):
            pass
    theme_colors = {}
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    def apply_ui_appearance(event=None):
        dark = theme_choice.get() == 'Dark'
        colors = dict(bg='#182130', field='#202c3e', text='#e3eaf5', muted='#9eabc0',
                      button='#29374d', hover='#354763', border='#42536a', selected='#2b426b') if dark else dict(
                      bg='#ffffff', field='#ffffff', text='#24324a', muted='#748197',
                      button='#f2f5fa', hover='#e4ebf8', border='#e1e7ef', selected='#e7edff')
        previous = dict(theme_colors)
        theme_colors.update(colors)
        factor = int(scale_choice.get().rstrip('%')) / 100
        size = round(base_ui_size * factor)
        root.configure(background=colors['bg'])
        style.configure('.', font=(ui_font, size), background=colors['bg'], foreground=colors['text'])
        style.configure('TFrame', background=colors['bg'])
        style.configure('TLabel', background=colors['bg'], foreground=colors['text'])
        style.configure('TButton', background=colors['button'], foreground=colors['text'], padding=(round(9*factor), round(6*factor)))
        style.map('TButton', background=[('active', colors['hover'])], foreground=[('disabled',colors['muted'])])
        style.configure('InactiveTab.TButton', background=colors['button'], foreground=colors['text'], padding=(round(10*factor),round(9*factor)))
        style.configure('Accent.TButton', background='#345ee9', foreground='white', padding=(round(10*factor),round(9*factor)))
        style.map('Accent.TButton', background=[('active','#244ac8')], foreground=[('!disabled','white')])
        style.configure('Section.TLabel', font=(ui_font,size+1,'bold'))
        style.configure('Muted.TLabel', foreground=colors['muted'])
        style.configure('Title.TLabel', font=(ui_font,round(19*factor),'bold'))
        style.configure('TEntry', fieldbackground=colors['field'], foreground=colors['text'], insertcolor=colors['text'])
        style.configure('TCombobox', fieldbackground=colors['field'], background=colors['button'], foreground=colors['text'], arrowcolor=colors['text'])
        style.map('TCombobox', fieldbackground=[('readonly',colors['field'])], foreground=[('readonly',colors['text'])], selectbackground=[('readonly',colors['field'])], selectforeground=[('readonly',colors['text'])])
        style.configure('TNotebook', background=colors['bg'], borderwidth=0, lightcolor=colors['bg'],darkcolor=colors['bg'],bordercolor=colors['bg'])
        style.configure('Treeview',borderwidth=0,relief='flat')
        style.configure('Treeview.Heading',borderwidth=0,relief='flat',padding=(6,7))
        style.configure('Treeview', background=colors['field'], fieldbackground=colors['field'], foreground=colors['text'], rowheight=round(27*factor), font=(ui_font,size))
        style.configure('Treeview.Heading', background=colors['button'], foreground=colors['text'], font=(ui_font,size))
        style.map('Treeview', background=[('selected',colors['selected'])], foreground=[('selected',colors['text'])])
        style.configure('Vertical.TScrollbar', background=colors['button'], troughcolor=colors['bg'], arrowcolor=colors['text'])
        root.option_add('*TCombobox*Listbox.background', colors['field'])
        root.option_add('*TCombobox*Listbox.foreground', colors['text'])
        root.option_add('*TCombobox*Listbox.selectBackground', colors['selected'])
        for widget in descendants(root):
            if isinstance(widget, tk.Listbox):
                widget.configure(background=colors['field'], foreground=colors['text'], selectbackground=colors['selected'],
                                 selectforeground=colors['text'], highlightbackground=colors['border'], font=(ui_font,size))
            elif isinstance(widget, (tk.Canvas, tk.Frame, tk.Label)):
                old = str(widget.cget('background'))
                selected = old in ('#e7edff','#2b426b')
                widget.configure(background=colors['selected'] if selected else colors['bg'])
                if isinstance(widget, tk.Canvas):
                    widget.configure(highlightbackground=colors['border'])
                    if hasattr(widget,'redraw'):
                        widget.redraw()
                    if hasattr(widget,'artwork'):
                        widget.artwork.clear()
                        widget.paint()
                if isinstance(widget, tk.Label):
                    fg=str(widget.cget('foreground'))
                    if fg in ('#24324a','#e3eaf5'):
                        widget.configure(foreground=colors['text'])
                    widget.configure(font=(ui_font,size))
        split_panes.configure(background=colors['border'])

    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=(ui_font, 10), background='#ffffff', foreground='#24324a')
    style.configure('TButton', padding=(9, 6), background='#f2f5fa', borderwidth=0)
    style.map('TButton', background=[('active', '#e4ebf8')])
    style.configure('Accent.TButton', foreground='white', background='#345ee9', padding=(10, 9))
    style.map('Accent.TButton', background=[('active', '#244ac8')])
    style.configure('TNotebook', background='#ffffff', borderwidth=0)
    style.configure('TNotebook.Tab', padding=(20, 10), background='#eef2f8', width=9)
    style.map('TNotebook.Tab', expand=[('selected', (0, 0, 0, 0))])
    style.map('TNotebook.Tab', background=[('selected', '#ffffff')], foreground=[('selected', '#345ee9')])
    style.configure('Section.TLabel', font=(ui_font, 11, 'bold'))
    style.configure('Muted.TLabel', foreground='#748197')
    style.configure('TEntry', padding=6)
    class SlimScrollbar(tk.Canvas):
        """Arrow-free scrollbar with a rounded thumb and mouse dragging."""
        def __init__(self,parent,orient='vertical',command=None,**kwargs):
            super().__init__(parent,width=12,height=1,highlightthickness=0,borderwidth=0,
                             background=theme_colors.get('bg','white'),cursor='arrow')
            self.command=command
            self.first,self.last=0.0,1.0
            self.hover=False
            self.drag_offset=None
            self.bind('<Configure>',lambda event:self.redraw())
            self.bind('<Enter>',lambda event:self.set_hover(True))
            self.bind('<Leave>',lambda event:self.set_hover(False))
            self.bind('<Button-1>',self.press)
            self.bind('<B1-Motion>',self.drag)
            self.bind('<ButtonRelease-1>',lambda event:setattr(self,'drag_offset',None))
        def set(self,first,last):
            self.first,self.last=float(first),float(last)
            self.redraw()
        def set_hover(self,value):
            self.hover=value
            self.redraw()
        def geometry_values(self):
            track=max(1,self.winfo_height()-10)
            thumb=min(track,max(26,track*(self.last-self.first)))
            travel=max(1,track-thumb)
            fraction=self.first/max(1e-9,1-(self.last-self.first))
            top=5+travel*fraction
            return top,thumb,travel
        def redraw(self):
            self.delete('all')
            if self.last-self.first>=0.999:
                return
            top,thumb,travel=self.geometry_values()
            dark=theme_choice.get()=='Dark'
            color=('#73839a' if self.hover else '#46566f') if dark else ('#8d9cb1' if self.hover else '#c6d0de')
            center=self.winfo_width()/2
            self.create_line(center,top+4,center,top+thumb-4,width=7 if self.hover else 5,
                             fill=color,capstyle='round')
        def press(self,event):
            top,thumb,travel=self.geometry_values()
            self.drag_offset=event.y-top if top<=event.y<=top+thumb else thumb/2
            self.drag(event)
        def drag(self,event):
            if self.drag_offset is None or self.command is None:
                return
            top,thumb,travel=self.geometry_values()
            fraction=max(0,min(1,(event.y-5-self.drag_offset)/travel))
            self.command('moveto',fraction*max(0,1-(self.last-self.first)))
    header = ttk.Frame(root, padding=(22, 16))
    header.pack(side='top', fill='x')
    ttk.Label(header, text='XRD Plotter', style='Title.TLabel').pack(side='left')
    ttk.Label(header, text='  /  Pattern workspace', style='Muted.TLabel').pack(side='left', padx=10)
    root.minsize(720, 400)
    split_panes = tk.PanedWindow(root, orient='horizontal', sashwidth=6,
                                sashrelief='flat', sashcursor='sb_h_double_arrow',
                                opaqueresize=False, proxyrelief='solid', proxyborderwidth=1, borderwidth=0, background='#e3e8f0')
    split_panes.pack(fill='both', expand=True)
    def restore_split_cursor(event=None):
        if split_panes.winfo_exists():
            split_panes.configure(cursor='arrow')
    split_panes.bind('<Leave>', restore_split_cursor)
    split_panes.bind('<ButtonRelease-1>', lambda event: split_panes.after_idle(restore_split_cursor))

    controls = ttk.Frame(split_panes)
    split_panes.add(controls, minsize=320, width=470, stretch='never')
    footer = ttk.Frame(controls, padding=(14, 10))
    footer.pack(side='bottom', fill='x')
    control_canvas = tk.Canvas(controls, highlightthickness=0, width=340, background=theme_colors.get('bg','white'))
    control_scrollbar = SlimScrollbar(controls, orient='vertical', command=control_canvas.yview)
    control_scrollbar.pack(side='right', fill='y')
    control_canvas.pack(side='left', fill='both', expand=True)
    control_canvas.configure(yscrollcommand=control_scrollbar.set)
    panel = ttk.Frame(control_canvas, padding=12)
    ttk.Label(panel, text='WORKSPACE', style='Muted.TLabel').pack(anchor='w', pady=(0, 10))
    tab_bar = ttk.Frame(panel)
    tab_bar.pack(fill='x', pady=(0, 10))
    style.layout('Pages.TNotebook.Tab', [])
    tabs = ttk.Notebook(panel, style='Pages.TNotebook')
    tabs.pack(fill='both', expand=True)
    data_page = ttk.Frame(tabs, padding=(10, 12))
    layout_page = ttk.Frame(tabs, padding=(12, 12))
    settings_page = ttk.Frame(tabs, padding=(12, 12))
    tabs.add(data_page, text='Data')
    tabs.add(layout_page, text='Layout')
    tabs.add(settings_page, text='Settings')
    tab_buttons = []
    def select_tab(index):
        tabs.select(index)
        for i, button in enumerate(tab_buttons):
            button.configure(style='Accent.TButton' if i == index else 'InactiveTab.TButton')
    for index, caption in enumerate(('Data', 'Layout', 'Settings')):
        button = ttk.Button(tab_bar, text=caption, command=lambda i=index: select_tab(i))
        button.grid(row=0, column=index, sticky='nsew', padx=2)
        tab_bar.columnconfigure(index, weight=1, uniform='workspace_tabs')
        tab_buttons.append(button)
    # Equal padding prevents the selected button from changing dimensions.
    style.configure('Tab.TButton', padding=(10, 9))
    style.configure('InactiveTab.TButton', padding=(10, 9), background='#eef2f8')
    def sync_tabs(event=None):
        index = tabs.index(tabs.select())
        for i, button in enumerate(tab_buttons):
            button.configure(style='Accent.TButton' if i == index else 'InactiveTab.TButton')
    tabs.bind('<<NotebookTabChanged>>', sync_tabs)
    select_tab(0)
    sync_tabs()

    ttk.Label(settings_page, text='Appearance', style='Section.TLabel').pack(anchor='w', pady=(0, 8))
    appearance_controls = ttk.Frame(settings_page)
    appearance_controls.pack(fill='x')
    appearance_controls.columnconfigure(1, weight=1)
    ttk.Label(appearance_controls, text='Theme').grid(row=0, column=0, sticky='w', padx=(0, 12), pady=5)
    theme_picker = ttk.Combobox(appearance_controls, textvariable=theme_choice,
                               values=('Light', 'Dark'), state='readonly', width=12)
    theme_picker.grid(row=0, column=1, sticky='ew', pady=5)
    theme_picker.bind('<<ComboboxSelected>>', apply_ui_appearance)
    ttk.Label(appearance_controls, text='UI scale').grid(row=1, column=0, sticky='w', padx=(0, 12), pady=5)
    scale_picker = ttk.Combobox(appearance_controls, textvariable=scale_choice,
                               values=('100%', '110%', '125%', '150%'), state='readonly', width=12)
    scale_picker.grid(row=1, column=1, sticky='ew', pady=5)
    scale_picker.bind('<<ComboboxSelected>>', apply_ui_appearance)
    ttk.Separator(settings_page).pack(fill='x', pady=(18, 12))
    ttk.Label(settings_page, text='Updates', style='Section.TLabel').pack(anchor='w', pady=(0, 6))

    panel_window = control_canvas.create_window((0, 0), window=panel, anchor='nw')
    def update_control_region(event=None):
        control_canvas.configure(scrollregion=control_canvas.bbox('all'))
    panel.bind('<Configure>', update_control_region)
    control_canvas.bind('<Configure>', lambda event: control_canvas.itemconfigure(panel_window, width=event.width))
    def scroll_controls(event):
        px, py = root.winfo_pointerxy()
        left, top = control_canvas.winfo_rootx(), control_canvas.winfo_rooty()
        if not (left <= px < left + control_canvas.winfo_width() and
                top <= py < top + control_canvas.winfo_height()):
            return
        if getattr(event, 'num', None) in (4, 5):
            steps = -1 if event.num == 4 else 1
        elif event.delta:
            steps = -int(event.delta / 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
        else:
            return
        control_canvas.yview_scroll(steps, 'units')
        return 'break'
    root.bind('<MouseWheel>', scroll_controls)
    root.bind('<Button-4>', scroll_controls)
    root.bind('<Button-5>', scroll_controls)
    preview = ttk.Frame(split_panes)
    split_panes.add(preview, minsize=300, stretch='always')
    class VisibilityTickBox(tk.Canvas):
        """Custom keyboard-accessible tick box with antialiased artwork."""
        def __init__(self, parent, variable, command):
            super().__init__(parent, width=26, height=24, highlightthickness=0,
                             background=theme_colors.get('bg','white'), cursor='hand2', takefocus=True)
            self.variable, self.command = variable, command
            self.artwork = {}
            self.bind('<Button-1>', lambda e: self.invoke())
            self.bind('<space>', lambda e: (self.invoke(), 'break')[1])
            self.bind('<Return>', lambda e: (self.invoke(), 'break')[1])
            self.bind('<FocusIn>', lambda e: self.paint())
            self.bind('<FocusOut>', lambda e: self.paint())
            self.paint()
        def paint(self):
            from PIL import Image, ImageDraw, ImageTk
            enabled = self.variable.get()
            if enabled not in self.artwork:
                scale=4
                image=Image.new('RGBA',(26*scale,24*scale))
                drawing=ImageDraw.Draw(image)
                drawing.rounded_rectangle((5*scale,5*scale,21*scale,21*scale),radius=3*scale,
                                          fill='#345ee9' if enabled else theme_colors.get('field','#ffffff'),
                                          outline='#345ee9' if enabled else '#b8c3d2',width=1*scale)
                if enabled:
                    drawing.line([(8*scale,13*scale),(11*scale,16*scale),(18*scale,10*scale)],
                                 fill='white',width=2*scale,joint='curve')
                image=image.resize((26,24),Image.Resampling.LANCZOS)
                self.artwork[enabled]=ImageTk.PhotoImage(image, master=self)
            self.delete('all')
            self.create_image(0,0,anchor='nw',image=self.artwork[enabled])
            if self.focus_get()==self:
                self.create_rectangle(1,1,25,23,outline='#7395f8',dash=(2,2))
        def invoke(self):
            self.variable.set(not self.variable.get())
            self.paint()
            self.command()
    class CheckList(ttk.Frame):
        """Custom tick boxes with independent row selection for editing."""
        def __init__(self, parent, on_toggle):
            super().__init__(parent)
            self.on_toggle = on_toggle
            self.rows = []
            self.selected = ()
            self.canvas = tk.Canvas(self, height=122, background=theme_colors.get('bg','white'), highlightthickness=0, highlightbackground='#e1e7ef')
            scroll = SlimScrollbar(self, orient='vertical', command=self.canvas.yview)
            scroll.pack(side='right', fill='y')
            self.canvas.pack(side='left', fill='both', expand=True)
            self.canvas.configure(yscrollcommand=scroll.set)
            self.body = ttk.Frame(self.canvas)
            window = self.canvas.create_window(0, 0, anchor='nw', window=self.body)
            self.body.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
            self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(window, width=e.width))
        def delete(self, first, last=None):
            for row in self.rows:
                row['frame'].destroy()
            self.rows.clear()
            self.selected = ()
        def insert(self, index, text):
            i = len(self.rows)
            frame = tk.Frame(self.body, background=theme_colors.get('bg','white'))
            frame.pack(fill='x', pady=2)
            value = tk.BooleanVar(value=True)
            def toggle():
                self.selection_set(i)
                self.on_toggle()
            check = VisibilityTickBox(frame, variable=value, command=toggle)
            check.pack(side='left', padx=(8, 9), pady=5)
            label = tk.Label(frame, text=text, anchor='w', background=theme_colors.get('bg','white'), foreground='#24324a', font=(ui_font,round(base_ui_size * int(scale_choice.get().rstrip('%'))/100)))
            label.pack(side='left', fill='x', expand=True, padx=(0,6), pady=4)
            label.bind('<Button-1>', lambda e: (self.focus_set(), self.selection_set(i)))
            frame.bind('<Button-1>', lambda e: (self.focus_set(), self.selection_set(i)))
            self.rows.append(dict(frame=frame, label=label, check=check, value=value, text=text))
        def itemconfigure(self, index, **options):
            row=self.rows[-1 if index == 'end' else index]
            if 'foreground' in options:
                row['label'].configure(foreground=options['foreground'])
        def set_checked(self, index, checked):
            row = self.rows[-1 if index == 'end' else index]
            row['value'].set(checked)
            row['check'].paint()
        def curselection(self):
            return self.selected
        def selection_set(self, index):
            self.selected=(int(index),)
            for i,row in enumerate(self.rows):
                background=theme_colors.get('selected','#e7edff') if i==index else theme_colors.get('bg','white')
                row['frame'].configure(background=background)
                row['label'].configure(background=background)
                row['check'].configure(background=background)
        def selection_clear(self, first, last=None):
            self.selected=()
            for row in self.rows:
                row['frame'].configure(background=theme_colors.get('bg','white'))
                row['label'].configure(background=theme_colors.get('bg','white'))
                row['check'].configure(background=theme_colors.get('bg','white'))
        def size(self):
            return len(self.rows)
        def get(self,index):
            return self.rows[index]['text']
    groups = {'samples': [], 'cards': []}
    global_order = []
    order_ready = [False]
    boxes = {}
    rendered = {}
    palette_ready = [False]
    def refresh_global_order(group_key=None):
        import uuid
        by_id = {}
        for kind, items in groups.items():
            for path, label, color, label_style in items:
                identifier = label_style.setdefault('_order_id', uuid.uuid4().hex)
                by_id[identifier] = (kind, label, label_style.get('_visible', True))
        global_order[:] = [identifier for identifier in global_order if identifier in by_id]
        global_order.extend(identifier for identifier in by_id if identifier not in global_order)
        if group_key is not None:
            ordered = [item[3]['_order_id'] for item in groups[group_key]]
            slots = [i for i, identifier in enumerate(global_order) if by_id[identifier][0] == group_key]
            for i, identifier in zip(slots, ordered):
                global_order[i] = identifier
        if not order_ready[0]:
            return
        selected = order_tree.selection()
        order_tree.delete(*order_tree.get_children())
        for i, identifier in enumerate(global_order, 1):
            kind, label, visible = by_id[identifier]
            order_tree.insert('', 'end', iid=identifier,
                              values=('Pattern' if kind == 'samples' else 'Card', f'≡  {i}. {label}', 'On' if visible else 'Off'))
        if selected and selected[0] in by_id:
            order_tree.selection_set(selected[0])
    def move_global(direction):
        chosen = order_tree.selection()
        if not chosen:
            return
        i = global_order.index(chosen[0]); j = i + direction
        if not 0 <= j < len(global_order):
            return
        global_order[i], global_order[j] = global_order[j], global_order[i]
        rank = {identifier: index for index, identifier in enumerate(global_order)}
        for kind in groups:
            groups[kind].sort(key=lambda item: rank[item[3]['_order_id']])
            refresh(kind)
        order_tree.selection_set(chosen[0])
        order_tree.see(chosen[0])
        draw()
    drag_order = [None]
    def begin_order_drag(event):
        identifier=order_tree.identify_row(event.y)
        if not identifier:
            return
        drag_order[0]=identifier
        order_tree.selection_set(identifier)
        order_tree.configure(cursor='fleur')
    def move_order_drag(event):
        identifier=drag_order[0]
        if not identifier:
            return
        target=order_tree.identify_row(event.y)
        if target and target!=identifier:
            order_tree.move(identifier,'',order_tree.index(target))
        if event.y<30:
            order_tree.yview_scroll(-1,'units')
        elif event.y>order_tree.winfo_height()-20:
            order_tree.yview_scroll(1,'units')
    def finish_order_drag(event=None):
        identifier=drag_order[0]
        drag_order[0]=None
        order_tree.configure(cursor='arrow')
        if not identifier:
            return
        updated=list(order_tree.get_children())
        if updated==global_order:
            return
        global_order[:]=updated
        rank={identifier:index for index,identifier in enumerate(global_order)}
        for kind in groups:
            groups[kind].sort(key=lambda item:rank[item[3]['_order_id']])
            refresh(kind)
        order_tree.selection_set(identifier)
        order_tree.see(identifier)
        draw()
    def reset_global_order():
        global_order[:] = [item[3]['_order_id'] for kind in ('samples','cards') for item in groups[kind]]
        refresh_global_order()
        draw()
    def refresh(key):
        boxes[key].delete(0, 'end')
        for p, label, override_color, label_style in groups[key]:
            visible = label_style.get('_visible', True)
            boxes[key].insert('end', label)
            boxes[key].set_checked('end', visible)
            boxes[key].itemconfigure('end', foreground=(override_color or theme_colors.get('text','#24324a')) if visible else theme_colors.get('muted','#a1aaba'))
        refresh_global_order(key)
        if key == 'samples' and palette_ready[0]:
            update_palette_preview()
    def toggle_visibility(key, mode=None):
        selected = boxes[key].curselection()
        if mode is None and not selected:
            return
        indices = range(len(groups[key])) if mode is not None else selected
        for i in indices:
            path, label, color, original_style = groups[key][i]
            updated = dict(original_style)
            updated['_visible'] = bool(mode) if mode is not None else not updated.get('_visible', True)
            groups[key][i] = (path, label, color, updated)
        refresh(key)
        for i in selected:
            boxes[key].selection_set(i)
        draw()
    def add(key):
        types = [('XRD CSV', '*.csv')] if key == 'samples' else [('Reference card files', '*.pdf *.csv *.cif *.xy')]
        paths = filedialog.askopenfilenames(initialdir=initial_dir, filetypes=types)
        for path in paths:
            try:
                label = read_card(path)['label'] if key == 'cards' else Path(path).stem
                groups[key].append((path, label, None, {}))
            except Exception as e:
                messagebox.showerror('Add file', str(e))
        refresh(key)
    def modify(key, action):
        chosen = boxes[key].curselection()
        if not chosen:
            return
        i = chosen[0]
        if action == 'delete':
            groups[key].pop(i)
        elif action == 'rename':
            label = simpledialog.askstring('Label', 'Display label:', initialvalue=groups[key][i][1])
            if label:
                groups[key][i] = (groups[key][i][0], label, groups[key][i][2], groups[key][i][3])
        else:
            j = i + action
            if 0 <= j < len(groups[key]):
                groups[key][i], groups[key][j] = groups[key][j], groups[key][i]
                i = j
        refresh(key)
        if groups[key]:
            boxes[key].selection_set(min(i, len(groups[key]) - 1))
    def set_selected_color(reset=False):
        selected = boxes['samples'].curselection()
        if not selected:
            messagebox.showinfo('Select a pattern', 'Select a sample XRD pattern first.')
            return
        i = selected[0]
        path, label, override_color, label_style = groups['samples'][i]
        if reset:
            chosen = None
        else:
            try:
                from matplotlib.colors import to_hex
                initial = to_hex(override_color or variables['color'].get())
                chosen = colorchooser.askcolor(color=initial, title=f'Color for {label}', parent=root)[1]
            except Exception as e:
                messagebox.showerror('Color', str(e))
                return
            if chosen is None:
                return
        groups['samples'][i] = (path, label, chosen, label_style)
        refresh('samples')
        boxes['samples'].selection_set(i)
        draw()
    def apply_color_to_all():
        try:
            from matplotlib.colors import to_rgba
            to_rgba(variables['color'].get())
        except ValueError as e:
            messagebox.showerror('Color', str(e))
            return
        groups['samples'] = [(path, label, None, style) for path, label, override, style in groups['samples']]
        refresh('samples')
        draw()
    custom_palette = ['#0000dd']
    def update_palette_preview(event=None):
        selected = palette_list.curselection()
        selected_index = selected[0] if selected else 0
        palette_list.delete(0, 'end')
        for i, color in enumerate(custom_palette):
            palette_list.insert('end', f'{i + 1}. {color}')
            palette_list.itemconfigure('end', foreground=color)
        if custom_palette:
            palette_list.selection_set(min(selected_index, len(custom_palette) - 1))
        palette_preview.delete('all')
        width = max(1, palette_preview.winfo_width())
        swatch_width = width / max(1, len(custom_palette))
        for i, color in enumerate(custom_palette):
            palette_preview.create_rectangle(i * swatch_width, 1, (i + 1) * swatch_width, 27,
                                             fill=color, outline=theme_colors.get('bg','white'))
    def modify_palette(action):
        chosen = palette_list.curselection()
        index = chosen[0] if chosen else None
        if action in ('add', 'edit'):
            if action == 'edit' and index is None:
                messagebox.showinfo('Select a color', 'Select a palette color to edit.')
                return
            from matplotlib.colors import to_hex
            try:
                initial = custom_palette[index] if action == 'edit' else to_hex(variables['color'].get())
                color = colorchooser.askcolor(color=initial, title='Choose custom palette color', parent=root)[1]
            except Exception as e:
                messagebox.showerror('Color', str(e))
                return
            if color is None:
                return
            if action == 'add':
                custom_palette.append(color)
                index = len(custom_palette) - 1
            else:
                custom_palette[index] = color
        elif index is not None:
            if action == 'remove':
                custom_palette.pop(index)
                index = min(index, len(custom_palette) - 1)
            else:
                other = index + (-1 if action == 'up' else 1)
                if 0 <= other < len(custom_palette):
                    custom_palette[index], custom_palette[other] = custom_palette[other], custom_palette[index]
                    index = other
        update_palette_preview()
        if index is not None and index >= 0 and custom_palette:
            palette_list.selection_clear(0, 'end')
            palette_list.selection_set(index)
    def click_palette(event):
        if not custom_palette:
            modify_palette('add')
            return
        index = min(len(custom_palette) - 1, max(0, int(event.x / max(1, palette_preview.winfo_width()) * len(custom_palette))))
        palette_list.selection_clear(0, 'end')
        palette_list.selection_set(index)
        modify_palette('edit')
    def apply_palette():
        if not groups['samples']:
            messagebox.showinfo('Select patterns', 'Add at least one sample XRD pattern first.')
            return
        try:
            colors = palette_colors(custom_palette, len(groups['samples']))
        except ValueError as e:
            messagebox.showerror('Custom palette', str(e))
            return
        groups['samples'] = [(path, label, color, style) for (path, label, override, style), color in zip(groups['samples'], colors)]
        refresh('samples')
        draw()
    def edit_label_settings(key):
        selected = boxes[key].curselection()
        if not selected:
            messagebox.showinfo('Select a label', 'Select a sample or reference card first.')
            return
        index = selected[0]
        path, label, color, current = groups[key][index]
        dialog = tk.Toplevel(root)
        dialog.title('Label Settings')
        dialog.transient(root)
        dialog.grab_set()
        dialog.configure(background=theme_colors.get('bg','white'))
        body = ttk.Frame(dialog, padding=16)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=label, wraplength=350).pack(anchor='w', pady=(0, 10))
        defaults = {'font_size': 11, 'x_percent': 99.2, 'y_offset': 1.08, 'alignment': 'right'}
        fields = {}
        for field, caption in [('font_size', 'Font size (pt)'), ('x_percent', 'X position (% of angle range)'),
                               ('y_offset', 'Y offset above pattern baseline'), ('alignment', 'Horizontal alignment')]:
            ttk.Label(body, text=caption).pack(anchor='w')
            fields[field] = tk.StringVar(value=str(current.get(field, defaults[field])))
            if field == 'alignment':
                ttk.Combobox(body, textvariable=fields[field], values=('left', 'center', 'right'), state='readonly').pack(fill='x', pady=(0, 6))
            else:
                ttk.Entry(body, textvariable=fields[field]).pack(fill='x', pady=(0, 6))
        ttk.Label(body, text='X: 0 = left edge, 100 = right edge.\nY: normalized intensity units; 1 = peak height.\nUse Preview / Update to check placement.', wraplength=350).pack(pady=8)
        def apply(reset=False):
            try:
                style = {} if reset else {k: (v.get() if k == 'alignment' else float(v.get())) for k, v in fields.items()}
                if style and (not all(np.isfinite(style[k]) for k in ('font_size', 'x_percent', 'y_offset'))
                              or not 1 <= style['font_size'] <= 200 or not 0 <= style['x_percent'] <= 100):
                    raise ValueError('Font size must be 1–200 pt, X must be 0–100%, and Y must be finite.')
                style['_visible'] = current.get('_visible', True)
                if '_order_id' in current:
                    style['_order_id'] = current['_order_id']
                groups[key][index] = (path, label, color, style)
                dialog.destroy()
                draw()
            except Exception as e:
                messagebox.showerror('Label Settings', str(e), parent=dialog)
        actions = ttk.Frame(body)
        actions.pack(fill='x', pady=5)
        ttk.Button(actions, text='Apply', command=apply).pack(side='left')
        ttk.Button(actions, text='Reset Label', command=lambda: apply(True)).pack(side='left', padx=5)
        ttk.Button(actions, text='Cancel', command=dialog.destroy).pack(side='left')
    for key, label in [('samples', 'Sample patterns'), ('cards', 'Reference cards')]:
        ttk.Label(data_page, text=label, style='Section.TLabel').pack(anchor='w', pady=(8, 4))
        boxes[key] = CheckList(data_page, on_toggle=lambda k=key: toggle_visibility(k))
        boxes[key].pack(fill='x', pady=(3, 4))
        boxes[key].bind('<space>', lambda e, k=key: toggle_visibility(k))
        visibility_bar = ttk.Frame(data_page)
        visibility_bar.pack(fill='x', pady=3)
        for caption, mode in [('Show / Hide', None), ('Show all', True), ('Hide all', False)]:
            ttk.Button(visibility_bar, text=caption, command=lambda k=key, m=mode: toggle_visibility(k, m)).pack(side='left', padx=(0, 4))
        buttons = ttk.Frame(data_page)
        buttons.pack(fill='x', pady=4)
        for text, command in [('Add', lambda k=key: add(k)), ('Remove', lambda k=key: modify(k, 'delete')),
                              ('Rename', lambda k=key: modify(k, 'rename')),
                              ('Up', lambda k=key: modify(k, -1)), ('Down', lambda k=key: modify(k, 1))]:
            ttk.Button(buttons, text=text, command=command, width=7).pack(side='left')
        ttk.Button(data_page, text='Label font & position', command=lambda k=key: edit_label_settings(k)).pack(fill='x', pady=3)
        if key == 'samples':
            color_buttons = ttk.Frame(data_page)
            color_buttons.pack(fill='x', pady=3)
            ttk.Button(color_buttons, text='Selected Pattern Color', command=set_selected_color).pack(side='left', fill='x', expand=True)
            ttk.Button(color_buttons, text='Use Global Color', command=lambda: set_selected_color(True)).pack(side='left', fill='x', expand=True)
    ttk.Label(data_page, text='Checked = visible. Unchecked = hidden.\nHidden items stay in the list and are excluded from export.', style='Muted.TLabel', wraplength=365).pack(anchor='w', pady=(10, 0))
    ttk.Separator(data_page).pack(fill='x', pady=(14, 8))
    ttk.Label(data_page, text='Overall plot order', style='Section.TLabel').pack(anchor='w', pady=(0, 4))
    ttk.Label(data_page, text='Drag a row to reorder · or use the buttons below', style='Muted.TLabel').pack(anchor='w', pady=(0, 7))
    order_frame = ttk.Frame(data_page)
    order_frame.pack(fill='x')
    order_tree = ttk.Treeview(order_frame, columns=('kind','label','visible'), show='headings', height=6, selectmode='browse')
    order_tree.heading('kind',text='Type'); order_tree.heading('label',text='Title'); order_tree.heading('visible',text='Show')
    order_tree.column('kind',width=65,minwidth=55,stretch=False)
    order_tree.column('label',width=240,minwidth=100)
    order_tree.column('visible',width=46,minwidth=42,stretch=False)
    order_scroll = SlimScrollbar(order_frame, orient='vertical', command=order_tree.yview)
    order_scroll.pack(side='right',fill='y')
    order_tree.configure(yscrollcommand=order_scroll.set)
    order_tree.pack(side='left',fill='both',expand=True)
    order_ready[0] = True
    order_actions = ttk.Frame(data_page)
    order_actions.pack(fill='x',pady=6)
    ttk.Button(order_actions,text='Move Up',command=lambda: move_global(-1)).pack(side='left',padx=(0,5))
    ttk.Button(order_actions,text='Move Down',command=lambda: move_global(1)).pack(side='left',padx=(0,5))
    ttk.Button(order_actions,text='Reset Order',command=reset_global_order).pack(side='left')
    order_tree.bind('<ButtonPress-1>',begin_order_drag)
    order_tree.bind('<B1-Motion>',move_order_drag)
    order_tree.bind('<ButtonRelease-1>',finish_order_drag)
    order_tree.bind('<Alt-Up>',lambda event: move_global(-1))
    order_tree.bind('<Alt-Down>',lambda event: move_global(1))
    variables = {}
    ttk.Label(layout_page, text='Plot layout', style='Section.TLabel').pack(anchor='w', pady=(0, 5))
    for key, label, default in [('xmin', '2θ minimum (°)', '10'), ('xmax', '2θ maximum (°)', '90'),
                                 ('wavelength', 'CIF wavelength (Å)', '1.54059'), ('spacing', 'Vertical spacing', '1.35'), ('dpi', 'Export DPI (PNG)', '400'),
                                 ('width_cm', 'Image width (cm)', '34.29'), ('height_cm', 'Image height (cm; blank = auto)', ''),
                                 ('xlabel', 'X-axis title', '2θ (°)'), ('ylabel', 'Y-axis title', ''),
                                 ('title', 'Plot title', '')]:
        ttk.Label(layout_page, text=label).pack(anchor='w', pady=(5, 0))
        variables[key] = tk.StringVar(value=default)
        ttk.Entry(layout_page, textvariable=variables[key]).pack(fill='x')
    ttk.Separator(layout_page).pack(fill='x', pady=(18, 12))
    ttk.Label(layout_page, text='Colors', style='Section.TLabel').pack(anchor='w', pady=(0, 5))
    color_controls = ttk.Frame(layout_page)
    color_controls.pack(fill='x')
    ttk.Label(color_controls, text='Global curve color').pack(anchor='w', pady=(5, 0))
    variables['color'] = tk.StringVar(value='#0000dd')
    ttk.Entry(color_controls, textvariable=variables['color']).pack(fill='x')
    ttk.Button(color_controls, text='Apply Color to All Patterns', command=apply_color_to_all).pack(fill='x', pady=3)
    ttk.Label(color_controls, text='Custom palette (click a swatch to choose its color)').pack(anchor='w', pady=(8, 0))
    palette_list = tk.Listbox(color_controls, height=3, exportselection=False, background=theme_colors.get('field','white'), foreground=theme_colors.get('text','#24324a'), selectbackground='#e7edff', selectforeground='#24324a', borderwidth=0, highlightthickness=1, highlightbackground='#e1e7ef')
    palette_list.pack(fill='x')
    palette_list.bind('<Double-Button-1>', lambda event: modify_palette('edit'))
    palette_tools = ttk.Frame(color_controls)
    palette_tools.pack(fill='x', pady=3)
    for label, action in [('Add Color', 'add'), ('Edit Color', 'edit'), ('Remove', 'remove'), ('Up', 'up'), ('Down', 'down')]:
        ttk.Button(palette_tools, text=label, command=lambda a=action: modify_palette(a)).pack(side='left', fill='x', expand=True)
    palette_preview = tk.Canvas(color_controls, height=29, highlightthickness=0, background=theme_colors.get('bg','white'), cursor='hand2')
    palette_preview.pack(fill='x', pady=4)
    palette_preview.bind('<Configure>', update_palette_preview)
    palette_preview.bind('<Button-1>', click_palette)
    palette_ready[0] = True
    ttk.Button(color_controls, text='Apply Custom Palette to All Patterns', command=apply_palette).pack(fill='x', pady=3)
    ttk.Label(layout_page, text='Changes apply with Preview / Update.\nExport size is independent of the window.', style='Muted.TLabel', wraplength=340).pack(anchor='w', pady=12)
    def draw():
        try:
            settings = {}
            for k, v in variables.items():
                value = v.get()
                if k == 'height_cm' and not value.strip():
                    settings[k] = None
                elif k == 'dpi':
                    settings[k] = int(value)
                elif k in ['xmin', 'xmax', 'spacing', 'width_cm', 'height_cm', 'wavelength']:
                    settings[k] = float(value)
                else:
                    settings[k] = value
            samples = []
            cards = []
            for key, loader, result in [('samples', read_sample, samples), ('cards', read_card, cards)]:
                for path, label, override_color, label_style in groups[key]:
                    if not label_style.get('_visible', True):
                        continue
                    row = loader(path, wavelength=settings['wavelength'], upper_angle=settings['xmax']) if key == 'cards' else loader(path)
                    row['label'] = label
                    row['label_style'] = dict(label_style)
                    row['order_id'] = label_style['_order_id']
                    if key == 'samples':
                        row['color'] = override_color or settings['color']
                    result.append(row)
            settings['display_order'] = list(global_order)
            fig = make_figure(samples, cards, **settings)
            for child in preview.winfo_children():
                child.destroy()
            # Fit a centered preview to the viewport without changing its aspect ratio.
            # Change display DPI together with widget dimensions to scale text and curves
            # consistently with the requested physical figure dimensions.
            requested_inches = tuple(float(v) for v in fig.get_size_inches())
            ttk.Label(preview, text=f'Preview: {requested_inches[0] * 2.54:.2f} × {requested_inches[1] * 2.54:.2f} cm | Export: {settings["dpi"]} DPI',
                      anchor='center').pack(side='top', fill='x', pady=4)
            viewport = ttk.Frame(preview)
            canvas = FigureCanvasTkAgg(fig, master=viewport)
            toolbar = NavigationToolbar2Tk(canvas, preview)
            toolbar.update()
            viewport.pack(fill='both', expand=True)
            widget = canvas.get_tk_widget()
            resize_job = [None]
            last_preview_size = [None]
            def cancel_preview_draw(event=None):
                if resize_job[0] is not None:
                    viewport.after_cancel(resize_job[0])
                    resize_job[0] = None
                pending = getattr(canvas, '_idle_draw_id', None)
                if pending:
                    widget.after_cancel(pending)
                    canvas._idle_draw_id = None
            widget.bind('<Destroy>', cancel_preview_draw, add='+')
            def fit_preview(event=None):
                resize_job[0] = None
                if not viewport.winfo_exists():
                    return
                available_width = max(1, viewport.winfo_width() - 20)
                available_height = max(1, viewport.winfo_height() - 20)
                display_dpi = min(available_width / requested_inches[0], available_height / requested_inches[1])
                width = max(1, round(requested_inches[0] * display_dpi))
                height = max(1, round(requested_inches[1] * display_dpi))
                if last_preview_size[0] == (width, height):
                    return
                last_preview_size[0] = (width, height)
                fig.set_dpi(display_dpi)
                widget.place(relx=0.5, rely=0.5, anchor='center', width=width, height=height)
                canvas.draw_idle()
            def queue_preview_resize(event=None):
                if resize_job[0] is not None:
                    viewport.after_cancel(resize_job[0])
                resize_job[0] = viewport.after(100, fit_preview)
            viewport.bind('<Configure>', queue_preview_resize)
            fit_preview()
            rendered.update(fig=fig, samples=samples, cards=cards, settings=settings, canvas=canvas,
                            viewport=viewport, requested_inches=requested_inches)
            return True
        except Exception as e:
            messagebox.showerror('XRD Plotter', str(e))
            return False
    def save(format_name):
        if not draw():
            return
        if format_name == 'data':
            destination = filedialog.askdirectory(title='Choose a parent folder for processed data')
            if not destination:
                return
            name = simpledialog.askstring('Data folder', 'Data folder name:', initialvalue='xrd_processed_data')
            if not name:
                return
            if name in ('.', '..') or '/' in name or '\\' in name:
                messagebox.showerror('Export', 'Enter a folder name without path separators.')
                return
            data_dir = Path(destination) / name
            if data_dir.exists() and not messagebox.askyesno('Overwrite data', 'This folder exists. Overwrite matching data files?'):
                return
            try:
                export_data(data_dir, rendered['samples'], rendered['cards'], rendered['settings'])
                messagebox.showinfo('Export complete', f'Processed data saved to:\n{data_dir}')
            except Exception as e:
                messagebox.showerror('Export', str(e))
            return
        path = filedialog.asksaveasfilename(title=f'Export {format_name.upper()}',
                                            defaultextension='.' + format_name,
                                            filetypes=[(format_name.upper(), '*.' + format_name)])
        if path:
            try:
                export_fig = make_figure(rendered['samples'], rendered['cards'], **rendered['settings'])
                export_fig.savefig(path, format=format_name, dpi=rendered['settings']['dpi'])
                messagebox.showinfo('Export complete', f'{format_name.upper()} saved to:\n{path}')
            except Exception as e:
                messagebox.showerror('Export', str(e))
    ttk.Button(footer, text='Preview / Update', style='Accent.TButton', command=draw).pack(fill='x', pady=5)
    export_buttons = ttk.Frame(footer)
    export_buttons.pack(fill='x', pady=5)
    for index, (label, format_name) in enumerate([('PNG', 'png'), ('PDF', 'pdf'), ('SVG', 'svg'), ('Data', 'data')]):
        ttk.Button(export_buttons, text=label, command=lambda fmt=format_name: save(fmt)).grid(
            row=0, column=index, sticky='ew', padx=2, pady=3)
    export_buttons.columnconfigure(0, weight=1)
    export_buttons.columnconfigure(1, weight=1)
    export_buttons.columnconfigure(2, weight=1)
    export_buttons.columnconfigure(3, weight=1)
    from update_ui import attach as attach_updater
    from updater import data_directory
    session_path = data_directory() / 'update-session.json'
    def save_update_session():
        bundled = default_input_dir().resolve()
        saved_groups = {}
        for kind, items in groups.items():
            saved_groups[kind] = []
            for path, label, color, style in items:
                source = Path(path).resolve()
                location = {'bundled': source.name} if source.parent == bundled else {'path': str(source)}
                saved_groups[kind].append([location, label, color, style])
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.write_text(json.dumps({'groups': saved_groups, 'order': global_order,
            'variables': {key: var.get() for key, var in variables.items()},
            'palette': custom_palette, 'theme': theme_choice.get(), 'scale': scale_choice.get()}), encoding='utf-8')
    attach_updater(root, settings_page, __version__, before_restart=save_update_session)
    apply_ui_appearance()
    initial = Path(initial_dir)
    if initial.is_dir():
        groups['samples'] = [(str(p), re.search(r'\d+C', p.stem).group() if re.search(r'\d+C', p.stem) else p.stem, None, {}) for p in sorted(initial.glob('*.csv'))]
        groups['cards'] = [(str(p), read_card(p)['label'], None, {}) for p in sorted(initial.iterdir()) if p.suffix.lower() in ('.pdf', '.cif', '.xy')]
    if session_path.is_file():
        try:
            session = json.loads(session_path.read_text(encoding='utf-8'))
            restored = {'samples': [], 'cards': []}
            for kind in restored:
                for location, label, color, label_style in session['groups'][kind]:
                    path = default_input_dir() / location['bundled'] if 'bundled' in location else Path(location['path'])
                    if path.is_file():
                        restored[kind].append((str(path), label, color, label_style))
            groups.update(restored)
            global_order[:] = session['order']
            for key, value in session['variables'].items():
                if key in variables:
                    variables[key].set(value)
            custom_palette[:] = session['palette']
            theme_choice.set(session['theme'])
            scale_choice.set(session['scale'])
            session_path.unlink()
        except (OSError, ValueError, KeyError, TypeError):
            pass
    for key in boxes:
        refresh(key)
    if groups['samples']:
        draw()
    apply_ui_appearance()
    if owns_root:
        root.mainloop()


def default_input_dir():
    if getattr(sys, 'frozen', False):
        executable = Path(sys.executable).resolve()
        base = executable.parent
        if sys.platform == 'darwin':
            base = executable.parents[3]
        external = base / 'defaultpattern'
        if external.is_dir():
            return external
    bundled = Path(__file__).resolve().parent / 'defaultpattern'
    return bundled if bundled.is_dir() else Path(__file__).resolve().parent.parent / 'demo-data'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=f'XRD Plotter {__version__}')
    parser.add_argument('--input-dir', default=str(default_input_dir()))
    parser.add_argument('--output', help='Output base path; omit to open GUI')
    parser.add_argument('--xmin', type=float, default=10)
    parser.add_argument('--xmax', type=float, default=90)
    parser.add_argument('--title', default='')
    parser.add_argument('--color', default='#0000dd')
    parser.add_argument('--spacing', type=float, default=1.35)
    parser.add_argument('--dpi', type=int, default=400, help='PNG export resolution in dots per inch')
    parser.add_argument('--width-cm', type=float, default=34.29)
    parser.add_argument('--height-cm', type=float, default=None, help='Omit for automatic height')
    parser.add_argument('--xlabel', default='2θ (°)')
    parser.add_argument('--ylabel', default='')
    parser.add_argument('--wavelength', type=float, default=1.54059, help='CIF calculation wavelength in angstroms')
    args = parser.parse_args()
    if not args.output:
        gui(args.input_dir)
        return
    matplotlib.use('Agg')
    folder = Path(args.input_dir)
    samples = [read_sample(p) for p in sorted(folder.glob('*.csv'))]
    for sample in samples:
        label = re.search(r'\d+C', sample['label'])
        if label:
            sample['label'] = label.group().replace('C', ' °C')
    cards = [read_card(p, wavelength=args.wavelength, upper_angle=args.xmax) for p in sorted(folder.iterdir()) if p.suffix.lower() in ('.pdf', '.cif', '.xy')]
    settings = {k: getattr(args, k) for k in ['xmin', 'xmax', 'title', 'color', 'spacing', 'dpi', 'width_cm', 'height_cm', 'xlabel', 'ylabel', 'wavelength']}
    fig = make_figure(samples, cards, **settings)
    export(fig, args.output, samples, cards, settings)
    print(f'Exported {args.output}.png / .pdf / .svg')
    print('Sample points:', [len(s['x']) for s in samples])
    print('Card peak rows:', [len(c['records']) for c in cards])


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        import tempfile
        error_log = Path(tempfile.gettempdir()) / 'XRD-Plotter-error.log'
        error_log.write_text(traceback.format_exc(), encoding='utf-8')
        raise
