"""Unit tests for instructions and deterministic output parsing."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lg_game import parsing, prompts


class InstructionsTests(unittest.TestCase):
    def test_hidden_language_does_not_change_proposer_prompt(self):
        a = prompts.proposer('II', language='English', reveal=0)
        b = prompts.proposer('II', language='Russian', reveal=0)
        self.assertEqual(a, b)
        self.assertNotIn('In this round', a)
        en = prompts.proposer('II', language='English', reveal=1)
        ru = prompts.proposer('II', language='Russian', reveal=1)
        self.assertNotEqual(en, ru)
        for revealed, language in ((en, 'English'), (ru, 'Russian')):
            self.assertIn(f"the other player's instructions are in {language}", revealed)
            self.assertEqual(revealed.replace('\n\n' + prompts.REVEAL.format(language=language), ''), a)

    def test_same_answer_in_stage_i_and_ii(self):
        for language in ('English', 'Russian'):
            for offer in range(10, 100, 10):
                self.assertEqual(prompts.responder('I', language, offer),
                                 prompts.responder('II', language, offer))
                self.assertIn(str(offer), prompts.responder('I', language, offer))

    def test_stage_iv_acceptance_sees_offer_message_only(self):
        en = prompts.responder('IV', 'English', 30)
        ru = prompts.responder('IV', 'Russian', 30)
        self.assertIn('I offer you 30 of the 100 points', en)
        self.assertIn('Предлагаю вам 30 из 100 очков', ru)
        self.assertNotIn('costs you 5 points', en)
        self.assertNotIn('costs you 5 points', ru)


class ParsingTests(unittest.TestCase):
    def test_strict_offer(self):
        for value in range(10, 100, 10):
            self.assertEqual(parsing.parse_offer(f' {value}\n'), value)
        for value in ('', '0', '25', '100', 'I offer 30', '30 or 40', '-10'):
            self.assertIsNone(parsing.parse_offer(value), value)

    def test_decision_distinguishes_rejection_from_invalid(self):
        self.assertEqual(parsing.parse_decision('0'), 0)
        self.assertEqual(parsing.parse_decision(' 1\n'), 1)
        for value in ('', 'no', '2', '0 or 1'):
            self.assertIsNone(parsing.parse_decision(value))

    def test_forecast_validation(self):
        self.assertEqual(parsing.parse_forecast('[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1]'),
                         [0, .1, .2, .3, .4, .5, .6, .7, 1])
        for value in ('[0, 1]', '[0,0,0,0,0,0,0,0,1.1]',
                      '[0,0,0,0,0,0,0,0,NaN]', '[0,0,0,0,0,0,0,0,true]'):
            self.assertIsNone(parsing.parse_forecast(value), value)

    def test_forecast_last_line(self):
        expected = [0, .1, .2, .3, .4, .5, .6, .7, 1]
        self.assertEqual(parsing.parse_forecast('Reasoning:\n**0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1**'), expected)
        self.assertEqual(parsing.parse_forecast('Reasoning:\n[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1]'), expected)
        self.assertIsNone(parsing.parse_forecast('Reasoning:\nHere: 0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1'))
        self.assertIsNone(parsing.parse_forecast('Reasoning:\n| 0 | .1 | .2 | .3 | .4 | .5 | .6 | .7 | 1 |'))
        self.assertIsNone(parsing.parse_forecast('Reasoning:\n**0, 0.1, 0.2**'))

    def test_offer_points_and_language(self):
        self.assertEqual(parsing.parse_offer_language("40 points, Russian"), (40, "Russian"))
        self.assertEqual(parsing.parse_offer_language("English, 40 points"), (40, "English"))
        self.assertEqual(parsing.parse_offer_language("**40, English**"), (40, "English"))
        self.assertIsNone(parsing.parse_offer_language("Explanation: **40, English**"))
        self.assertIsNone(parsing.parse_offer_language("**40, English** and something else"))
        self.assertIsNone(parsing.parse_offer_language("I offer 40 points, Russian"))

    def test_offer_and_language(self):
        self.assertEqual(parsing.parse_offer_language('30, Russian'), (30, 'Russian'))
        self.assertEqual(parsing.parse_offer_language('english 10'), (10, 'English'))
        for value in ('30', '25 Russian', '30 German', '30 English or Russian'):
            self.assertIsNone(parsing.parse_offer_language(value))


if __name__ == '__main__':
    unittest.main()
