"""Очередь донатов и приоритеты ядра (офлайн и детерминированно)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.server.http_server import Handler
from backend.controls.host import agent_identity
from backend.controls.donations import donation_context, donation_scene_instructions
from backend.server.llm import BridgeError
from backend.engine import Engine
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class RequestBoundary(Exception):
    pass


class DonationTests(unittest.TestCase):
    def test_all_valid_amounts_are_accepted_as_untrusted_data(self):
        for amount in (0, 0.99, 1, 5, 20, 50, 100, 1000000):
            item=donation_context({"donation_context":{
                "name":"Зритель","amount":amount,"text":"Привет, ребята!",
                "first":True,"remaining":1}})
            self.assertEqual(item["amount"],amount)
            self.assertEqual(item["name"],"Зритель")
        self.assertIsNone(donation_context({}))

    def test_malformed_donations_rejected(self):
        for invalid in ({"amount":-1},{"amount":"100"},{"amount":float("inf")},
                        {"remaining":99},{"first":"true"},{"text":""},
                        {"name":"X"*80}):
            data={"name":"Имя","amount":5,"text":"Привет",
                  "first":True,"remaining":2}
            data.update(invalid)
            with self.assertRaises(BridgeError):
                donation_context({"donation_context":data})

    def test_one_behavior_field_and_migration(self):
        self.assertEqual(agent_identity({"agent_name":"Лимур",
            "description":"Хитрый и весёлый шутник."}),
            ("Лимур","Хитрый и весёлый шутник."))
        self.assertEqual(agent_identity({"agent_name":"Лимур",
            "role":"Весёлый","goal":"Смешить зрителей"}),
            ("Лимур","Весёлый Смешить зрителей"))

    def test_real_stream_request_is_constructible_with_donation(self):
        info={
          "request_id":"donation_request_123",
          "agent":2,"agent_name":"Овелито","agents":["Лимур","Кизаро","Овелито"],
          "description":"Творческий, необычный, любит музыку",
          "model":"test-model","topic":"Разговор об искусстве",
          "shared_goal":"содержательная беседа","turns":13,"journal":[],"history":[],
          "donation_context":{"name":"Даша","text":"А какую песню любите?",
                              "amount":50,"remaining":5,"first":True}
        }
        with patch("backend.server.http_server.register_call",side_effect=RequestBoundary):
            with self.assertRaises(RequestBoundary):
                Handler.stream(object(),info)

    def test_donation_cannot_preempt_speaking_turn(self):
        engine=Engine()
        try:
            engine.names(["Лимур","Кизаро","Овелито"])
            engine.event("start",max_turns=0)
            turn=engine.event("claim")
            self.assertEqual(turn["agent"],0)
            urgent=engine.event("priority_donation",agent=2)
            self.assertFalse(urgent["accepted"])
            self.assertEqual(urgent["agent"],0)
            done=engine.event("complete",agent=0,ticket=turn["ticket"],
                              text="Я закончил мысль, теперь слово донату.")
            self.assertTrue(done["accepted"])
            urgent=engine.event("priority_donation",agent=2)
            self.assertTrue(urgent["accepted"])
            self.assertEqual(urgent["route_reason"],"donation")
            self.assertEqual(engine.event("claim")["agent"],2)
        finally:
            engine.close()

    def test_operator_pause_and_stop_override_donation(self):
        engine=Engine()
        try:
            engine.event("start",max_turns=0)
            engine.event("pause")
            result=engine.event("priority_donation",agent=1)
            self.assertFalse(result["accepted"])
            engine.event("stop")
            self.assertFalse(engine.event("priority_donation",agent=0)["accepted"])
        finally:
            engine.close()

    def test_no_separate_donation_moderator_call_in_client(self):
        js=(ROOT/"frontend/client.js").read_text()
        self.assertNotIn("reviewDonation(d)",js)
        self.assertIn("priority_donation",js)
        self.assertIn("donationQueue",js)
        self.assertIn("donation_context",js)

    def test_donation_scene_progresses_not_repeats_thanks(self):
        donation={"name":"Клоп","amount":50,"text":"Здарова пацаны",
                  "first":True,"remaining":1,"total":1,"covered":[]}
        first=donation_scene_instructions(donation,"Лимур","Добрый шутник",
                                           ["Лимур","Кизаро","Овелито"],"Будущее")
        self.assertIn("ПЕРВЫЙ ОТВЕТ",first)
        self.assertIn("УЖЕ добавляет начало",first)
        donation.update(first=False,remaining=1,total=2,covered=["Привет, рады видеть!"])
        second=donation_scene_instructions(donation,"Кизаро","Скептик",
                                           ["Лимур","Кизаро","Овелито"],"Будущее")
        self.assertIn("РАЗВИТИЕ",second)
        self.assertIn("НЕ повторяй имя",second)
        self.assertNotIn("ПЕРВЫЙ ОТВЕТ",second)

    def test_extra_donation_history_is_bounded(self):
        base={"name":"Даша","text":"Объясни проект","amount":100,
              "first":False,"remaining":3,"total":8,"covered":["Первый аргумент"]}
        self.assertEqual(donation_context({"donation_context":base})["covered"],
                         ["Первый аргумент"])
        base["covered"]=["реплика"]*9
        with self.assertRaises(BridgeError):
            donation_context({"donation_context":base})

    def test_compact_three_field_composer_exists(self):
        html=(ROOT/"frontend/index.html").read_text()
        for ident in ("donationAmount","donor","donationText","sendDonation"):
            self.assertEqual(html.count('id="'+ident+'"'),1,ident)
        self.assertIn('id="voiceSettings"',html)
        app=(ROOT/"frontend/client.js").read_text()
        self.assertNotIn("agent-advanced",app)
        self.assertNotIn("voice-tuning",app)
        self.assertIn("ХАРАКТЕР / ПОВЕДЕНИЕ",app)


if __name__=="__main__":
    unittest.main()
