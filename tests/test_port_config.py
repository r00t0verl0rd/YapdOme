"""Порт настраивается только в yapdome/server/config.py."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

class PortConfigTests(unittest.TestCase):
    def port_from_fresh_server(self, environment):
        env = os.environ.copy()
        env.pop("TRIAD_PORT", None)
        env.update(environment)
        return subprocess.run(
            [sys.executable, "-c", "import yapdome.server; print(yapdome.server.PORT)"],
            cwd=ROOT, env=env, text=True, capture_output=True, timeout=15
        )

    def test_default_port_is_single_editable_server_setting(self):
        import yapdome.server
        result = self.port_from_fresh_server({})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(int(result.stdout.strip()), yapdome.server.DEFAULT_PORT)
        self.assertTrue(1 <= yapdome.server.DEFAULT_PORT <= 65535)

    def test_environment_override_still_works(self):
        result = self.port_from_fresh_server({"TRIAD_PORT": "13181"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "13181")

    def test_invalid_ports_fail_loudly(self):
        for value in ("0", "65536", "not-a-port"):
            with self.subTest(value=value):
                result = self.port_from_fresh_server({"TRIAD_PORT": value})
                self.assertNotEqual(result.returncode, 0)

    def test_mac_launcher_reads_server_port_not_hardcoded_default(self):
        source = (ROOT / "START-MAC.command").read_text(encoding="utf-8")
        self.assertIn("from yapdome.server import PORT; print(PORT)", source)
        self.assertNotIn('TRIAD_PORT:-8765', source)
        self.assertIn('http://127.0.0.1:${PORT}/api/version', source)
        self.assertIn('http://127.0.0.1:${PORT}/', source)

if __name__ == "__main__":
    unittest.main()
