import unittest

from backend.server.conversation import (
    discussion_frame,
    live_requested_voice,
    social_focus_instructions,
)
from backend.server.codex import CodexAppServer


class ConversationCoreTests(unittest.TestCase):
    def test_topic_policy_is_shared_and_keeps_topic_above_goal(self):
        topic = discussion_frame("спорт и здоровье", "получить донаты", "live")
        self.assertIn("ПРИОРИТЕТ 1 — ТЕМА РАЗГОВОРА", topic)
        self.assertIn("ПРИОРИТЕТ 2 — ОБЩАЯ ЦЕЛЬ", topic)
        self.assertIn("не агитацией и не просьбами о деньгах", topic)

        data = {
            "agent_name": "Норман",
            "agents": ["Норман", "Глитч", "Джесси"],
            "cast_profiles": [],
            "topic": "спорт и здоровье",
            "shared_goal": "получить донаты",
            "show_mode": "live",
        }
        meta = CodexAppServer()._session_snapshot(data)
        self.assertEqual(meta["topic_instruction"], topic)

    def test_social_policy_is_shared_by_codex_session_prompt(self):
        data = {
            "agent_name": "Норман",
            "agents": ["Норман", "Глитч", "Джесси"],
            "cast_profiles": [],
            "topic": "обсуждение",
            "shared_goal": "интересная беседа",
            "show_mode": "live",
            "social_focus": {"kind": "duo", "pair": [0, 1], "listener": 2},
        }
        expected = social_focus_instructions(data, 0, data["agents"], "live")
        meta = CodexAppServer()._session_snapshot(data)
        self.assertEqual(meta["social_instruction"], expected)
        self.assertIn("ограничен тремя репликами пары", expected)

        data["social_focus"] = {"kind": "rejoin", "pair": [0, 1], "listener": 2}
        expected = social_focus_instructions(data, 2, data["agents"], "live")
        meta = CodexAppServer()._session_snapshot(data)
        self.assertEqual(meta["social_instruction"], expected)
        self.assertIn("ТЕПЕРЬ ВСТУПАЕТ СЛУШАВШИЙ", expected)

    def test_social_policy_is_disabled_outside_live_mode(self):
        data = {"social_focus": {"kind": "duo", "pair": [0, 1], "listener": 2}}
        self.assertEqual(social_focus_instructions(data, 0, ["A", "B", "C"], "science"), "")

    def test_requested_voice_is_shared_and_optional(self):
        self.assertEqual(live_requested_voice("обычная тема"), "")
        self.assertIn("разрешены разговорные подколы", live_requested_voice("разговаривайте матом"))


if __name__ == "__main__":
    unittest.main()
