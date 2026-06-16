from __future__ import annotations

import json

from app.core.config import get_settings
from app.integrations.langfuse_prompt_management import LangfusePromptProvider
from app.services.answer_generation import (
    AnswerGenerationService,
    managed_text_prompt_definitions,
)


def _upsert_prompt(client, *, name: str, prompt, prompt_type: str, label: str) -> dict:
    created = client.create_prompt(
        name=name,
        prompt=prompt,
        type=prompt_type,
        labels=[label],
        commit_message="Seed prompt from local fallback template",
    )
    return {
        "name": created.name,
        "version": created.version,
        "labels": list(created.labels or []),
        "type": prompt_type,
        "status": "created",
    }


def main() -> int:
    settings = get_settings()
    provider = LangfusePromptProvider()
    if provider.client is None:
        raise SystemExit(
            "Langfuse Prompt Management 未启用或未正确配置。"
            "请先设置 LANGFUSE_PROMPT_MANAGEMENT_ENABLED=true 和 Langfuse 凭据。"
        )

    label = settings.langfuse_prompt_label
    answer_service = AnswerGenerationService()
    definitions = [answer_service.answer_prompt_definition(), *managed_text_prompt_definitions()]

    results = []
    for definition in definitions:
        result = _upsert_prompt(
            provider.client,
            name=definition.name,
            prompt=definition.fallback,
            prompt_type=definition.prompt_type,
            label=label,
        )
        results.append(result)

    print(json.dumps({"seeded": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
