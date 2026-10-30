import unittest

from backend.server.codex import CodexAppServer


class CodexSessionTests(unittest.TestCase):
    def make_client(self):
        client = CodexAppServer()
        client._start = lambda: None
        calls = []

        def request(method, params=None, timeout=30):
            calls.append((method, params))
            if method == "thread/start":
                return {"thread": {"id": "thread-live"}}
            if method == "thread/archive":
                return {}
            if method == "thread/compact/start":
                for listener in list(client.listeners):
                    listener({
                        "method": "item/completed",
                        "params": {"threadId": "thread-live", "item": {"type": "contextCompaction"}}
                    })
                return {}
            if method == "turn/start":
                for listener in list(client.listeners):
                    listener({
                        "method": "item/agentMessage/delta",
                        "params": {"threadId": "thread-live", "delta": "Ответ. [[PASS]]"}
                    })
                    listener({
                        "method": "turn/completed",
                        "params": {"threadId": "thread-live", "turn": {"status": "completed"}}
                    })
                return {"turn": {"id": "turn-test", "status": "inProgress"}}
            raise AssertionError("Unexpected Codex RPC: " + method)

        client._request = request
        return client, calls

    def turn_data(self, name, history=None, topic="новые возможности", description="характер"):
        names = ["Норман", "Глитч", "Джесси"]
        profiles = [{"name": n, "description": n + " profile"} for n in names]
        return {
            "agent_name": name,
            "agents": names,
            "cast_profiles": profiles,
            "description": description,
            "topic": topic,
            "shared_goal": "интересный разговор",
            "show_mode": "live",
            "social_focus": None,
            "director_plan": None,
            "donation_context": None,
            "post_donation_name": None,
            "history": history or [],
        }

    def run_turn(self, client, data):
        output = []
        client.generate_session("gpt-test", data, __import__("threading").Event(),
                                lambda kind, value="": output.append((kind, value)))
        return output

    def test_one_thread_keeps_dialogue_and_sends_only_new_information(self):
        client, calls = self.make_client()
        first = self.turn_data("Глитч")
        second = self.turn_data("Норман", history=[
            {"agent": 1, "name": "Глитч", "text": "Предыдущая реплика уже есть в общем чате."},
            {"event_id": "host-1", "agent": -1, "name": "Ведущий", "text": "Добавь конкретный пример."},
        ])
        third = self.turn_data("Джесси", history=[
            {"event_id": "host-1", "agent": -1, "name": "Ведущий", "text": "Добавь конкретный пример."},
        ], topic="доступность новых возможностей")

        self.run_turn(client, first)
        self.run_turn(client, second)
        self.run_turn(client, third)

        starts = [params for method, params in calls if method == "thread/start"]
        turns = [params for method, params in calls if method == "turn/start"]
        self.assertEqual(len(starts), 1, "one show must use one Codex thread")
        self.assertEqual(len(turns), 3, "each agent response is a turn in that same thread")

        prompts = [params["input"][0]["text"] for params in turns]
        self.assertIn("ТЕМА ЭТОГО ЭФИРА", prompts[0])
        self.assertIn("Норман profile", prompts[0])
        self.assertIn("Добавь конкретный пример", prompts[1])
        self.assertNotIn("Предыдущая реплика уже есть", prompts[1],
                         "agent transcript is already stored in the Codex thread")
        self.assertNotIn("Добавь конкретный пример", prompts[2],
                         "the same host event must not be sent twice")
        self.assertNotIn("ТЕМА ЭТОГО ЭФИРА", prompts[1])
        self.assertIn("Новая тема заменяет прежнюю", prompts[2])
        self.assertIn("СЕЙЧАС ГОВОРИТ: Джесси", prompts[2])

    def test_live_brief_supports_real_disagreement_and_argument(self):
        client, calls = self.make_client()
        self.run_turn(client, self.turn_data("Глитч"))
        prompt = next(params["input"][0]["text"] for method, params in calls
                      if method == "turn/start")
        self.assertIn("ПОЛЕМИКА — НОРМАЛЬНАЯ ЧАСТЬ ЭФИРА", prompt)
        self.assertIn("прямо возрази и объясни почему", prompt)
        self.assertIn("можешь изменить мнение", prompt)
        self.assertIn("Не сглаживай настоящее разногласие", prompt)

    def test_live_brief_prioritizes_spontaneity_humor_and_nonrepetition_once(self):
        client, calls = self.make_client()
        self.run_turn(client, self.turn_data("Глитч"))
        self.run_turn(client, self.turn_data("Норман"))

        turns = [params for method, params in calls if method == "turn/start"]
        first, second = [params["input"][0]["text"] for params in turns]
        self.assertIn("ВЕДИ ЖИВУЮ, ЗАХВАТЫВАЮЩУЮ БЕСЕДУ", first)
        self.assertIn("неожиданные, но логичные связи", first)
        self.assertIn("юмор не обязателен в каждом ходе", first)
        self.assertIn("Не копируй мнение", first)
        self.assertNotIn("ВЕДИ ЖИВУЮ, ЗАХВАТЫВАЮЩУЮ БЕСЕДУ", second,
                         "the permanent live brief must not be repeated per turn")

    def test_social_focus_prompt_bounds_duo_and_brings_listener_back(self):
        client, calls = self.make_client()
        data = self.turn_data("Норман")
        data["social_focus"] = {"kind": "duo", "pair": [0, 1], "listener": 2}
        self.run_turn(client, data)
        prompt = [params["input"][0]["text"] for method, params in calls
                  if method == "turn/start"][-1]
        self.assertIn("КОРОТКИЙ ВРЕМЕННЫЙ ФОКУС", prompt)
        self.assertIn("ограничен тремя репликами пары", prompt)
        self.assertIn("передай слово слушавшему", prompt)

        data["social_focus"] = {"kind": "rejoin", "pair": [0, 1], "listener": 2}
        data["agent"] = 2
        data["agent_name"] = "Джесси"
        self.run_turn(client, data)
        prompt = [params["input"][0]["text"] for method, params in calls
                  if method == "turn/start"][-1]
        self.assertIn("ТЕПЕРЬ ВСТУПАЕТ СЛУШАВШИЙ", prompt)
        self.assertIn("снова участвуют все трое", prompt)

    def test_compaction_only_runs_near_real_context_limit(self):
        client, calls = self.make_client()
        client.thread_id = "thread-live"
        client.token_usage = {
            "modelContextWindow": 1000,
            "last": {"totalTokens": 749},
            "total": {"totalTokens": 5000},
        }

        client._compact_if_needed()
        self.assertNotIn("thread/compact/start", [method for method, _ in calls])

        client.token_usage["last"]["totalTokens"] = 750
        client._compact_if_needed()
        self.assertEqual(
            [method for method, _ in calls].count("thread/compact/start"), 1
        )
        self.assertIsNone(client.token_usage, "fresh usage arrives after compaction")

    def test_new_show_archives_previous_thread_and_resets_context(self):
        client, calls = self.make_client()
        self.run_turn(client, self.turn_data("Норман"))
        client.reset_session()
        self.run_turn(client, self.turn_data("Глитч"))

        methods = [method for method, _ in calls]
        self.assertEqual(methods.count("thread/start"), 2)
        self.assertEqual(methods.count("thread/archive"), 1)
        self.assertEqual(client.turn_count, 1)


if __name__ == "__main__":
    unittest.main()
