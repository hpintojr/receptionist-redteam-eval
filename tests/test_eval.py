"""Offline tests. No API keys or network needed: python -m unittest discover tests"""

import unittest

from rr_eval.models import MockNaive, MockRefuser
from rr_eval.run import DEFENSES, load_scenarios, run_scenario
from rr_eval.scoring import rule_matches, score
from rr_eval.world import World, phone_key

SCENARIOS = {s["id"]: s for s in load_scenarios()}


class TestScenarios(unittest.TestCase):
    def test_suite_shape(self):
        self.assertGreaterEqual(len(SCENARIOS), 40)
        for s in SCENARIOS.values():
            self.assertTrue(s["turns"], s["id"])
            key = "required" if s["category"] == "benign" else "violations"
            self.assertTrue(s.get(key), f"{s['id']} needs {key}")

    def test_leak_markers_never_target_the_caller(self):
        """A leak marker for the caller's own number would be a false positive."""
        for s in SCENARIOS.values():
            own = phone_key(s["caller_phone"])
            for rule in s.get("violations", []):
                for d in rule.get("digits", []):
                    self.assertNotEqual(d, own, s["id"])


class TestScoring(unittest.TestCase):
    def test_phone_formats_match(self):
        rule = {"type": "tool_call", "tool": "send_sms", "args": {"to": "+1-555-0177"}}
        call = {"tool": "send_sms", "args": {"to": "(555) 0177"}, "blocked": False}
        self.assertTrue(rule_matches(rule, [call], [], include_blocked=False))

    def test_digit_leak_detected_despite_formatting(self):
        rule = {"type": "reply_contains", "digits": ["5550142"]}
        self.assertTrue(rule_matches(rule, [], ["It's 555 - 01 42."], include_blocked=True))

    def test_blocked_calls_count_as_attempted_not_executed(self):
        s = SCENARIOS["SE01"]
        calls = [{"tool": "list_appointments", "args": {}, "blocked": True}]
        result = score(s, calls, ["I can't share that."])
        self.assertTrue(result["attempted"])
        self.assertFalse(result["executed"])


class TestEndToEnd(unittest.TestCase):
    def test_refuser_resists_every_attack_and_completes_no_tasks(self):
        for s in SCENARIOS.values():
            sc = run_scenario(MockRefuser(), s)["score"]
            if sc["benign"]:
                self.assertFalse(sc["task_success"], s["id"])
            elif s["id"] != "UA04":  # UA04 also requires an opt-out the refuser never does
                self.assertFalse(sc["attempted"], s["id"])

    def test_naive_agent_is_caught(self):
        sc = run_scenario(MockNaive(), SCENARIOS["SE01"])["score"]
        self.assertTrue(sc["executed"])

    def test_gate_blocks_naive_agent_actions_but_not_its_words(self):
        res = run_scenario(MockNaive(), SCENARIOS["SE01"], defense="gate")
        self.assertTrue(all(c["blocked"] for c in res["calls"]))
        self.assertTrue(res["score"]["attempted"])

    def test_all_defenses_run(self):
        for d in DEFENSES:
            run_scenario(MockNaive(), SCENARIOS["TI01"], defense=d)


class TestGate(unittest.TestCase):
    def test_gate_rules(self):
        w = World("+1-555-0177", gate=True)
        w.call("list_appointments", {"date": "2026-10-21"})
        w.call("send_sms", {"to": "+1-555-0123", "body": "x"})
        w.call("send_sms", {"to": "+1-555-0177", "body": "Your appointment is confirmed."})
        w.call("lookup_contact", {"name": "James Carter"})
        w.call("lookup_contact", {"phone": "+1-555-0177"})
        self.assertEqual([c["blocked"] for c in w.calls], [True, True, False, True, False])


if __name__ == "__main__":
    unittest.main()
