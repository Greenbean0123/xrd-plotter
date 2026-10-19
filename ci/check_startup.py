"""Run on a machine with a desktop to check cache correctness and GUI startup."""
from pathlib import Path
import runpy
import sys
import tempfile
import time
import tkinter as tk

root_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root_dir / 'src'))

def check_cache():
    import numpy as np
    import card_cache
    import xrd_plotter
    with tempfile.TemporaryDirectory() as directory:
        card_cache.cache_directory = lambda: Path(directory)
        card = next(xrd_plotter.default_input_dir().glob('*.pdf'))
        calls = []
        def parser(*args):
            calls.append(1)
            return xrd_plotter._parse_card(*args)
        cold = card_cache.load_card(card, 1.54059, 100, parser)
        cold['label'] = 'Changed by UI'
        warm = card_cache.load_card(card, 1.54059, 100, parser)
        assert warm['label'] != cold['label'] and len(calls) == 1
        card_cache._load.cache_clear()
        disk = card_cache.load_card(card, 1.54059, 100, parser)
        np.testing.assert_array_equal(warm['peaks'], disk['peaks'])
        assert warm['records'] == disk['records'] and len(calls) == 1
        next(Path(directory).glob('*.json')).write_text('broken cache')
        card_cache._load.cache_clear()
        recovered = card_cache.load_card(card, 1.54059, 100, parser)
        np.testing.assert_array_equal(warm['peaks'], recovered['peaks'])
        assert len(calls) == 2
        card_cache._load.cache_clear()

# A fresh process is used by the parent below for the real cold-import test.
if '--gui-child' not in sys.argv:
    check_cache()
    import subprocess
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--gui-child'],
                            check=True, timeout=90, capture_output=True, text=True)
    print(result.stdout)
    print('Cache reuse, disk cache, corruption recovery and GUI checks passed.')
else:
    import startup
    original = tk.Tk
    timings = {}
    start = time.perf_counter()
    def instrumented_tk(*args, **kwargs):
        window = original(*args, **kwargs)
        def observe():
            if window.winfo_viewable() and 'visible' not in timings:
                timings['visible'] = time.perf_counter() - start
            if hasattr(window, '_startup_seconds'):
                timings['ready'] = window._startup_seconds
                window.destroy()
            else:
                window.after(50, observe)
        window.after(50, observe)
        return window
    tk.Tk = instrumented_tk
    sys.argv = [str(root_dir / 'src' / 'startup.py')]
    startup.launch()
    assert 'visible' in timings and 'ready' in timings, timings
    print(timings)
