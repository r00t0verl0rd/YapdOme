"""Wire-protocol adapters for HTTP-compatible LLM providers.

Conversation policy and session state live in Conversation Core. Each adapter only
translates a common turn request to a provider's HTTP format and normalizes its
stream events back to (kind, text).
"""
import json
import urllib.request

from .llm import API_URL, DEEPSEEK_URL, BridgeError, json_request


class HTTPProviderAdapter:
    provider_id = ""
    models_url = ""

    def access_token(self, state):
        raise NotImplementedError

    def request(self, state, model, instructions, inputs):
        raise NotImplementedError

    def parse_event(self, event):
        raise NotImplementedError

    def parse_models(self, payload):
        raise NotImplementedError

    def models(self, state):
        return self.parse_models(json_request(self.models_url, token=self.access_token(state)))

    @staticmethod
    def _request(url, payload, authorization):
        return urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + authorization,
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )


class OpenAIResponsesAdapter(HTTPProviderAdapter):
    provider_id = "chatgpt"
    models_url = API_URL + "/models"

    def access_token(self, state):
        return state.access_token()

    def request(self, state, model, instructions, inputs):
        return self._request(
            API_URL + "/responses",
            {"model": model, "instructions": instructions, "input": inputs,
             "store": False, "stream": True},
            self.access_token(state),
        )

    def parse_event(self, event):
        kind = event.get("type")
        if kind == "response.output_text.delta":
            return "delta", str(event.get("delta", ""))
        if kind == "response.completed":
            return "done", ""
        if kind in ("response.failed", "response.incomplete", "error"):
            response = event.get("response")
            response = response if isinstance(response, dict) else {}
            detail = response.get("error") or event.get("error") or response.get("incomplete_details")
            return "error", "OpenAI: " + str(detail)[:400]
        return "ignore", ""

    def parse_models(self, payload):
        return [
            {"slug": item["slug"], "name": item.get("display_name") or item["slug"]}
            for item in payload.get("models", [])
            if isinstance(item, dict) and item.get("visibility") == "list"
            and isinstance(item.get("slug"), str)
        ]


class DeepSeekAdapter(HTTPProviderAdapter):
    provider_id = "deepseek"
    models_url = DEEPSEEK_URL + "/models"

    def access_token(self, state):
        key = state.deepseek_key()
        if not key:
            raise BridgeError("Сначала введи API-ключ DeepSeek")
        return key

    def request(self, state, model, instructions, inputs):
        return self._request(
            DEEPSEEK_URL + "/chat/completions",
            {"model": model, "messages": [{"role": "system", "content": instructions}] + inputs,
             "stream": True},
            self.access_token(state),
        )

    def parse_event(self, event):
        if event.get("error"):
            return "error", str(event["error"])[:400]
        choices = event.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            choice = choices[0]
            delta = choice.get("delta")
            content = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(content, str) and content:
                return "delta", content
            if choice.get("finish_reason") is not None:
                return "done", ""
        return "ignore", ""

    def parse_models(self, payload):
        return [
            {"slug": item["id"], "name": item.get("id")}
            for item in payload.get("data", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]


HTTP_ADAPTERS = {
    "chatgpt": OpenAIResponsesAdapter(),
    "deepseek": DeepSeekAdapter(),
}


def get_http_adapter(provider):
    # Auxiliary one-shot tasks (director/topic review) historically use the
    # ChatGPT HTTP credential even while the main turn provider is Codex.
    if provider == "codex":
        return HTTP_ADAPTERS["chatgpt"]
    adapter = HTTP_ADAPTERS.get(provider)
    if adapter is None:
        raise BridgeError("Неизвестный HTTP-провайдер: " + str(provider))
    return adapter
