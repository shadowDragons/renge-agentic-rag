from app.services.llm_pricing import compute_model_cost, normalize_model_name


def test_normalize_model_name_handles_deepseek_alias() -> None:
    assert normalize_model_name("deepseek-ai/DeepSeek-V4-Pro") == (
        "deepseek-ai/deepseek-v4-pro"
    )
    assert normalize_model_name("deepseek-v4-pro") == "deepseek-ai/deepseek-v4-pro"


def test_compute_model_cost_uses_local_static_pricing_table() -> None:
    breakdown = compute_model_cost(
        model_name="deepseek-ai/DeepSeek-V4-Pro",
        usage={
            "prompt_tokens": 1000000,
            "completion_tokens": 500000,
            "total_tokens": 1500000,
        },
    )

    assert breakdown is not None
    assert breakdown.currency == "CNY"
    assert breakdown.provider == "siliconflow"
    assert breakdown.as_langfuse_cost_details() == {
        "input": 3.0,
        "output": 3.0,
        "total": 6.0,
    }


def test_compute_model_cost_returns_none_for_unknown_model() -> None:
    assert (
        compute_model_cost(
            model_name="unknown-model",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "total_tokens": 110,
            },
        )
        is None
    )
