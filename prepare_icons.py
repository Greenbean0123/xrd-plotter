"""Convert the approved PNG to native application icon containers."""
from pathlib import Path
from PIL import Image
import shutil

root = Path(__file__).resolve().parent
assets = root / 'assets'
with Image.open(assets / 'xrd-plotter-icon.png') as source:
    icon = source.convert('RGBA').resize((1024, 1024), Image.Resampling.LANCZOS)
    icon.save(assets / 'xrd-plotter.ico', sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    icon.save(assets / 'xrd-plotter.icns', sizes=[(s, s) for s in (16, 32, 64, 128, 256, 512, 1024)])
resources = root / 'mac-launcher' / 'XRD Plotter.app' / 'Contents' / 'Resources'
resources.mkdir(parents=True, exist_ok=True)
shutil.copy2(assets / 'xrd-plotter.icns', resources / 'xrd-plotter.icns')
for name in ('xrd-plotter.ico', 'xrd-plotter.icns'):
    with Image.open(assets / name) as check:
        check.load()
        print(name, check.format, check.size)
