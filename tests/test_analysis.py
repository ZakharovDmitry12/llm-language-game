"""Known numerical cases for estimates and missing-outcome bounds."""
import math
import csv
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import numpy as np
    import pandas as pd
    import analysis
except ModuleNotFoundError:
    np = pd = analysis = None


@unittest.skipIf(analysis is None, 'Install requirements-analysis.txt for statistical tests')
class AnalysisTests(unittest.TestCase):
    def test_interaction_and_hc3(self):
        values = {('English', 0): [.2, .4], ('Russian', 0): [.1, .3],
                  ('English', 1): [.2, .4], ('Russian', 1): [.5, .7]}
        result = analysis.contrast_stats(values)
        self.assertAlmostEqual(result['estimate'], .4)
        self.assertAlmostEqual(result['se_hc3'], math.sqrt(.08))
        self.assertLess(result['ci_lower'], result['estimate'])
        self.assertGreater(result['ci_upper'], result['estimate'])

    def test_missing_bounds_use_sign_of_contrast(self):
        values = {('English', 0): [.2, None], ('Russian', 0): [.6, None],
                  ('English', 1): [.4, None], ('Russian', 1): [.8, None]}
        low, high = analysis.contrast_bounds(values, .1, .9)
        self.assertAlmostEqual(low, -.8)
        self.assertAlmostEqual(high, .8)

    def test_average_payoff_effect_not_interaction(self):
        rows = []
        for lang, reveal, payoff in [('English', 0, 10), ('Russian', 0, 30),
                                      ('English', 1, 40), ('Russian', 1, 60)]:
            for _ in range(2):
                rows.append({'model': 'm', 'language': lang, 'reveal': reveal,
                             'Y': .5, 'payoff_p_calculated': payoff})
        with tempfile.TemporaryDirectory() as directory:
            _, estimates = analysis._stage2(pd.DataFrame(rows), Path(directory))
        payoff = next(row for row in estimates if row['outcome'] == 'payoff')
        self.assertAlmostEqual(payoff['estimate'], 30)
        self.assertAlmostEqual(payoff['missing_bound_lower'], 30)
        self.assertAlmostEqual(payoff['missing_bound_upper'], 30)

    def test_zero_variance_has_no_spurious_significance(self):
        values = {cell: [.5, .5] for cell in analysis.CELLS}
        result = analysis.contrast_stats(values)
        self.assertTrue(np.isnan(result['p_value']))
        self.assertIn('variance', result['warning'].lower())

    def test_mock_pipeline_produces_analysis(self):
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop('OPENROUTER_API_KEY', None)
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            database, export, output = temp / 'pilot.sqlite', temp / 'pilot.csv', temp / 'results'
            def call(*args):
                subprocess.run([sys.executable, *map(str, args)], cwd=root, env=env,
                               text=True, capture_output=True, check=True)
            call('-m', 'lg_game', 'generate', '--db', database, '--seed', 23, '--preset', 'pilot')
            call('-m', 'lg_game', 'run', '--db', database, '--budget', 0, '--mock')
            call('-m', 'lg_game', 'export', '--db', database, '--out', export)
            call('analysis.py', export, '--output', output, '--bootstrap', 5)
            with (output / 'stage_II_contrasts.csv').open(newline='', encoding='utf8') as stream:
                results = list(csv.DictReader(stream))
            self.assertEqual(len(results), 6)
            self.assertTrue((output / 'stage_I_acceptance.csv').is_file())
            self.assertTrue((output / 'stage_III_predictions.csv').is_file())
            self.assertTrue((output / 'stage_IV_choice.csv').is_file())
            self.assertTrue((output / 'README_analysis.md').is_file())
            self.assertEqual(len(list(output.glob('acceptance_*.png'))), 3)

    def test_holm_preserves_missing_tests_in_family(self):
        adjusted = analysis.holm([.01, .04, float('nan')])
        self.assertAlmostEqual(adjusted[0], .03)
        self.assertAlmostEqual(adjusted[1], .08)
        self.assertTrue(np.isnan(adjusted[2]))


if __name__ == '__main__':
    unittest.main()
