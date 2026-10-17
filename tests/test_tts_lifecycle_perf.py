"""Offline regression tests; synthetic latency is not model performance."""
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.audio.addons import Addon, valid_wav


class LifecycleTests(unittest.TestCase):
    def test_stop_reaps_before_forgetting_child(self):
        addon = Addon('piper')
        child = Mock()
        child.poll.return_value = None
        addon._process = child
        addon.stop()
        child.terminate.assert_called_once()
        child.wait.assert_called_once_with(timeout=4)
        self.assertIsNone(addon._process)

    def test_stop_escalates_and_reaps_stubborn_child(self):
        addon = Addon('kokoro-ru')
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired('worker', 4), 0]
        addon._process = child
        addon.stop()
        child.kill.assert_called_once()
        self.assertEqual(child.wait.call_count, 2)
        self.assertIsNone(addon._process)

    def test_failed_kill_wait_keeps_ownership(self):
        addon = Addon('silero')
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = subprocess.TimeoutExpired('worker', 4)
        addon._process = child
        with self.assertRaises(subprocess.TimeoutExpired):
            addon.stop()
        self.assertIs(addon._process, child)

    def test_truncated_wav_is_not_complete_audio(self):
        out = io.BytesIO()
        with wave.open(out, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
            wav.writeframes(b'\x00\x10' * 4000)
        self.assertTrue(valid_wav(out.getvalue()))
        self.assertFalse(valid_wav(out.getvalue()[:-2000]))



if __name__ == '__main__':
    unittest.main()
