import unittest

from backend.server.codex import CodexAppServer


class CodexLogoutTests(unittest.TestCase):
    def test_logout_calls_app_server_and_clears_cached_account(self):
        client = CodexAppServer()
        client.account = {"type": "chatgpt", "email": "old-account@example.com"}
        sent = []

        def start():
            return None

        def write(message):
            sent.append(message)
            with client.lock:
                waiter = client.pending[message["id"]]
            waiter["response"] = {"id": message["id"], "result": {}}
            waiter["event"].set()

        client._start = start
        client._start_write = write
        client.logout()

        self.assertEqual(sent, [{"method": "account/logout", "id": 1}])
        self.assertIsNone(client.account)
        self.assertEqual(client.error, "")


if __name__ == "__main__":
    unittest.main()
