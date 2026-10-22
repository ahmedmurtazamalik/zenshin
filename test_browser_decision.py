import unittest
from unittest.mock import patch

import ai_decision


class BrowserDecisionTests(unittest.TestCase):
    def test_selects_candidate_position_after_waiting_for_semantic_choice(self):
        candidates = [{"name": "I want product emails"}, {"name": "Our user agreement applies"}]
        choice = {"decision": "approve", "response": "1", "reason": "Account agreement"}
        with patch.object(ai_decision, "start", return_value="job") as start, \
             patch.object(ai_decision, "result", side_effect=[None, choice]) as result, \
             patch.object(ai_decision.time, "sleep") as sleep:
            self.assertEqual(ai_decision.select_browser_control("terms", candidates, "Accept agreement"), 1)
        start.assert_called_once_with({"kind": "terms", "candidates": candidates,
                                       "hint": "Accept agreement"}, prompt=ai_decision.BROWSER_PROMPT)
        result.assert_called_with("job")
        sleep.assert_called_once_with(.1)

    def test_no_matching_control_returns_none(self):
        choice = {"decision": "no_response", "response": None, "reason": "Only confirmation fields"}
        with patch.object(ai_decision, "start"), patch.object(ai_decision, "result", return_value=choice):
            self.assertIsNone(ai_decision.select_browser_control("password", [{"name": "Repeat secret"}]))

    def test_unavailable_or_non_integer_selection_is_rejected(self):
        for response in ("-1", "1", "0.0"):
            with self.subTest(response=response), patch.object(ai_decision, "start"), \
                 patch.object(ai_decision, "result", return_value={
                     "decision": "approve", "response": response, "reason": "Candidate"}):
                with self.assertRaisesRegex(RuntimeError, "unavailable Chrome control"):
                    ai_decision.select_browser_control("terms", [{"name": "Agreement"}])

    def test_empty_candidate_list_does_not_start_ai(self):
        with patch.object(ai_decision, "start") as start:
            self.assertIsNone(ai_decision.select_browser_control("password", []))
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
