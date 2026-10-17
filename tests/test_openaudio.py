"""OpenAudio boundaries and actual bridge requests, without downloading weights."""
import base64
import hashlib
import io
import json
import math
import struct
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
import types
import sys
from unittest.mock import patch

from backend.audio.addons import OpenAudioAddon
from backend.audio.openaudio import (FISH_REVISION, MODEL_FILES, reference_status,
                                    save_reference, validate_request, download, download_command)


def wav(seconds=3):
    out = io.BytesIO()
    with wave.open(out, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b''.join(struct.pack('<h', int(3000*math.sin(i/10)))
                                    for i in range(8000*seconds)))
    return out.getvalue()


class OpenAudioTests(unittest.TestCase):
    def test_gated_download_explains_account_access_and_local_login(self):
        from contextlib import redirect_stderr
        class GatedRepoError(Exception):
            pass
        stub = types.ModuleType('huggingface_hub.utils')
        stub.GatedRepoError = GatedRepoError
        output = io.StringIO()
        with patch.dict(sys.modules, {'huggingface_hub.utils': stub}), redirect_stderr(output), \
                patch('backend.audio.openaudio.download', side_effect=GatedRepoError('private upstream detail')):
            result = download_command(Path('/unused'))
        self.assertEqual(result, 1)
        self.assertIn('hf auth login', output.getvalue())
        self.assertIn('https://huggingface.co/fishaudio/openaudio-s1-mini', output.getvalue())
        self.assertNotIn('private upstream detail', output.getvalue())

    def test_download_pins_snapshot_and_rejects_checksum_mismatch(self):
        content = b'fixture model'
        digest = hashlib.sha256(content).hexdigest()
        entries = [SimpleNamespace(rfilename=name, size=len(content),
                                   lfs=SimpleNamespace(sha256=digest)) for name in MODEL_FILES]
        info = SimpleNamespace(sha='a'*40, siblings=entries)
        api = SimpleNamespace(model_info=lambda *args, **kwargs: info)
        calls = []
        def fetch(repo, name, revision, local_dir):
            calls.append((repo, revision))
            local_dir.mkdir(parents=True, exist_ok=True)
            target = local_dir / name
            target.write_bytes(content)
            return str(target)
        stub = types.ModuleType('huggingface_hub')
        stub.HfApi = lambda: api
        stub.hf_hub_download = fetch
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {'huggingface_hub': stub}):
            root = Path(folder)
            download(root)
            marker = root / 'models/installed.json'
            manifest = json.loads(marker.read_text())
            self.assertEqual(manifest['revision'], info.sha)
            self.assertTrue(all(revision == info.sha for _, revision in calls))
            entries[0].lfs.sha256 = '0'*64
            with self.assertRaisesRegex(RuntimeError, 'сумма'):
                download(root)
            self.assertFalse(marker.exists(), 'failed verification must never leave an installed marker')

    def test_reference_upload_roundtrip_and_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = {'voice': 'voice-2', 'text': 'Exact transcript.',
                    'audio': base64.b64encode(wav()).decode()}
            self.assertEqual(save_reference(root, data), {'voice': 'voice-2', 'saved': True})
            self.assertEqual(reference_status(root), ['voice-2'])
            path = root / 'references/voice-2.json'
            record = json.loads(path.read_text())
            self.assertEqual(base64.b64decode(record['audio']), wav())
            self.assertEqual(record['text'], data['text'])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            for changes in ({'voice': '../escape'}, {'audio': 'not base64'},
                            {'text': ''}, {'audio': base64.b64encode(wav(1)).decode()}):
                with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                    save_reference(root, dict(data, **changes))
            self.assertEqual(json.loads(path.read_text()), record)

    def test_http_reference_upload_accepts_wav_above_normal_json_limit(self):
        from backend.server import http_server as bridge
        addon = OpenAudioAddon()
        with tempfile.TemporaryDirectory() as folder, patch.dict(bridge.ADDONS, {addon.kind: addon}):
            addon.root = Path(folder)
            server = bridge.Server(('127.0.0.1', 0), bridge.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                body = json.dumps({'voice': 'voice-1', 'text': 'Reference transcript.',
                                   'audio': base64.b64encode(wav(6)).decode()}).encode()
                self.assertGreater(len(body), 100000)
                url = f'http://127.0.0.1:{server.server_port}/api/voice/{addon.kind}/reference'
                headers = {'Host': f'{bridge.HOST}:{bridge.PORT}', 'Content-Type': 'application/json'}
                request = urllib.request.Request(url, body, headers)
                with urllib.request.urlopen(request) as response:
                    self.assertTrue(json.load(response)['saved'])
                self.assertEqual(reference_status(addon.root), ['voice-1'])
                request = urllib.request.Request(url, body, dict(headers, Origin='https://other.example'))
                with self.assertRaises(urllib.error.HTTPError) as rejected:
                    urllib.request.urlopen(request)
                self.assertEqual(rejected.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()

    def test_invalid_synthesis_is_rejected_before_start(self):
        addon = OpenAudioAddon()
        with patch.object(addon, 'await_ready') as start:
            for data in ({'text': 'hello', 'voice': '../file'},
                         {'text': ' ', 'voice': 'default'},
                         {'text': 'x'*451, 'voice': 'default'},
                         {'text': 'hello', 'voice': 'default', 'speed': True},
                         {'text': 'hello', 'voice': 'default', 'speed': float('nan')}):
                with self.subTest(data=data), self.assertRaises(ValueError):
                    addon.synthesize(data)
            start.assert_not_called()
        self.assertEqual(validate_request({'text': ' hello ', 'voice': 'default'}),
                         ('hello', 'default', 1.0))

    def test_partial_weights_never_count_as_installed(self):
        addon = OpenAudioAddon()
        with tempfile.TemporaryDirectory() as folder:
            addon.root = Path(folder)
            (addon.root / 'models').mkdir()
            (addon.root / 'venv/bin').mkdir(parents=True)
            (addon.root / 'venv/bin/python').touch()
            (addon.root / 'fish-speech/fish_speech').mkdir(parents=True)
            manifest = {'source_revision': FISH_REVISION, 'files': {}}
            for name in MODEL_FILES:
                (addon.root / 'models' / name).write_bytes(b'verified fixture')
                manifest['files'][name] = {'size': len(b'verified fixture')}
            self.assertFalse(addon.installed)
            (addon.root / 'models/installed.json').write_text(json.dumps(manifest))
            self.assertTrue(addon.installed)
            (addon.root / 'models/model.pth').write_bytes(b'partial')
            self.assertFalse(addon.installed)

    def test_bridge_sends_selected_voice_speed_and_text_and_checks_wav(self):
        requests, output = [], [wav()]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                requests.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(output[0])
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            addon = OpenAudioAddon()
            addon.port = server.server_port
            with patch.object(addon, 'await_ready', return_value=True):
                result = addon.synthesize({'text': ' Hello ', 'voice': 'default', 'speed': 1.2})
                self.assertEqual(result, output[0])
                self.assertEqual(requests, [('/speak', {'text': 'Hello', 'voice': 'default', 'speed': 1.2})])
                output[0] = b'not wav'
                with self.assertRaises(RuntimeError):
                    addon.synthesize({'text': 'Hello', 'voice': 'default'})
        finally:
            server.shutdown()
            server.server_close()

    def test_unavailable_reference_does_not_fall_back_to_random_voice(self):
        addon = OpenAudioAddon()
        with tempfile.TemporaryDirectory() as folder, patch.object(addon, 'await_ready') as start:
            addon.root = Path(folder)
            with self.assertRaisesRegex(ValueError, 'WAV'):
                addon.synthesize({'text': 'Hello', 'voice': 'voice-1'})
            start.assert_not_called()
