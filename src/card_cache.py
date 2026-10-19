"""Cache parsed reference data without changing the original input files."""
from pathlib import Path
from functools import lru_cache
import hashlib
import json
import os
import sys
import tempfile
import numpy as np


def cache_directory():
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Caches' / 'XRD Plotter' / 'references-v1'
    return Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'XRD Plotter' / 'references-v1'


def load_card(path, wavelength, upper_angle, parser):
    path = Path(path).resolve()
    stat = path.stat()
    # Copy the top-level dictionary: GUI labels and colors must not modify the cache.
    return dict(_load(str(path), stat.st_mtime_ns, stat.st_size, wavelength, upper_angle, parser))


@lru_cache(maxsize=64)
def _load(path, mtime_ns, size, wavelength, upper_angle, parser):
    source = Path(path)
    if source.suffix.lower() != '.pdf':
        return parser(source, wavelength, upper_angle)
    key = hashlib.sha256(b'xrd-pdf-v1\0' + source.name.encode() + source.read_bytes()).hexdigest()
    cached = cache_directory() / f'{key}.json'
    try:
        row = json.loads(cached.read_text(encoding='utf-8'))
        peaks = np.asarray(row['peaks'], dtype=float)
        if peaks.ndim != 2 or peaks.shape[1] != 2 or not np.isfinite(peaks).all() or not row['records']:
            raise ValueError('Invalid cached peaks')
        row.update(peaks=peaks, path=str(source))
        return row
    except (OSError, ValueError, KeyError, TypeError):
        pass
    row = parser(source, wavelength, upper_angle)
    temporary = None
    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(row, peaks=row['peaks'].tolist())
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=cached.parent,
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False)
        os.replace(temporary, cached)
    except OSError:
        pass  # Read-only/full cache storage must not prevent plotting.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return row
