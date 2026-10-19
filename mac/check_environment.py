"""Validate imports, native libraries, Tk windows and required export backends."""
import sys
import platform
import tkinter
import numpy
import matplotlib
import pdfplumber
import gemmi
from PIL import Image, ImageTk
from matplotlib.backends import backend_tkagg, backend_pdf, backend_svg

assert (3, 11) <= sys.version_info[:2] <= (3, 13), 'Use Python 3.11–3.13'
root = tkinter.Tk()
root.withdraw()
root.update()
print('Python:', sys.version.split()[0], 'Architecture:', platform.machine())
print('Tk:', root.tk.call('info', 'patchlevel'))
print('NumPy:', numpy.__version__, 'Matplotlib:', matplotlib.__version__)
print('PDF/CIF/XY and PNG/PDF/SVG export dependencies ready.')
root.destroy()
