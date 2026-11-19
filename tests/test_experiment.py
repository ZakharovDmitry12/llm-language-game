"""Integration checks for the published experimental design (no network)."""
import collections
import csv
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def cli(*args):
    env = dict(os.environ)
    env.pop('OPENROUTER_API_KEY', None)
    return subprocess.run([sys.executable, '-m', 'lg_game', *map(str, args)],
                          cwd=ROOT, env=env, text=True, capture_output=True, check=True)


def rows(path):
    with open(path, newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


class ScheduleTests(unittest.TestCase):
    def test_full_schedule_matches_project(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'full.sqlite'
            export = Path(directory) / 'full.csv'
            cli('generate', '--db', database, '--seed', '123', '--preset', 'full')
            cli('export', '--db', database, '--out', export)
            data = rows(export)
        self.assertEqual(len(data), 7200)
        self.assertEqual({r['model'] for r in data}, {'luna', 'qwen', 'hy4'})
        self.assertEqual(collections.Counter(r['stage'] for r in data),
                         {'I': 2700, 'II': 3000, 'III': 600, 'IV': 900})
        self.assertEqual(len({r['task_id'] for r in data}), len(data))
        stage1 = [r for r in data if r['stage'] == 'I']
        self.assertEqual(set(collections.Counter((r['model'], r['language'], r['x'])
                                                  for r in stage1).values()), {50})
        self.assertEqual(len({(r['model'], r['language'], r['x']) for r in stage1}), 54)
        self.assertEqual({int(float(r['x'])) for r in stage1}, set(range(10, 100, 10)))
        stage2 = [r for r in data if r['stage'] == 'II']
        self.assertEqual(len({(r['model'], r['language'], r['reveal']) for r in stage2}), 12)
        self.assertEqual(set(collections.Counter((r['model'], r['language'], r['reveal'])
                                                  for r in stage2).values()), {250})
        stage3 = [r for r in data if r['stage'] == 'III']
        self.assertEqual(len({(r['model'], r['language']) for r in stage3}), 6)
        self.assertEqual(set(collections.Counter((r['model'], r['language'])
                                                  for r in stage3).values()), {100})
        stage4 = [r for r in data if r['stage'] == 'IV']
        self.assertEqual({r['model'] for r in stage4}, {'luna', 'hy4'})
        self.assertEqual(len({(r['model'], r['D'], r['c']) for r in stage4}), 12)
        self.assertEqual(set(collections.Counter((r['model'], r['D'], r['c'])
                                                  for r in stage4).values()), {75})
        self.assertEqual({int(float(r['c'])) for r in stage4}, {0, 2, 5})

    def test_seed_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = []
            for number in (1, 2):
                database = Path(directory) / f'{number}.sqlite'
                export = Path(directory) / f'{number}.csv'
                cli('generate', '--db', database, '--seed', '42', '--preset', 'pilot')
                cli('export', '--db', database, '--out', export)
                outputs.append(rows(export))
        fields = ('stage', 'model', 'language', 'reveal', 'x', 'D', 'c')
        self.assertEqual([[r[f] for f in fields] for r in outputs[0]],
                         [[r[f] for f in fields] for r in outputs[1]])


if __name__ == '__main__':
    unittest.main()
