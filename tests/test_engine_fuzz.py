"""Сид-рандомизированный стресс движка.

Отклонённые события не меняют снимок, инварианты держатся после каждого
события, кольцо аудита ограничено и строго последовательно. Также проверены
границы счётчиков поколений и лимита ходов.
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.engine import Engine
from backend.engine import enums as E

ACTIONS = ["start", "claim", "complete", "user", "pause", "resume", "stop",
           "interrupt", "reset", "fail", "tick",
           "recover", "director", "priority_donation", "social"]
SAMPLES = ["", "[[PASS]]", "[[WAIT_USER]]", "Хм.", "[[TO:SELF]]", "[[TO:ANY]]",
           "Экспериментатор, ответь", "Он сказал «Экспериментатор, ответь»",
           "[[TO:я]]"]


def assert_invariants(test, core):
    s = core.state()
    test.assertIn(s["status"], E.MODES)
    test.assertNotEqual(s["status"], "WAIT_USER")
    test.assertIn(s["agent"], (-1, 0, 1, 2))
    test.assertIn(s["next_agent"], (0, 1, 2))
    test.assertTrue(s["agent"] < 0 or s["status"] == "RUNNING")
    test.assertTrue(0 <= s["passes"] <= 3)
    test.assertTrue(s["turns"] >= 0 and 0 <= s["errors"] <= 3)
    test.assertIn(s["kind"], E.KINDS)
    test.assertIn(s["route_reason"], E.ROUTE_REASONS.values())


class EngineFuzz(unittest.TestCase):
    def test_seeded_random_events_keep_invariants(self):
        rng = random.Random(0x54524941)
        for run in range(400):
            core = Engine()
            try:
                core.names(["Лимур", "Кизаро", "Овелито"])
                core.event("start", max_turns=0)
                for _ in range(250):
                    action = rng.choice(ACTIONS)
                    agent = rng.randint(-1, 2)
                    ticket = core.state()["ticket"] if rng.random() < .7 else 0
                    text = SAMPLES[rng.randrange(len(SAMPLES))] if rng.random() < .6 else ""
                    before = core.state()
                    after = core.event(action, agent=agent, ticket=ticket,
                                       max_turns=rng.choice((0, 1, 2, 24)),
                                       auto_interrupt=rng.random() < .5, text=text)
                    if not after["accepted"]:
                        for snap in (before, after):
                            snap["result"] = 0
                            snap["accepted"] = True
                            snap["timeout_ms"] = 0
                        self.assertEqual(after, before, (run, action, agent))
                    assert_invariants(self, core)
            finally:
                core.close()

    def test_audit_is_bounded_and_sequential(self):
        core = Engine()
        try:
            for _ in range(150):
                core.event("tick")
            entries = core.audit()
            self.assertEqual(len(entries), 128)
            for previous, current in zip(entries, entries[1:]):
                self.assertEqual(current["sequence"], previous["sequence"] + 1)
        finally:
            core.close()

    def test_counter_boundaries_fail_closed(self):
        # turns на пределе INT_MAX-2 переводит claim в LIMIT, а не в overflow.
        core = Engine()
        try:
            core.event("start")
            core._engine.turns = E.INT_MAX - 2
            self.assertEqual(core.event("claim")["status"], "LIMIT")
        finally:
            core.close()
        # UINT_MAX ticket: движок отказывает закрытым способом.
        core = Engine()
        try:
            core.event("start")
            core._engine.ticket = E.UINT_MAX - 1
            claimed = core.event("claim")
            self.assertEqual(claimed["ticket"], E.UINT_MAX)
            self.assertEqual(core.event("complete", agent=claimed["agent"],
                                        ticket=claimed["ticket"], text="hello")["status"], "ERROR")
            self.assertFalse(core.event("start")["accepted"])
        finally:
            core.close()


if __name__ == "__main__":
    unittest.main()
