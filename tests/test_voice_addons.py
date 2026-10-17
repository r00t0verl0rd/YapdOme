"""No model downloads: test local voice installer boundaries and UI wiring."""
import sys
import tempfile
import unittest
from pathlib import Path
from html.parser import HTMLParser
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from yapdome.audio.addons import safe_directory, ADDONS, VOICE_NAMES, PIPER_ORIGIN, SILERO_ORIGIN

BASE=Path(__file__).resolve().parents[1]

class IDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=[]
    def handle_starttag(self,tag,attrs):
        for key,value in attrs:
            if key=="id":
                self.ids.append(value)

class AddonTests(unittest.TestCase):
    def test_backends_have_bounded_voices(self):
        self.assertEqual(set(ADDONS),{"kokoro","kokoro-ru","piper","silero","qwen3-tts"})
        for key,voices in VOICE_NAMES.items():
            self.assertTrue(voices)
            self.assertEqual(len(set(voices)),len(voices))
            self.assertEqual(ADDONS[key].kind,key)

    def test_model_urls_and_files_are_allowlisted(self):
        p=ADDONS["piper"]
        self.assertEqual(len(p.expected_files()),8)
        self.assertTrue(p._url("ru_RU-irina-medium.onnx").startswith(PIPER_ORIGIN))
        self.assertEqual(ADDONS["silero"]._url("v5_ru.pt"),SILERO_ORIGIN)
        self.assertIn("ru_g2p.py",ADDONS["kokoro-ru"].expected_files())
        self.assertIn("voices-v1.0.bin",ADDONS["kokoro"].expected_files())

    def test_russian_model_requires_complete_phonetic_assets(self):
        from yapdome.audio.addons import Addon, RU_ESPEAK_FILES, complete_asset
        expected=set(RU_ESPEAK_FILES)
        self.assertIn("espeak-data/ru_dict",expected)
        self.assertIn("espeak-data/phontab",expected)
        self.assertIn("espeak-data/lang/zle/ru",expected)
        self.assertIn("kokoro-config.json",Addon("kokoro-ru").expected_files())
        with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
            root=Path(folder)
            addon=Addon("kokoro-ru")
            addon.root=root
            (root/"venv/bin").mkdir(parents=True)
            (root/"venv/bin/python").touch()
            for name in addon.expected_files():
                if name.startswith("espeak-data/"):
                    continue
                target=root/name
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(b"model"*512)
            self.assertFalse(addon.installed)
            for name in RU_ESPEAK_FILES:
                target=root/name
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(b"phonemes"*300)
            # Kokoro also depends on RUAccent models inside its private venv.
            self.assertFalse(addon.installed)
            from yapdome.audio.ruaccent_repair import ESSENTIAL
            cache=root/"venv/lib/python3.12/site-packages/ruaccent"
            for name in ESSENTIAL:
                target=cache/name
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(b"o"*200000 if name.endswith(".onnx") else b"d"*512)
            self.assertTrue(addon.installed)
            (root/"espeak-data/ru_dict").unlink()
            self.assertFalse(addon.installed)
            (root/"espeak-data/ru_dict").write_bytes(b"dictionary"*512)
            (cache/"nn/nn_omograph/turbo3.1/model.onnx").unlink()
            self.assertFalse(addon.installed)

    def test_ruaccent_detects_partial_downloaded_directory(self):
        from yapdome.audio.ruaccent_repair import check_essential, ESSENTIAL
        with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
            root=Path(folder)
            target=root/"nn/nn_omograph/turbo3.1"
            target.mkdir(parents=True)
            (target/"config.json").write_text("{}")
            self.assertIn("nn/nn_omograph/turbo3.1/model.onnx",check_essential(root))
            for name in ESSENTIAL:
                dest=root/name
                dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes(b"onnx"*40000 if name.endswith(".onnx") else b"dictionary"*100)
            self.assertEqual(check_essential(root),[])

    def test_small_language_definition_is_valid_but_pointer_is_not(self):
        from yapdome.audio.addons import complete_asset
        with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
            root=Path(folder)
            language=root/"espeak-data/lang/zle/ru"
            language.parent.mkdir(parents=True)
            language.write_text("name Russian\\nlanguage ru\\n")
            self.assertTrue(complete_asset(root,"espeak-data/lang/zle/ru"))
            dictionary=root/"espeak-data/ru_dict"
            dictionary.write_bytes(b"x"*100)
            self.assertFalse(complete_asset(root,"espeak-data/ru_dict"))

    def test_directory_validation(self):
        home=Path.home()
        with self.assertRaises(ValueError):
            safe_directory("/", "piper")
        with self.assertRaises(ValueError):
            safe_directory(str(home), "silero")
        with tempfile.TemporaryDirectory(dir=home) as base:
            target=Path(base)/"voice"
            self.assertEqual(safe_directory(str(target),"silero"),target.resolve())
            (Path(base)/"server.py").write_text("protected")
            with self.assertRaises(ValueError):
                safe_directory(base,"piper")

    def test_output_wav_must_contain_audible_samples(self):
        import io, wave, struct
        from yapdome.audio.addons import valid_wav
        self.assertFalse(valid_wav(b''))
        def make_wav(values):
            output=io.BytesIO()
            with wave.open(output, 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(22050)
                w.writeframes(struct.pack('<'+'h'*len(values), *values))
            return output.getvalue()
        self.assertFalse(valid_wav(make_wav([0]*4000)))
        self.assertTrue(valid_wav(make_wav([200 if i%4==0 else 0 for i in range(4000)])))

    def test_kokoro_and_silero_installation_dependencies(self):
        from yapdome.audio.addons import ADDONS
        self.assertIn('espeak-data/ru_dict', ADDONS['kokoro-ru'].expected_files())
        code=(BASE/'yapdome/audio/addons.py').read_text()
        self.assertIn('RU_ESPEAK_FILES', code)
        self.assertIn('kokoro-config.json', code)
        self.assertNotIn('from huggingface_hub import snapshot_download', code)
        self.assertIn('scipy', code)
    def test_voice_studio_has_unique_controls(self):
        h=IDs();h.feed((BASE/"web/index.html").read_text())
        self.assertEqual(len(h.ids),len(set(h.ids)), "duplicate HTML ids")
        for key in ("ttsBackend","voiceSettings","piperDirectory","sileroDirectory",
                    "kokoroRuDirectory","kokoroDirectory","piperProgress",
                    "sileroProgress","kokoroRuProgress","voiceHint",
                    "voiceEnabled","auto","rate"):
            self.assertIn(key,h.ids)
        js=(BASE/"web/app.js").read_text()
        self.assertIn("syncVoicePanel()",js)
        self.assertIn("'/api/voice/'+addon.key",js)
        self.assertIn("piperSpeakers",js)
        self.assertIn("sileroSpeakers",js)
        self.assertIn("qwen3BuiltinSpeakers",js)

    def test_qwen3_custom_voices_share_one_folder_and_crud(self):
        import io, wave, struct, base64
        from yapdome.audio.qwen3 import Qwen3Voices, QWEN3_VOICES_DIR
        def wav_b64():
            out=io.BytesIO()
            with wave.open(out, 'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
                w.writeframes(struct.pack('<'+'h'*4000, *([200 if i%4==0 else 0 for i in range(4000)])))
            return base64.b64encode(out.getvalue()).decode()
        with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
            store=Qwen3Voices(folder)
            self.assertEqual(store.list(), [])
            design=store.create({"name":"Deep Narrator","mode":"design","instruct":"deep calm narrator"})
            self.assertEqual(design["id"],"Deep-Narrator")
            preset=store.create({"name":"Angry Ryan","mode":"preset","speaker":"Ryan","instruct":"angry","speed":1.2})
            self.assertEqual(preset["speaker"],"Ryan")
            with self.assertRaises(ValueError):
                store.create({"name":"Clone","mode":"clone","ref_text":"hello"})
            clone=store.create({"name":"Mom","mode":"clone","ref_text":"hello","ref_audio_b64":wav_b64()})
            self.assertEqual(clone["mode"],"clone")
            self.assertTrue(store.ref_path("Mom").is_file())
            # The '+' flow must support an unbounded number of voices.
            for i in range(50):
                store.create({"name":f"Voice {i}","mode":"design","instruct":"x"})
            self.assertEqual(len(store.list()), 53)
            self.assertTrue(store.delete("Mom"))
            self.assertFalse(store.delete("nope"))
        self.assertIn("qwen3-voices", str(QWEN3_VOICES_DIR))


class SupervisionTests(unittest.TestCase):
    """No model downloads: fake child processes and readiness probes."""

    def test_crashed_worker_exposes_traceback_and_stays_stopped(self):
        from unittest.mock import Mock, PropertyMock, patch
        from yapdome.audio.addons import Addon
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp, patch.object(
            Addon, "installed", new_callable=PropertyMock, return_value=True
        ):
            addon=Addon("piper")
            addon.root=Path(tmp)
            (addon.root/"worker.log").write_text(
                "Traceback (most recent call last):\\nModuleNotFoundError: No module named piper\\n"
            )
            crashed=Mock(pid=1001)
            crashed.poll.return_value=1
            addon._process=crashed
            with patch("yapdome.audio.addons.subprocess.Popen") as spawn:
                result=addon.status()
                self.assertEqual(result["status"],"error")
                self.assertFalse(result["ready"])
                self.assertIn("ModuleNotFoundError",result["error"])
                self.assertFalse(addon.start(), "must not silently respawn")
                spawn.assert_not_called()
                good=Mock(pid=1002)
                good.poll.return_value=None
                spawn.return_value=good
                self.assertTrue(addon.start(force=True))
                spawn.assert_called_once()
                self.assertEqual(addon.status()["status"],"starting")

    def test_readiness_probe_transitions_to_ready(self):
        from unittest.mock import Mock, PropertyMock, patch
        from yapdome.audio.addons import Addon
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp, patch.object(
            Addon, "installed", new_callable=PropertyMock, return_value=True
        ):
            addon=Addon("piper")
            addon.root=Path(tmp)
            good=Mock(pid=1003)
            good.poll.return_value=None
            with patch("yapdome.audio.addons.subprocess.Popen",return_value=good),patch.object(
                addon, "_health", side_effect=[False,True,True]
            ),patch("yapdome.audio.addons.time.sleep"):
                self.assertTrue(addon.await_ready(timeout=2))
                self.assertEqual(addon.status()["status"],"ready")

    def test_timeout_is_failure_not_infinite_starting(self):
        import time
        from unittest.mock import Mock, PropertyMock, patch
        from yapdome.audio.addons import Addon
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp, patch.object(
            Addon, "installed", new_callable=PropertyMock, return_value=True
        ):
            addon=Addon("silero")
            addon.root=Path(tmp)
            child=Mock(pid=1004)
            child.poll.return_value=None
            addon._process=child
            addon._started_at=time.monotonic()-125
            with patch.object(addon,"_health",return_value=False):
                current=addon.status()
            self.assertEqual(current["status"],"error")
            self.assertIn("120",current["error"])
            child.terminate.assert_called_once()
            self.assertFalse(current["ready"])

if __name__=="__main__":
    unittest.main()
