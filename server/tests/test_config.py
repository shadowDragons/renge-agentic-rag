from app.core.config import Settings


def test_settings_resolve_embedding_api_key_from_env_file_named_secret(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_EMBEDDING_API_KEY=",
                "OPENAI_EMBEDDING_API_KEY_ENV_VAR=SILICONFLOW_API_KEY",
                "SILICONFLOW_API_KEY=sk-test-from-env-file",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=str(env_file))

    assert settings.resolved_embedding_api_key == "sk-test-from-env-file"


def test_langfuse_effective_sample_rate_defaults_to_twenty_percent_for_prod(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("LANGFUSE_SAMPLE_RATE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.langfuse_effective_sample_rate == 0.2


def test_langfuse_effective_sample_rate_keeps_explicit_value_for_prod(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_SAMPLE_RATE", "0.5")

    settings = Settings(_env_file=None)

    assert settings.langfuse_effective_sample_rate == 0.5


def test_langfuse_effective_sample_rate_defaults_to_full_for_dev(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("LANGFUSE_SAMPLE_RATE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.langfuse_effective_sample_rate == 1.0
