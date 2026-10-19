"""Create a Mac ZIP with Unix executable permissions and LF line endings."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent
output = root / 'releases' / 'XRD_Plotter_Mac.zip'
output.parent.mkdir(parents=True, exist_ok=True)
files = [root / name for name in ('Start.command', 'Repair.command', 'Diagnose.command',
         'Build-Mac.command', 'build.py', 'requirements-build.txt', 'Mac-Instructions.txt', 'Update-Publishing.md', 'LICENSE', 'README.md')]
files += [p for folder in ('src', 'mac', 'demo-data') for p in (root / folder).rglob('*')
          if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
files += [p for p in (root / 'mac-launcher').rglob('*') if p.is_file()]
files += [p for p in (root / 'assets').iterdir() if p.is_file()]
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        relative = path.relative_to(root)
        if relative.parts[0] == 'mac-launcher':
            relative = relative.relative_to('mac-launcher')
        name = 'XRD_Plotter_Mac/' + relative.as_posix()
        info = zipfile.ZipInfo(name)
        info.create_system = 3
        executable = path.suffix in ('.command', '.sh') or path.name == 'launch'
        info.external_attr = (0o100755 if executable else 0o100644) << 16
        data = path.read_bytes()
        if path.suffix in ('.command', '.sh', '.py', '.txt') or path.name == 'launch':
            data = data.replace(b'\r\n', b'\n')
        archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
    for item in archive.infolist():
        if item.filename.endswith(('.command', '.sh', '/MacOS/launch')):
            assert (item.external_attr >> 16) & 0o111
            assert b'\r' not in archive.read(item)
print(output)
