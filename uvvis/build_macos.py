"""Build a Mac trial application and DMG without publishing a release."""
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
from PIL import Image

ROOT = Path(__file__).resolve().parent
VERSION = '0.0.1'


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Run this build on a Mac.')
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    icon = build / 'uvvis.icns'
    with Image.open(ROOT / 'assets' / 'uvvis.png') as image:
        image.convert('RGBA').resize((1024, 1024)).save(icon, format='ICNS')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed',
        '--name', 'UV-Vis Plotter', '--distpath', str(ROOT / 'dist'),
        '--workpath', str(build), '--specpath', str(build), '--icon', str(icon),
        '--osx-bundle-identifier', 'org.uvvisplotter.app',
        '--add-data', f'{ROOT / "assets"}:assets',
        '--exclude-module', 'scipy', '--exclude-module', 'pandas',
        '--exclude-module', 'IPython', '--exclude-module', 'pytest',
        str(ROOT / 'mac_entry.py')], check=True, cwd=ROOT)
    app = ROOT / 'dist' / 'UV-Vis Plotter.app'
    plist = app / 'Contents' / 'Info.plist'
    info = plistlib.loads(plist.read_bytes())
    info.update(CFBundleVersion=VERSION, CFBundleShortVersionString=VERSION)
    plist.write_bytes(plistlib.dumps(info))
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    expected = platform.machine()
    binary = app / 'Contents' / 'MacOS' / 'UV-Vis Plotter'
    assert expected in subprocess.check_output(['lipo', '-archs', str(binary)], text=True).split()
    with tempfile.TemporaryDirectory(prefix='uvvis-smoke-') as directory:
        subprocess.run([str(binary), '--smoke-test', directory], check=True, timeout=120)
        assert (Path(directory) / 'ready.txt').is_file()
        for suffix in ('png', 'pdf', 'svg'):
            assert (Path(directory) / ('smoke.' + suffix)).stat().st_size > 1000
    output = ROOT / 'cloud-output'
    output.mkdir(exist_ok=True)
    label = 'AppleSilicon' if expected == 'arm64' else 'Intel'
    stem = f'UV-Vis-Plotter-{VERSION}-Mac-{label}-Trial'
    with tempfile.TemporaryDirectory(prefix='uvvis-dmg-', dir=build) as directory:
        stage = Path(directory)
        shutil.copytree(app, stage / app.name, symlinks=True)
        (stage / 'Applications').symlink_to('/Applications')
        dmg = output / (stem + '.dmg')
        subprocess.run(['hdiutil', 'create', '-volname', 'UV-Vis Plotter', '-srcfolder', str(stage),
                        '-ov', '-format', 'UDZO', str(dmg)], check=True)
    subprocess.run(['hdiutil', 'verify', str(dmg)], check=True)
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app),
                    str(output / (stem + '.zip'))], check=True)


if __name__ == '__main__':
    main()
