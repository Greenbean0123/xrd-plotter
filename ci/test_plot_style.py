"""Check that line controls affect the intended plot artists and metadata."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from xrd_plotter import make_figure, export_data


class PlotStyleTests(unittest.TestCase):
    def setUp(self):
        points = np.array([[20., 10.], [30., 100.], [40., 25.]])
        self.sample = dict(path='sample.csv', label='Sample', normalization_max=100.,
                           x=points[:, 0], normalized=points[:, 1] / 100,
                           obs=points[:, 1], background=np.zeros(3), corrected=points[:, 1])
        self.sticks = dict(path='reference.csv', label='Sticks', peaks=points,
                           records=[{'2theta': float(x), 'intensity': float(y)} for x, y in points])
        self.profile = dict(self.sticks, label='XY profile', kind='profile')

    def test_separate_widths_and_default_title(self):
        fig = make_figure([self.sample], [self.sticks, self.profile],
                          frame_linewidth=2.5, pattern_linewidth=2.2,
                          card_linewidth=1.4, reference_baseline_linewidth=0.6)
        ax = fig.axes[0]
        self.assertEqual(ax.get_ylabel(), 'Intensity(a.u.)')
        self.assertTrue(all(spine.get_linewidth() == 2.5 for spine in ax.spines.values()))
        self.assertEqual([line.get_linewidth() for line in ax.lines], [1.4, 2.2])
        np.testing.assert_allclose([collection.get_linewidths()[0] for collection in ax.collections],
                                   [0.6, 0.6, 1.4])
        self.assertEqual(make_figure([self.sample], [], ylabel='').axes[0].get_ylabel(), '')

    def test_invalid_widths_and_zero(self):
        for key in ['frame_linewidth', 'pattern_linewidth', 'card_linewidth', 'reference_baseline_linewidth']:
            for value in [-1., float('nan'), float('inf')]:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    make_figure([self.sample], [], **{key: value})
            make_figure([self.sample], [self.sticks], **{key: 0.})

    def test_metadata_preserves_widths(self):
        settings = dict(frame_linewidth=2., pattern_linewidth=1.5, card_linewidth=1.,
                        reference_baseline_linewidth=0.3, ylabel='Intensity(a.u.)')
        with tempfile.TemporaryDirectory() as directory:
            export_data(directory, [self.sample], [self.sticks], settings)
            result = json.loads((Path(directory) / 'processing.json').read_text(encoding='utf-8'))
            self.assertEqual(result['settings'], settings)


if __name__ == '__main__':
    unittest.main()
