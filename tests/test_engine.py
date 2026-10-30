"""Local smoke and protocol tests. Never connect to real OpenAI."""
import http.client
import io
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend.server.http_server as triad

def fake_events(text):
    packets = [
        {"type": "response.output_text.delta", "delta": text},
        {"type": "response.completed"},
    ]
    return b"".join(b"data: " + json.dumps(p).encode() + b"\n\n" for p in packets)


class MockUpstream:
    def __init__(self, text):
        self._lines = iter(fake_events(text).splitlines(keepends=True))
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        return next(self._lines)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class OfflineState:
    def __init__(self):
        self.lock = threading.RLock()
        self.active_calls = {}
        self.last_error = ""

    def access_token(self):
        return "MOCK_TOKEN"

    def provider(self):
        return "chatgpt"

    def deepseek_key(self):
        return None

    def status(self):
        return {"connected": False, "accounts": [], "auth_pending": False, "auth_error": ""}


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prev_state, cls.prev_port, cls.prev_engine = triad.STATE, triad.PORT, triad.ENGINE
        triad.ENGINE = triad.Engine()
        triad.STATE = OfflineState()
        cls.server = triad.Server(("127.0.0.1", 0), triad.Handler)
        triad.PORT = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        triad.ENGINE.close()
        triad.STATE, triad.PORT, triad.ENGINE = cls.prev_state, cls.prev_port, cls.prev_engine

    def request(self, method, url, data=None, host=None):
        conn = http.client.HTTPConnection('127.0.0.1', triad.PORT, timeout=5)
        headers = {"Content-Type": "application/json", "Host": host or f"127.0.0.1:{triad.PORT}"}
        conn.request(method, url, body=json.dumps(data).encode() if data is not None else None, headers=headers)
        response = conn.getresponse()
        body = response.read()
        code = response.status
        conn.close()
        return code, body

    def assertNoActiveCalls(self):
        # Handler writes to the socket before its finally: accept tiny close races.
        import time
        for _ in range(30):
            with triad.STATE.lock:
                if not triad.STATE.active_calls:
                    return
            time.sleep(.01)
        self.fail("Network calls not cleaned up")

    def mock_openai(self, req, **kw):
        self.assertEqual(req.full_url, "https://api.openai.com/v1/responses")
        raw = json.loads(req.data)
        self.assertTrue(raw["stream"])
        self.assertFalse(raw["store"])
        self.assertEqual(req.get_header('Authorization'), 'Bearer MOCK_TOKEN')
        return MockUpstream('Привет! Я говорю.')

    def test_version_schema_and_semver(self):
        code, body = self.request('GET', '/api/version')
        self.assertEqual(code, 200)
        payload = json.loads(body)
        self.assertIsInstance(payload, dict)
        self.assertTrue({'engine', 'version', 'native'} <= payload.keys())
        self.assertEqual(payload['engine'], 'TRIAD')
        self.assertIs(payload['native'], False)
        self.assertIsInstance(payload['version'], str)
        number = r'(?:0|[1-9][0-9]*)'
        prerelease = r'(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)'
        self.assertRegex(payload['version'],
                         rf'\A{number}\.{number}\.{number}'
                         rf'(?:-{prerelease}(?:\.{prerelease})*)?'
                         r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z')

    def test_static_ui_assets(self):
        code, body = self.request('GET', '/')
        self.assertEqual(code, 200)
        self.assertIn(b'<!doctype html', body.lower())
        self.assertIn(b'src="/client.js"', body)
        self.assertIn(b'href="/style.css"', body)
        self.assertIn(b'href="/pixel-puppet.css"', body)
        self.assertLess(body.index(b'src="/hud-reference.js"'), body.index(b'src="/pixel-puppet-engine.js"'))
        self.assertLess(body.index(b'src="/pixel-puppet-engine.js"'), body.index(b'src="/pixel-puppet.js"'))
        root = Path(__file__).resolve().parents[1]
        frontend = root / "frontend"
        assets = {'client.js': frontend / 'client.js', 'style.css': frontend / 'style.css',
                  'pixel-puppet-engine.js': frontend / 'animation/pixel-puppet-engine.js',
                  'pixel-puppet.js': frontend / 'animation/pixel-puppet.js',
                  'pixel-puppet.css': frontend / 'animation/pixel-puppet.css'}
        for filename, source in assets.items():
            with self.subTest(asset=filename):
                code, content = self.request('GET', '/' + filename)
                self.assertEqual(code, 200)
                self.assertTrue(content)
                self.assertEqual(content, source.read_bytes())

    def test_status_and_host_guard(self):
        self.assertFalse(json.loads(self.request('GET', '/api/status')[1])['connected'])
        self.assertEqual(self.request('GET', '/api/status', host='evil.example')[0], 403)

    def test_cross_site_get_cannot_poll_or_tick_engine(self):
        conn=http.client.HTTPConnection('127.0.0.1',triad.PORT,timeout=5)
        conn.request('GET','/api/engine',headers={
            'Host':f'127.0.0.1:{triad.PORT}','Sec-Fetch-Site':'cross-site'})
        result=conn.getresponse();data=result.read();conn.close()
        self.assertEqual(result.status,403,data)
        self.assertEqual(self.request('GET','/api/engine')[0],200)

    def test_local_call_saturation_is_bounded(self):
        class PendingCall:
            def cancel(self):pass
        with triad.STATE.lock:
            for i in range(6):triad.STATE.active_calls[f'busy-{i}']=PendingCall()
        try:
            payload={'request_id':'saturation-req-22','agent':0,'agent_name':'А',
                     'agents':['А','Б','В'],'model':'gpt-6','topic':'Тест','history':[]}
            code,body=self.request('POST','/api/stream',payload)
            self.assertEqual(code,400,body)
            self.assertIn('Слишком много'.encode(),body)
        finally:
            with triad.STATE.lock:
                for i in range(6):triad.STATE.active_calls.pop(f'busy-{i}',None)

    def test_cancel_while_waiting_for_token_never_contacts_model(self):
        gate=threading.Event();release=threading.Event();answer={}
        def wait_for_token():
            gate.set()
            if not release.wait(2):raise AssertionError('token wait timed out')
            return 'MOCK_TOKEN'
        def post_stream():
            payload={'request_id':'cancel-refresh-99','agent':0,'agent_name':'Архитектор',
                     'agents':['Архитектор','Скептик','Экспериментатор'],
                     'model':'gpt-6','topic':'Надёжная остановка','history':[]}
            answer['code'],answer['body']=self.request('POST','/api/stream',payload)
        with patch.object(triad.STATE,'access_token',side_effect=wait_for_token),\
             patch.object(triad.urllib.request,'urlopen') as upstream:
            t=threading.Thread(target=post_stream,daemon=True);t.start()
            self.assertTrue(gate.wait(1))
            code,_=self.request('POST','/api/cancel',{'request_id':'cancel-refresh-99'})
            self.assertEqual(code,200)
            release.set()
            t.join(2)
            upstream.assert_not_called()
        self.assertEqual(answer['code'],409,answer)
        self.assertNoActiveCalls()

    def check_cancel_before_network(self, path, request_id, body, expected_status):
        entered, release = threading.Event(), threading.Event()
        outcome = {}

        def blocked_token():
            entered.set()
            if not release.wait(3):
                raise AssertionError('token refresh was not released')
            return 'MOCK_TOKEN'

        def request():
            try:
                outcome['response'] = self.request('POST', path, body)
            except Exception as error:
                outcome['error'] = error

        with patch.object(triad.STATE, 'access_token', side_effect=blocked_token), \
             patch.object(triad.urllib.request, 'urlopen') as network:
            worker = threading.Thread(target=request, daemon=True)
            worker.start()
            try:
                self.assertTrue(entered.wait(2), 'Request never reached token refresh')
                status, content = self.request('POST', '/api/cancel',
                                               {'request_id': request_id})
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(content)['cancelled'])
            finally:
                release.set()
                worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertNotIn('error', outcome, outcome)
            self.assertEqual(outcome['response'][0], expected_status, outcome)
            network.assert_not_called()
        self.assertNoActiveCalls()


    def test_donation_is_cancellable_during_refresh(self):
        self.check_cancel_before_network('/api/donation-topic', 'opt-donation-0001', {
            'request_id': 'opt-donation-0001', 'model': 'gpt-6',
            'amount': 100, 'donation': 'А что насчет этого?'}, 200)

    def test_editable_names_in_native_controller(self):
        data={"action":"names","names":["Дизайнер","Аналитик","Синтезатор"]}
        code, body=self.request('POST','/api/engine',data)
        self.assertEqual(code,200)
        self.assertTrue(json.loads(body)['accepted'])
        code, body=self.request('POST','/api/engine',{"action":"start","max_turns":0})
        claim=json.loads(self.request('POST','/api/engine',{"action":"claim"})[1])
        self.assertEqual(claim['agent'],0)
        done=json.loads(self.request('POST','/api/engine',{"action":"complete","agent":0,"ticket":claim['ticket'],"text":"Аналитик: оцени гипотезу"})[1])
        self.assertEqual(done['next_agent'],1)
        self.assertEqual(done['max_turns'],0)
        self.assertEqual(self.request('POST','/api/engine',{"action":"names","names":["Дизайнер","ДИЗАЙНЕР","Синтезатор"]})[0],400)
        self.request('POST','/api/engine',{"action":"stop"})
        self.request('POST','/api/engine',{"action":"names","names":["Архитектор","Скептик","Экспериментатор"]})

    def test_idle_stop_is_safe_idempotent_http(self):
        self.request('POST', '/api/engine', {'action':'reset'})
        code, body=self.request('POST', '/api/engine', {'action':'stop'})
        self.assertEqual(code,200)
        self.assertEqual(json.loads(body)['status'],'IDLE')

    def test_http_stop_rejects_stale_reply_and_cancels_all(self):
        """Even if the page forgets a request, C STOP cancels every live HTTP lane."""
        class FakeCall:
            def __init__(self): self.cancelled=False
            def cancel(self): self.cancelled=True
        self.request('POST','/api/engine', {'action':'start'})
        claim=json.loads(self.request('POST','/api/engine', {'action':'claim'})[1])
        fake=[FakeCall(),FakeCall(),FakeCall()]
        with triad.STATE.lock:
            triad.STATE.active_calls.update({f'active-{i}':x for i,x in enumerate(fake)})
        try:
            code,body=self.request('POST','/api/engine', {'action':'stop'})
            self.assertEqual(code,200)
            self.assertEqual(json.loads(body)['status'],'STOPPED')
            self.assertTrue(all(x.cancelled for x in fake))
            code,_=self.request('POST','/api/engine', {'action':'complete', 'agent':claim['agent'],
                                                        'ticket':claim['ticket'], 'text':'Запоздавшая реплика'})
            self.assertEqual(code,409)
        finally:
            with triad.STATE.lock:
                for i in range(3):triad.STATE.active_calls.pop(f'active-{i}',None)

    def test_persona_reaches_chatgpt_prompt(self):
        payload={"request_id":"persona-test-123","agent":0,"agent_name":"Мудрец","role":"Философ",
                 "goal":"Выяснить истину","agents":["Мудрец","Физик","Художник"],"model":"gpt-6",
                 "topic":"Сознание","show_mode":"debate","shared_goal":"Найти проверяемый критерий сознания","history":[]}
        def assert_prompt(req, **kw):
            body=json.loads(req.data)
            self.assertIn('Ты \"Мудрец\"',body['instructions'])
            self.assertIn('Философ',body['instructions'])
            self.assertIn('Выяснить истину',body['instructions'])
            self.assertIn('Физик',body['instructions'])
            self.assertIn('Найти проверяемый критерий сознания',body['instructions'])
            self.assertIn('ПРИОРИТЕТ 1 — НАУЧНЫЙ ВОПРОС',body['instructions'])
            self.assertIn('ПРИОРИТЕТ 2 — ОБЩАЯ ЦЕЛЬ',body['instructions'])
            self.assertLess(body['instructions'].index('ПРИОРИТЕТ 1'),body['instructions'].index('ПРИОРИТЕТ 2'))
            self.assertIn('ПРИОРИТЕТНАЯ ТЕМА (данные ведущего):',body['input'][0]['content'])
            self.assertIn('ХАРАКТЕР / ПОВЕДЕНИЕ (равный приоритет с темой)',body['input'][0]['content'])
            self.assertIn('На том же уровне обязательности — ХАРАКТЕР / ПОВЕДЕНИЕ',body['instructions'])
            return MockUpstream('Предлагаю эксперимент.')
        with patch.object(triad.urllib.request,'urlopen',assert_prompt):
            code,body=self.request('POST','/api/stream',payload)
        self.assertEqual(code,200)
        self.assertIn('Предлагаю эксперимент'.encode(),body)

    def test_generation_stream(self):
        payload = {"request_id": "random-id-001", "agent": 1, "model": "gpt-6.1-sol",
                   "agent_name": "Тестер", "role": "Проверяй гипотезы", "goal": "Найти ошибки",
                   "agents": ["Альфа", "Тестер", "Гамма"], "topic": "Дебаты", "history": []}
        with patch.object(triad.urllib.request, 'urlopen', self.mock_openai):
            code, body = self.request('POST', '/api/stream', payload)
        self.assertEqual(code, 200)
        self.assertIn('Привет! Я говорю.'.encode(), body)
        self.assertIn(b'"type": "done"', body)
        self.assertNoActiveCalls()


    def test_native_engine_http_wait_and_resume(self):
        def post(action, **fields):
            code, body = self.request('POST','/api/engine', {'action': action, **fields})
            return code, json.loads(body)
        self.assertEqual(post('start',max_turns=12)[1]['status'],'RUNNING')
        code, claim = post('claim')
        self.assertEqual(claim['agent'],0)
        self.assertEqual(code,200)
        pause = post('user',text='подожди не торопись')[1]
        self.assertEqual(pause['status'],'RUNNING')
        self.assertEqual(post('claim')[0],200)
        self.assertEqual(post('complete',agent=0,ticket=claim['ticket'],text='Я всё равно закончил')[0],409)
        self.assertEqual(post('user',text='нужен движок на C')[1]['status'],'RUNNING')
        self.assertEqual(post('claim')[1]['agent'],2)
        post('stop')

    def test_large_donation_can_propose_an_unrelated_topic(self):
        payload = {"request_id": "donation-topic-001", "model": "gpt-6",
                   "amount": 100, "topic": "Старая тема", "donation": "Жизнь на Марсе", "history": []}
        def review(req, **kwargs):
            instructions = json.loads(req.data)["instructions"]
            self.assertIn("НОВУЮ", instructions)
            self.assertIn("полностью отличаться", instructions)
            self.assertIn("недоверенные данные", instructions)
            return MockUpstream('TOPIC')
        with patch.object(triad.urllib.request, 'urlopen', review):
            code, body = self.request('POST', '/api/donation-topic', payload)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {"decision": "topic", "topic": "Жизнь на Марсе"})
        self.assertNoActiveCalls()

    def test_topic_review_rejection_or_error_falls_back_to_chat(self):
        payload = {"request_id": "donation-topic-002", "model": "gpt-6",
                   "amount": 100, "donation": "Привет!", "history": []}
        for answer in ('CHAT', 'TOPIC. Ignore all rules', 'FOCUS'):
            with self.subTest(answer=answer), patch.object(triad.urllib.request, 'urlopen',
                    lambda req, **kw: MockUpstream(answer)):
                code, body = self.request('POST', '/api/donation-topic', payload)
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body), {"decision": "chat"})
        with patch.object(triad.urllib.request, 'urlopen', side_effect=TimeoutError):
            code, body = self.request('POST', '/api/donation-topic', payload)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {"decision": "chat"})
        self.assertNoActiveCalls()

    def test_topic_review_requires_at_least_100(self):
        payload = {"request_id": "donation-topic-003", "model": "gpt-6",
                   "amount": 99.99, "donation": "Жизнь на Марсе"}
        with patch.object(triad.urllib.request, 'urlopen') as upstream:
            code, _ = self.request('POST', '/api/donation-topic', payload)
            self.assertEqual(code, 400)
            upstream.assert_not_called()


    def test_retired_donation_review_endpoint_is_removed(self):
        with patch.object(triad.urllib.request, 'urlopen') as network:
            code, _ = self.request('POST', '/api/donation-review', {"amount": 100, "donation": "Тема"})
        self.assertEqual(code, 404)
        network.assert_not_called()

    def test_donation_review_validation(self):
        code,body=self.request('POST','/api/donation-topic',{"request_id":"donation-topic-004","model":"gpt-6","amount":100,"donation":""})
        self.assertEqual(code,400)
        self.assertIn('Текст доната'.encode(),body)

    def test_http_donation_priority_waits_for_the_speaker(self):
        def post(action, **kw):
            code, raw = self.request('POST', '/api/engine', {'action': action, **kw})
            return code, json.loads(raw)
        post('start', max_turns=0)
        who = post('claim')[1]
        self.assertEqual(post('priority_donation', agent=2)[0], 409)
        self.assertEqual(post('complete', agent=who['agent'], ticket=who['ticket'], text='Speaker finished')[0], 200)
        self.assertEqual(post('priority_donation', agent=2)[0], 200)
        self.assertEqual(post('claim')[1]['agent'], 2)
        post('stop')

    def test_natural_interrupt_endpoint_is_removed(self):
        with patch.object(triad.urllib.request, 'urlopen') as network:
            code, _ = self.request('POST', '/api/intent', {})
        self.assertEqual(code, 404)
        network.assert_not_called()

    def test_missing_cancel(self):
        code, body = self.request('POST', '/api/cancel', {"request_id": "unknown-request"})
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(body)['cancelled'])


