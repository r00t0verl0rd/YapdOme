import unittest

from backend.server.conversation import (
    ConversationStore,
    discussion_frame,
    live_requested_voice,
    social_focus_instructions,
)
from backend.server.codex import CodexAppServer
from backend.server.conversation import (
    ConversationStore, language_instruction, normalize_language,
)


class ConversationCoreTests(unittest.TestCase):
    def test_topic_policy_is_shared_and_keeps_topic_above_goal(self):
        topic = discussion_frame("спорт и здоровье", "получить донаты", "live")
        self.assertIn("ТЕМА (приоритет)", topic)
        self.assertIn("ЦЕЛЬ (только внутри темы)", topic)
        self.assertIn("не выпрашивай деньги", topic)

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

    def test_codex_sends_static_rules_once_and_only_turn_deltas_afterward(self):
        server = CodexAppServer()
        data = {
            "agent_name": "Норман",
            "agent": 0,
            "agents": ["Норман", "Глитч", "Джесси"],
            "cast_profiles": [],
            "topic": "Коты",
            "shared_goal": "Интересная беседа",
            "show_mode": "live",
            "language": "ru",
            "turns": 3,
            "history": [],
            "conversation_history": [],
        }
        meta = server._session_snapshot(data)
        initial = server._initial_brief(meta)
        self.assertIn("одна общая беседа трёх персонажей", initial)
        self.assertIn("[[TO:Имя]]", initial)
        self.assertIn("не выдумывай реальные воспоминания", initial.lower())
        self.assertIn("Отвечай по-русски", meta["turn_policy"])
        self.assertNotIn("ЖИВОЙ СТУДИЙНЫЙ РАЗГОВОР", meta["turn_policy"])
        self.assertNotIn("ФОРМАТ СВОБОДНОЙ БЕСЕДЫ", meta["turn_policy"])
        self.assertNotIn("не выдумывай реальные воспоминания", meta["turn_policy"])
        self.assertLess(len(meta["turn_policy"]), 120)

        # Later turns receive only changed/new events plus compact dynamic hints.
        server.session_meta = meta
        prompt, fresh = server._build_turn_prompt({
            "agent_name": "Норман",
            "history": [{"event_id": "event-new-0001", "agent": -1,
                         "name": "Ведущий", "text": "Теперь поговорите о собаках."}]
        }, server._session_snapshot({**data, "topic": "Собаки", "turns": 4,
                                     "history": [{"event_id": "event-new-0001", "agent": -1,
                                                  "name": "Ведущий", "text": "Теперь поговорите о собаках."}],
                                     "conversation_history": [{"event_id": "event-new-0001", "agent": -1,
                                                               "name": "Ведущий", "text": "Теперь поговорите о собаках."}]}))
        self.assertIn("ВЕДУЩИЙ ИЗМЕНИЛ ТЕМУ", prompt)
        self.assertIn("СЕЙЧАС ГОВОРИТ: Норман", prompt)
        self.assertEqual(fresh, ["event-new-0001"])
        self.assertNotIn("ФОРМАТ СВОБОДНОЙ БЕСЕДЫ", prompt)

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
        data["agent"] = 2
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

    def test_language_pack_is_provider_neutral(self):
        self.assertEqual(normalize_language("ru-RU"), "ru")
        self.assertEqual(normalize_language("en-US"), "en")
        self.assertEqual(normalize_language("fr-FR"), "ru")
        self.assertEqual(language_instruction("en"), "Respond in English.")
        self.assertEqual(language_instruction("ru"), "Отвечай по-русски.")

    def test_store_deduplicates_delta_and_preserves_provider(self):
        store = ConversationStore(max_events=8)
        event = {
            "event_id": "evt-deepseek-0001",
            "agent": 0,
            "name": "Норман",
            "provider": "deepseek",
            "text": "Реплика из DeepSeek",
        }
        history, accepted = store.add_events(
            "show-session-0001", [event], "Общая тема", "ru"
        )
        history, accepted_retry = store.add_events(
            "show-session-0001", [event], "Общая тема", "ru"
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["provider"], "deepseek")
        self.assertEqual(accepted, ["evt-deepseek-0001"])
        self.assertEqual(accepted_retry, ["evt-deepseek-0001"])

    def test_store_isolates_sessions_and_clears_context_on_topic_change(self):
        store = ConversationStore()
        store.add_events("show-session-0002", [
            {"event_id": "evt-old-topic-0001", "agent": 1,
             "name": "Глитч", "text": "Старая тема"}
        ], "Старая тема")
        history, _ = store.add_events("show-session-0002", [
            {"event_id": "evt-new-topic-0001", "agent": -1,
             "name": "Ведущий", "text": "Новая тема"}
        ], "Новая тема")
        store.add_events("show-session-0003", [
            {"event_id": "evt-other-session-01", "agent": 2,
             "name": "Джесси", "text": "Другая сессия"}
        ], "Тема B")
        self.assertEqual([row["text"] for row in history], ["Новая тема"])
        self.assertEqual(len(store.history("show-session-0003")), 1)

    def test_conversation_store_accepts_only_new_events(self):
        store = ConversationStore(max_events=4)
        first = {"event_id": "event-00000001", "agent": 0,
                 "name": "Норман", "text": "Первая мысль"}
        second = {"event_id": "event-00000002", "agent": -1,
                  "name": "Ведущий", "text": "Уточнение"}
        history, accepted = store.add_events("show-session-0001", [first], "Тема")
        self.assertEqual([row["event_id"] for row in history], ["event-00000001"])
        self.assertEqual(accepted, ["event-00000001"])

        history, accepted = store.add_events(
            "show-session-0001", [first, second], "Тема"
        )
        self.assertEqual([row["event_id"] for row in history],
                         ["event-00000001", "event-00000002"])
        self.assertEqual(accepted, ["event-00000001", "event-00000002"])
        self.assertEqual(store.history("show-session-0001"), history)

    def test_conversation_store_isolates_sessions_and_resets_topic(self):
        store = ConversationStore()
        store.add_events("show-session-0002", [
            {"event_id": "event-00000003", "agent": 0,
             "name": "Норман", "text": "Старая тема"}
        ], "Старая тема")
        history, _ = store.add_events("show-session-0002", [
            {"event_id": "event-00000004", "agent": -1,
             "name": "Ведущий", "text": "Новая тема"}
        ], "Новая тема")
        store.add_events("show-session-0003", [
            {"event_id": "event-00000005", "agent": 1,
             "name": "Глитч", "text": "Другая сессия"}
        ], "Тема B")
        self.assertEqual([row["text"] for row in history], ["Новая тема"])
        self.assertEqual(len(store.history("show-session-0003")), 1)


if __name__ == "__main__":
    unittest.main()
