"""Build the standalone application including its icon and update checker."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
    '--name', 'UV-Vis Plotter 0.0.1', '--distpath', str(ROOT / 'dist'),
    '--workpath', str(ROOT / 'build'), '--specpath', str(ROOT / 'build'),
    '--icon', str(ROOT / 'assets' / 'uvvis.ico'),
    '--add-data', f'{ROOT / "assets"};assets',
    '--exclude-module', 'scipy', '--exclude-module', 'pandas',
    '--exclude-module', 'IPython', '--exclude-module', 'pytest',
    str(ROOT / 'uvvis_plotter.py')], check=True)
