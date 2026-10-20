"""Validate Mac build metadata, signatures, bundled export and DMG integrity."""
from pathlib import Path
import hashlib
import json
import os
import platform
import plistlib
import runpy
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
version = runpy.run_path(str(root / 'src' / 'app_version.py'))['__version__']
app = root / 'dist' / 'XRD Plotter.app'
binary = app / 'Contents' / 'MacOS' / 'XRD Plotter'
expected_arch = os.environ.get('EXPECTED_ARCH', platform.machine())
with (app / 'Contents' / 'Info.plist').open('rb') as stream:
    info = plistlib.load(stream)
assert info['CFBundleVersion'] == info['CFBundleShortVersionString'] == version
architectures = subprocess.check_output(['lipo', '-archs', str(binary)], text=True).split()
assert expected_arch in architectures, architectures
subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
with tempfile.TemporaryDirectory(prefix='xrd-cloud-test-') as directory:
    output = Path(directory) / 'plot'
    # Deliberately do not pass --input-dir: test the samples bundled in the app.
    subprocess.run([str(binary), '--output', str(output), '--dpi', '80',
                    '--frame-linewidth', '2', '--pattern-linewidth', '1.5',
                    '--card-linewidth', '1.2', '--reference-baseline-linewidth', '0.3'],
                   cwd=directory, check=True, timeout=120)
    for suffix in ('.png', '.pdf', '.svg'):
        assert output.with_suffix(suffix).stat().st_size > 1000
    metadata = json.loads((Path(directory) / 'plot_data' / 'processing.json').read_text())
    assert len(metadata['samples']) == 2 and len(metadata['cards']) == 3
    assert metadata['settings']['ylabel'] == 'Intensity(a.u.)'
    for key, value in [('frame_linewidth', 2), ('pattern_linewidth', 1.5),
                       ('card_linewidth', 1.2), ('reference_baseline_linewidth', 0.3)]:
        assert metadata['settings'][key] == value, key

dmg = root / 'dist' / f'XRD_Plotter_{version}_Mac_{platform.machine()}.dmg'
subprocess.run(['hdiutil', 'verify', str(dmg)], check=True)
with tempfile.TemporaryDirectory(prefix='xrd-dmg-verify-') as mountpoint:
    subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', mountpoint, str(dmg)], check=True)
    try:
        subprocess.run(['codesign', '--verify', '--deep', '--strict',
                        str(Path(mountpoint) / 'XRD Plotter.app')], check=True)
    finally:
        subprocess.run(['hdiutil', 'detach', mountpoint], check=True)
output_dir = root / 'cloud-output'
output_dir.mkdir(exist_ok=True)
label = 'AppleSilicon' if expected_arch == 'arm64' else 'Intel'
installer = output_dir / f'XRD_Plotter_{version}_Mac_{label}.dmg'
shutil.copy2(dmg, installer)
update_zip = root / 'dist' / f'XRD_Plotter_{version}_Mac_{platform.machine()}_update.zip'
shutil.copy2(update_zip, output_dir / update_zip.name)
digest = hashlib.sha256(installer.read_bytes()).hexdigest()
(output_dir / 'SHA256SUMS.txt').write_text(f'{digest}  {installer.name}\n')
(output_dir / 'Build-Info.json').write_text(json.dumps({
    'version': version, 'architecture': expected_arch,
    'commit': os.environ.get('GITHUB_SHA'),
    'validated': ['bundle version', 'architecture', 'ad-hoc signature',
                  'bundled samples', 'PNG/PDF/SVG export', 'line widths and Y-axis title', 'DMG integrity'],
    'developer_id_signed': False, 'notarized': False,
}, indent=2))
print(f'Verified: {installer.name}')
