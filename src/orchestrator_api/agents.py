"""Minimal agent registry and provider wiring."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    name: str
    provider: str
    fallback_provider: str | None
    task_kind: str


class LocalStructuredProvider:
    def invoke(self, prompt: str, *, fail: bool = False) -> dict[str, object]:
        if fail:
            raise RuntimeError("provider_failed")
        return {"status": "ok", "summary": prompt[:120], "artefacts": []}


class FallbackStructuredProvider:
    def invoke(self, prompt: str, *, fail: bool = False) -> dict[str, object]:
        del fail
        return {"status": "ok", "summary": f"fallback:{prompt[:120]}", "artefacts": []}


class AgentRegistry:
    def __init__(self) -> None:
        self._agents = {
            "planner": AgentSpec("planner", "local", "fallback", "planning"),
            "coder": AgentSpec("coder", "local", "fallback", "coding"),
        }
        self._providers = {
            "local": LocalStructuredProvider(),
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