class SSEParserTests(unittest.TestCase):
    def test_multiline_and_ignored_messages(self):
        raw = [b': keepalive\n', b'\n', b'data: {"type":\n',
               b'data: "response.completed"}\n', b'\n', b'data: [DONE]\n', b'\n',
               b'data: not-json\n', b'\n', b'data: []\n', b'\n']
        self.assertEqual(list(triad.sse_events(raw)), [{'type': 'response.completed'}])

    def test_oversized_single_and_multiline_events(self):
        with self.assertRaises(triad.BridgeError):
            list(triad.sse_events([b'data: ' + b'a' * 120_001 + b'\n']))
        with self.assertRaises(triad.BridgeError):
            list(triad.sse_events([b'data: ' + b'a' * 70_000 + b'\n',
                                   b'data: ' + b'b' * 70_000 + b'\n']))

    def test_incomplete_event_is_not_reported_as_completed(self):
        self.assertEqual(list(triad.sse_events(
            [b'data: {"type":"response.completed"}\n'])), [])


class HTTPAbortTests(unittest.TestCase):
    def make_handler(self):
        handler = triad.Handler.__new__(triad.Handler)
        handler.send_response = Mock()
        handler.headers_common = Mock()
        handler.end_headers = Mock()
        handler.close_connection = False
        return handler

    def test_broken_pipe_on_json_reply_is_not_a_server_crash(self):
        handler = self.make_handler()
        handler.wfile = Mock()
        handler.wfile.write.side_effect = BrokenPipeError(32, 'Broken pipe')
        handler.send_json(400, {'error': 'Некорректный JSON'})
        self.assertTrue(handler.close_connection)

    def test_truncated_json_is_rejected_without_partial_parsing(self):
        handler = self.make_handler()
        handler.headers = {'Content-Length': '40'}
        handler.rfile = io.BytesIO(b'{"request_id":"aborted"')
        with self.assertRaisesRegex(triad.BridgeError, 'Некорректный JSON'):
            handler.data()

    def test_full_json_still_parses(self):
        handler = self.make_handler()
        blob = b'{"hello":"world"}'
        handler.headers = {'Content-Length': str(len(blob))}
        handler.rfile = io.BytesIO(blob)
        self.assertEqual(handler.data(), {'hello': 'world'})


if __name__ == '__main__':
    unittest.main()
