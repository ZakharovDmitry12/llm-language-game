"""Exercise match continuation, paid-error accounting and payouts with a fake API."""
import os
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lg_game import api, runner, storage


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'sample.sqlite'
        storage.generate(self.db, seed=123, preset='pilot', models_path=ROOT / 'config/models.json')

    def tearDown(self):
        self.temp.cleanup()

    def test_resume_does_not_repeat_valid_offer_or_technical_failure(self):
        con = storage.connect(self.db)
        con.execute("UPDATE tasks SET status_proposer='invalid' WHERE stage='II'")
        task_id = con.execute("SELECT task_id FROM tasks WHERE stage='II' AND model='qwen' ORDER BY seq LIMIT 1").fetchone()[0]
        con.execute("UPDATE tasks SET status_proposer='not_run' WHERE task_id=?", (task_id,))
        con.commit(); con.close()
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'dummy-for-mocked-client'}), \
             patch('lg_game.api.request_openrouter', side_effect=[
                 {'text':'30', 'usage':{'cost':.001}}, RuntimeError('timeout')]) as request:
            first = runner.run(self.db, budget=.1, max_requests=1, model='qwen', stage='II')
            second = runner.run(self.db, budget=.1, max_requests=1, model='qwen', stage='II')
            third = runner.run(self.db, budget=.1, max_requests=1, model='qwen', stage='II')
        self.assertEqual(request.call_count, 2)
        self.assertEqual(first['requests_this_run'], 1)
        self.assertEqual(second['requests_this_run'], 1)
        self.assertEqual(third['requests_this_run'], 0)
        con = storage.connect(self.db)
        task = con.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        attempts = list(con.execute('SELECT * FROM attempts WHERE task_id=? ORDER BY id', (task_id,)))
        self.assertEqual((task['x'], task['status_proposer'], task['status_responder']), (30, 'valid', 'technical_error'))
        self.assertIsNone(task['payoff_p'])
        self.assertEqual([a['outcome'] for a in attempts], ['valid', 'technical_error'])
        self.assertGreater(runner.spent(con), .001)
        con.close()

    def test_mock_and_live_cannot_share_database(self):
        runner.run(self.db, budget=0, mock=True, max_requests=1)
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'dummy-for-mocked-client'}), \
             patch('lg_game.api.request_openrouter') as request:
            with self.assertRaises((ValueError, RuntimeError)):
                runner.run(self.db, budget=1, mock=False, max_requests=1)
        request.assert_not_called()

    def test_stage_iv_cost_paid_even_if_rejected(self):
        con = storage.connect(self.db)
        task_id = con.execute("SELECT task_id FROM tasks WHERE stage='IV' LIMIT 1").fetchone()[0]
        con.execute("UPDATE tasks SET x=30, chosen_language='Russian', charged_language='Russian', cost=5, status_proposer='valid', status_responder='in_flight' WHERE task_id=?", (task_id,))
        cur = con.execute("INSERT INTO attempts(task_id,role,started_at,model_id,prompt,outcome,request_params,reserved_cost) VALUES (?, 'responder', 'test', 'test', 'test', 'in_flight', '{}', 0)", (task_id,))
        task = con.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        runner.save_outcome(con, task, 'responder', cur.lastrowid, result={'text':'0','usage':{}}, mock=True)
        saved = con.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        self.assertEqual((saved['a'], saved['payoff_p'], saved['payoff_a']), (0, -5, 0))
        self.assertEqual(saved['status_responder'], 'valid')
        con.close()

    def test_parser_hash_required_and_unchanged(self):
        con = storage.connect(self.db)
        con.execute("UPDATE metadata SET value=? WHERE key='parser_hash'", ('"altered"',))
        con.commit()
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'dummy-for-mocked-client'}), \
             patch('lg_game.api.request_openrouter') as request:
            with self.assertRaisesRegex(ValueError, 'Parser'):
                runner.run(self.db, budget=.1, max_requests=1)
            request.assert_not_called()
            con.execute("DELETE FROM metadata WHERE key='parser_hash'")
            con.commit()
            with self.assertRaisesRegex(ValueError, 'Parser'):
                runner.run(self.db, budget=.1, max_requests=1)
            request.assert_not_called()
        self.assertEqual(con.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 0)
        storage.export_csv(con, Path(self.temp.name) / 'old-export.csv')
        self.assertTrue((Path(self.temp.name) / 'old-export.csv').exists())
        con.close()

    def test_budget_prevents_call(self):
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'dummy-for-mocked-client'}), \
             patch('lg_game.api.request_openrouter') as request:
            result = runner.run(self.db, budget=0, max_requests=1)
        self.assertEqual(result['requests_this_run'], 0)
        self.assertEqual(result['stopped'], 'budget')
        request.assert_not_called()

    def test_openrouter_error_in_http_200_stops_the_run(self):
        body = b'{"error":{"code":503,"message":"provider unavailable"}}'
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'dummy-for-mocked-client'}), \
             patch.object(api.urllib.request, 'urlopen', return_value=io.BytesIO(body)) as request:
            result = runner.run(self.db, budget=.1, model='luna', stage='II')
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result['stopped'], 'technical_error')
        self.assertIn('503', result['last_error'])
        self.assertEqual(result['invalid_this_run'], 0)
        con = storage.connect(self.db)
        try:
            self.assertEqual(con.execute('SELECT outcome FROM attempts').fetchone()[0], 'technical_error')
        finally:
            con.close()


if __name__ == '__main__':
    unittest.main()
