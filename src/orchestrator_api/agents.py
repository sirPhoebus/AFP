"""Minimal agent registry and provider wiring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from .config import AppConfig


@dataclass(frozen=True)
class AgentSpec:
    name: str
    provider: str
    fallback_provider: str | None
    task_kind: str


class OpenAICompatibleProvider:
    def __init__(self, *, base_url: str, model: str, api_key: str | None, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._preferred_model = model
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._resolved_model: str | None = None

    def invoke(self, prompt: str, *, fail: bool = False) -> dict[str, object]:
        if fail:
            raise RuntimeError("provider_failed")

        model = self._resolve_model()
        body = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a coding agent. Return a concise implementation summary and any artefacts. "
                        "When no artefacts exist, return an empty list."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        payload = json.dumps(body).encode("utf-8")
        req = request.Request(
            f"{self._base_url}/chat/completions",
            data=payload,
            headers=self._headers(),
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.URLError as exc:
            raise RuntimeError("provider_unreachable") from exc

        data = json.loads(raw)
        summary = self._extract_summary(data)
        return {"status": "ok", "summary": summary, "artefacts": []}

    def _resolve_model(self) -> str:
        if self._resolved_model is not None:
            return self._resolved_model

        try:
            available_ids = self._list_models()
        except Exception:
            self._resolved_model = self._preferred_model
            return self._resolved_model

        preferred = self._preferred_model.casefold()
        for model_id in available_ids:
            folded = model_id.casefold()
            if folded == preferred or preferred in folded or folded in preferred:
                self._resolved_model = model_id
                return self._resolved_model

        if len(available_ids) == 1:
            self._resolved_model = available_ids[0]
            return self._resolved_model

        self._resolved_model = self._preferred_model
        return self._resolved_model

    def _list_models(self) -> list[str]:
        req = request.Request(
            f"{self._base_url}/models",
            headers=self._headers(),
            method="GET",
        )
        with request.urlopen(req, timeout=self._timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("invalid_models_response")
        return [item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)]

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _extract_summary(self, response: dict[str, Any]) -> str:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("invalid_provider_response")
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            fragments = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    fragments.append(item["text"])
            if fragments:
                return "\n".join(fragment.strip() for fragment in fragments if fragment.strip())
        raise ValueError("invalid_provider_response")


class FallbackStructuredProvider:
    def invoke(self, prompt: str, *, fail: bool = False) -> dict[str, object]:
        del fail
        return {"status": "ok", "summary": f"fallback:{prompt[:120]}", "artefacts": []}


class AgentRegistry:
    def __init__(self, config: AppConfig) -> None:
        self._agents = {
            "planner": AgentSpec("planner", "local-llm", "fallback", "planning"),
            "coder": AgentSpec("coder", "local-llm", "fallback", "coding"),
        }
        self._providers = {
            "local-llm": OpenAICompatibleProvider(
                base_url=config.agent_provider_base_url,
                model=config.agent_provider_model,
                api_key=config.agent_provider_api_key,
                timeout_seconds=config.agent_provider_timeout_seconds,
            ),
            "fallback": FallbackStructuredProvider(),
        }

    def list_agents(self) -> list[AgentSpec]:
        return list(self._agents.values())

    def invoke(self, *, agent_name: str, prompt: str, fail_primary: bool = False) -> tuple[dict[str, object], str]:
        agent = self._agents[agent_name]
        try:
            result = self._providers[agent.provider].invoke(prompt, fail=fail_primary)
            provider_name = agent.provider
        except Exception:
            if agent.fallback_provider is None:
                raise
            result = self._providers[agent.fallback_provider].invoke(prompt)
            provider_name = agent.fallback_provider
        if not {"status", "summary", "artefacts"} <= set(result):
            raise ValueError("invalid_agent_response")
        return result, provider_name
