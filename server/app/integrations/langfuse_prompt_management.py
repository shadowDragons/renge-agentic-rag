from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ManagedPromptResult:
    name: str
    prompt_type: str
    compiled: str | list[dict[str, Any]]
    version: int | None = None
    labels: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    source: str = "local_fallback"
    is_fallback: bool = False


@dataclass(frozen=True)
class PromptDefinition:
    name: str
    prompt_type: str
    label: str
    fallback: str | list[dict[str, Any]]
    cache_ttl_seconds: int = 60


class LangfusePromptProvider:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = None
        self.enabled = bool(
            self.settings.langfuse_prompt_management_enabled
            and self.settings.langfuse_public_key.strip()
            and self.settings.langfuse_secret_key.strip()
        )
        if not self.enabled:
            return
        try:
            from langfuse import Langfuse

            self.client = Langfuse(
                public_key=self.settings.langfuse_public_key,
                secret_key=self.settings.langfuse_secret_key,
                host=self.settings.langfuse_host,
            )
        except Exception as exc:  # pragma: no cover - defensive by design
            self.enabled = False
            logger.warning("Langfuse prompt provider initialization failed: %s", exc)

    def get_text_prompt(
        self,
        definition: PromptDefinition,
        *,
        variables: dict[str, Any],
    ) -> ManagedPromptResult:
        if definition.prompt_type != "text":
            raise ValueError("text prompt definition required")
        fallback = str(definition.fallback)
        if not self.enabled:
            return ManagedPromptResult(
                name=definition.name,
                prompt_type="text",
                compiled=self._compile_text_fallback(fallback, variables),
                labels=[definition.label],
                source="local_fallback",
                is_fallback=True,
            )

        try:
            prompt_client = self.client.get_prompt(
                definition.name,
                label=definition.label,
                type="text",
                cache_ttl_seconds=definition.cache_ttl_seconds,
                fallback=fallback,
            )
            compiled = str(prompt_client.compile(**variables))
            return ManagedPromptResult(
                name=prompt_client.name,
                prompt_type="text",
                compiled=compiled,
                version=getattr(prompt_client, "version", None),
                labels=list(getattr(prompt_client, "labels", []) or []),
                config=dict(getattr(prompt_client, "config", {}) or {}),
                source="langfuse" if not getattr(prompt_client, "is_fallback", False) else "langfuse_fallback",
                is_fallback=bool(getattr(prompt_client, "is_fallback", False)),
            )
        except Exception as exc:  # pragma: no cover - defensive by design
            logger.warning("Langfuse text prompt fetch failed for %s: %s", definition.name, exc)
            return ManagedPromptResult(
                name=definition.name,
                prompt_type="text",
                compiled=self._compile_text_fallback(fallback, variables),
                labels=[definition.label],
                source="local_fallback",
                is_fallback=True,
            )

    def get_chat_prompt(
        self,
        definition: PromptDefinition,
        *,
        variables: dict[str, Any],
    ) -> ManagedPromptResult:
        if definition.prompt_type != "chat":
            raise ValueError("chat prompt definition required")
        fallback = list(definition.fallback)  # shallow copy
        if not self.enabled:
            return ManagedPromptResult(
                name=definition.name,
                prompt_type="chat",
                compiled=self._compile_chat_fallback(fallback, variables),
                labels=[definition.label],
                source="local_fallback",
                is_fallback=True,
            )

        try:
            prompt_client = self.client.get_prompt(
                definition.name,
                label=definition.label,
                type="chat",
                cache_ttl_seconds=definition.cache_ttl_seconds,
                fallback=fallback,
            )
            compiled = [
                dict(item) if isinstance(item, dict) else {"role": "NOT_GIVEN", "content": str(item)}
                for item in prompt_client.compile(**variables)
            ]
            return ManagedPromptResult(
                name=prompt_client.name,
                prompt_type="chat",
                compiled=compiled,
                version=getattr(prompt_client, "version", None),
                labels=list(getattr(prompt_client, "labels", []) or []),
                config=dict(getattr(prompt_client, "config", {}) or {}),
                source="langfuse" if not getattr(prompt_client, "is_fallback", False) else "langfuse_fallback",
                is_fallback=bool(getattr(prompt_client, "is_fallback", False)),
            )
        except Exception as exc:  # pragma: no cover - defensive by design
            logger.warning("Langfuse chat prompt fetch failed for %s: %s", definition.name, exc)
            return ManagedPromptResult(
                name=definition.name,
                prompt_type="chat",
                compiled=self._compile_chat_fallback(fallback, variables),
                labels=[definition.label],
                source="local_fallback",
                is_fallback=True,
            )

    def _compile_text_fallback(
        self,
        template: str,
        variables: dict[str, Any],
    ) -> str:
        result = str(template)
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    def _compile_chat_fallback(
        self,
        messages: list[dict[str, Any]],
        variables: dict[str, Any],
    ) -> list[dict[str, Any]]:
        compiled: list[dict[str, Any]] = []
        for message in messages:
            content = str(message.get("content", ""))
            for key, value in variables.items():
                content = content.replace(f"{{{{{key}}}}}", str(value))
            compiled.append(
                {
                    **message,
                    "role": str(message.get("role", "user")),
                    "content": content,
                }
            )
        return compiled
