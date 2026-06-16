from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from app.core.config import get_settings

_TOKEN_DENOMINATOR = Decimal("1000000")
_MONEY_PRECISION = Decimal("0.00000001")


@dataclass(frozen=True)
class ModelPricing:
    model_name: str
    input_per_1m: Decimal
    output_per_1m: Decimal
    currency: str
    provider: str
    source: str


@dataclass(frozen=True)
class ModelCostBreakdown:
    model_name: str
    normalized_model_name: str
    currency: str
    provider: str
    source: str
    input_cost: Decimal
    output_cost: Decimal
    total_cost: Decimal

    def as_langfuse_cost_details(self) -> dict[str, float]:
        return {
            "input": float(self.input_cost),
            "output": float(self.output_cost),
            "total": float(self.total_cost),
        }


_DEFAULT_PRICING_TABLE = {
    "deepseek-ai/deepseek-v4-pro": ModelPricing(
        model_name="deepseek-ai/DeepSeek-V4-Pro",
        input_per_1m=Decimal("3.00"),
        output_per_1m=Decimal("6.00"),
        currency="CNY",
        provider="siliconflow",
        source="https://siliconflow.cn/zh-cn/models?target=api",
    ),
}

_MODEL_ALIASES = {
    "deepseek-v4-pro": "deepseek-ai/deepseek-v4-pro",
    "deepseek-ai/deepseek-v4-pro": "deepseek-ai/deepseek-v4-pro",
}


def normalize_model_name(model_name: str) -> str:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return ""
    normalized = normalized.replace("\\", "/")
    return _MODEL_ALIASES.get(normalized, normalized)


def resolve_model_pricing(model_name: str) -> ModelPricing | None:
    normalized = normalize_model_name(model_name)
    if not normalized:
        return None

    table = dict(_DEFAULT_PRICING_TABLE)
    table.update(_load_pricing_overrides())
    return table.get(normalized)


def compute_model_cost(
    *,
    model_name: str,
    usage: dict[str, int] | None,
) -> ModelCostBreakdown | None:
    if not usage:
        return None

    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
        return None

    pricing = resolve_model_pricing(model_name)
    if pricing is None:
        return None

    input_cost = _quantize_money(
        (Decimal(prompt_tokens) / _TOKEN_DENOMINATOR) * pricing.input_per_1m
    )
    output_cost = _quantize_money(
        (Decimal(completion_tokens) / _TOKEN_DENOMINATOR) * pricing.output_per_1m
    )
    total_cost = _quantize_money(input_cost + output_cost)

    return ModelCostBreakdown(
        model_name=pricing.model_name,
        normalized_model_name=normalize_model_name(model_name),
        currency=pricing.currency,
        provider=pricing.provider,
        source=pricing.source,
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=total_cost,
    )


def _load_pricing_overrides() -> dict[str, ModelPricing]:
    raw = get_settings().llm_pricing_json.strip()
    if not raw:
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}

    overrides: dict[str, ModelPricing] = {}
    for model_name, item in payload.items():
        if not isinstance(item, dict):
            continue
        normalized_name = normalize_model_name(model_name)
        if not normalized_name:
            continue
        try:
            input_per_1m = Decimal(str(item["input_per_1m"]))
            output_per_1m = Decimal(str(item["output_per_1m"]))
        except Exception:
            continue
        overrides[normalized_name] = ModelPricing(
            model_name=str(item.get("model_name") or model_name),
            input_per_1m=input_per_1m,
            output_per_1m=output_per_1m,
            currency=str(item.get("currency") or "USD"),
            provider=str(item.get("provider") or "custom"),
            source=str(item.get("source") or "LLM_PRICING_JSON"),
        )
    return overrides


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_PRECISION, rounding=ROUND_HALF_UP)
