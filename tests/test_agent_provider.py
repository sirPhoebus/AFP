import json
import unittest
from unittest.mock import patch

from orchestrator_api.agents import OpenAICompatibleProvider


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class AgentProviderTests(unittest.TestCase):
    def test_openai_compatible_provider_discovers_lm_studio_model_and_parses_completion(self) -> None:
        provider = OpenAICompatibleProvider(
            base_url="http://127.0.0.1:1234/v1",
            model="Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled",
            api_key=None,
            timeout_seconds=5,
        )
        requests_seen = []
        models_payload = {
            "data": [
                {
                    "id": "Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-GGUF",
                }
            ]
        }
        completion_payload = {
            "choices": [
                {
                    "message": {
                        "content": "Implemented the requested change.",
                    }
                }
            ]
        }

        def fake_urlopen(req, timeout):
            del timeout
            requests_seen.append(req)
            if req.full_url.endswith("/models"):
                return _FakeResponse(models_payload)
            if req.full_url.endswith("/chat/completions"):
                return _FakeResponse(completion_payload)
            raise AssertionError(req.full_url)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = provider.invoke("write code")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["summary"], "Implemented the requested change.")
        self.assertEqual(result["artefacts"], [])
        self.assertEqual(len(requests_seen), 2)
        body = json.loads(requests_seen[1].data.decode("utf-8"))
        self.assertEqual(
            body["model"],
            "Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-GGUF",
        )


if __name__ == "__main__":
    unittest.main()
