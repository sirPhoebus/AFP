"""Runtime configuration and secrets metadata."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    api_token: str | None
    approval_roles: tuple[str, ...]
    agent_provider_api_key: str | None
    agent_provider_base_url: str
    agent_provider_model: str
    agent_provider_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "AppConfig":
        roles = tuple(
            role.strip()
            for role in os.getenv("AFP_APPROVAL_ROLES", "reviewer,operator").split(",")
            if role.strip()
        )
        return cls(
            api_token=os.getenv("AFP_API_TOKEN"),
            approval_roles=roles,
            agent_provider_api_key=os.getenv("AFP_AGENT_PROVIDER_API_KEY"),
            agent_provider_base_url=os.getenv("AFP_AGENT_PROVIDER_BASE_URL", "http://127.0.0.1:1234/v1"),
            agent_provider_model=os.getenv(
                "AFP_AGENT_PROVIDER_MODEL",
                "Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled",
            ),
            agent_provider_timeout_seconds=float(os.getenv("AFP_AGENT_PROVIDER_TIMEOUT_SECONDS", "120")),
        )

    def secret_sources(self) -> dict[str, str]:
        return {
            "api_token": "env:AFP_API_TOKEN" if self.api_token else "unset",
            "agent_provider_api_key": "env:AFP_AGENT_PROVIDER_API_KEY" if self.agent_provider_api_key else "unset",
        }
