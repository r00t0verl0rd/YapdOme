import json
import unittest

from backend.server.llm import API_URL, DEEPSEEK_URL, BridgeError
from backend.server.provider_adapters import (
    DeepSeekAdapter,
    OpenAIResponsesAdapter,
    get_http_adapter,
)


class FakeState:
    def access_token(self):
        return "chatgpt-token"

    def deepseek_key(self):
        return "deepseek-key"


class ProviderAdapterTests(unittest.TestCase):
    def setUp(self):
        self.state = FakeState()

    def test_openai_responses_adapter_builds_request_and_normalizes_stream(self):
        adapter = OpenAIResponsesAdapter()
        request = adapter.request(
            self.state, "gpt-test", "shared instructions",
            [{"role": "user", "content": "new event"}],
        )
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, API_URL + "/responses")
        self.assertEqual(request.headers["Authorization"], "Bearer chatgpt-token")
        self.assertEqual(payload["instructions"], "shared instructions")
        self.assertEqual(payload["input"], [{"role": "user", "content": "new event"}])
        self.assertFalse(payload["store"])
        self.assertTrue(payload["stream"])
        self.assertEqual(
            adapter.parse_event({"type": "response.output_text.delta", "delta": "Hi"}),
            ("delta", "Hi"),
        )
        self.assertEqual(adapter.parse_event({"type": "response.completed"}), ("done", ""))
        self.assertEqual(
            adapter.parse_event({"type": "response.failed", "response": {"error": "bad"}})[0],
            "error",
        )

    def test_deepseek_adapter_builds_chat_completion_and_normalizes_stream(self):
        adapter = DeepSeekAdapter()
        request = adapter.request(
            self.state, "deepseek-flash", "shared instructions",
            [{"role": "user", "content": "new event"}],
        )
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, DEEPSEEK_URL + "/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer deepseek-key")
        self.assertEqual(payload["messages"], [
            {"role": "system", "content": "shared instructions"},
            {"role": "user", "content": "new event"},
        ])
        self.assertTrue(payload["stream"])
        self.assertEqual(
            adapter.parse_event({"choices": [{"delta": {"content": "Hi"}}]}),
            ("delta", "Hi"),
        )
        self.assertEqual(
            adapter.parse_event({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            ("done", ""),
        )

    def test_adapter_registry_is_provider_keyed(self):
        self.assertIsInstance(get_http_adapter("chatgpt"), OpenAIResponsesAdapter)
        self.assertIsInstance(get_http_adapter("deepseek"), DeepSeekAdapter)
        self.assertIsInstance(
            get_http_adapter("codex"), OpenAIResponsesAdapter,
            "one-shot auxiliary tasks retain the existing ChatGPT HTTP fallback",
        )
        with self.assertRaises(BridgeError):
            get_http_adapter("unknown-provider")


if __name__ == "__main__":
    unittest.main()
