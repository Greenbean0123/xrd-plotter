"""Build on Windows or macOS using the current Python architecture."""
from pathlib import Path
import platform
import subprocess
import sys
import shutil
import runpy
import plistlib

ROOT = Path(__file__).resolve().parent
VERSION = runpy.run_path(str(ROOT / 'src' / 'app_version.py'))['__version__']
SAMPLES = ROOT / 'src' / 'defaultpattern'
if not SAMPLES.is_dir():
    SAMPLES = ROOT / 'demo-data'

def main():
    system = platform.system()
    if system not in ('Windows', 'Darwin'):
        raise SystemExit('Build on Windows or macOS.')
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed',
            '--name', 'XRD Plotter', '--paths', str(ROOT / 'src'),
            '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build'),
            '--specpath', str(ROOT / 'build'), '--hidden-import', 'PIL._tkinter_finder',
            '--hidden-import', 'matplotlib.backends.backend_pdf',
            '--hidden-import', 'matplotlib.backends.backend_svg',
            '--hidden-import', 'matplotlib.backends.backend_agg',
            '--icon', str(ROOT / 'assets' / ('xrd-plotter.ico' if system == 'Windows' else 'xrd-plotter.icns')),
            '--add-data', f'{ROOT / "assets" / "xrd-plotter-icon.png"}:assets',
            '--add-data', f'{ROOT / "src" / "update_config.json"}:.',
            '--add-data', f'{SAMPLES}:defaultpattern']
    args += ['--onefile'] if system == 'Windows' else ['--onedir', '--osx-bundle-identifier', 'org.xrdplotter.app']
    if system == 'Windows':
        version_file = ROOT / 'build' / 'windows-version.txt'
        version_file.parent.mkdir(parents=True, exist_ok=True)
        numeric_version = tuple(map(int, VERSION.split('.'))) + (0,)
        version_file.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numeric_version}, prodvers={numeric_version},
    mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('FileDescription', 'XRD Plotter'),
    StringStruct('FileVersion', '{VERSION}'),
    StringStruct('ProductName', 'XRD Plotter'),
    StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding='utf-8')
        args += ['--version-file', str(version_file)]
    subprocess.run(args + [str(ROOT / 'src' / 'startup.py')], check=True, cwd=ROOT)
    if system == 'Darwin':
        app = ROOT / 'dist' / 'XRD Plotter.app'
        plist_path = app / 'Contents' / 'Info.plist'
        with plist_path.open('rb') as stream:
            info = plistlib.load(stream)
        info.update(CFBundleVersion=VERSION, CFBundleShortVersionString=VERSION)
        with plist_path.open('wb') as stream:
            plistlib.dump(info, stream)
        subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
        stage = ROOT / 'build' / 'dmg'
        stage.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / 'dist' / 'XRD Plotter.app', stage / 'XRD Plotter.app', dirs_exist_ok=True)
        link = stage / 'Applications'
        if not link.exists():
            link.symlink_to('/Applications')
        subprocess.run(['hdiutil', 'create', '-volname', 'XRD Plotter', '-srcfolder', str(stage),
                        '-ov', '-format', 'UDZO', str(ROOT / 'dist' / f'XRD_Plotter_{VERSION}_Mac_{platform.machine()}.dmg')], check=True)
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app),
                        str(ROOT / 'dist' / f'XRD_Plotter_{VERSION}_Mac_{platform.machine()}_update.zip')], check=True)

if __name__ == '__main__':
    main()
