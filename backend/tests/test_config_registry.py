"""Settings parsing/validation, the model catalog and the provider registry."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.main import OPEN_API_WARNING, create_app
from app.providers.base import Pricing, ProviderName
from app.providers.catalog import (
    build_catalog,
    compute_cost,
    gemini_display_name,
    openai_display_name,
    parse_model_entries,
)
from app.providers.registry import build_registry
from tests.conftest import running_client
from tests.fakes import ScriptedProvider


def make(**values: object) -> Settings:
    return Settings(_env_file=None, **values)


def test_comma_lists_and_secrets() -> None:
    settings = make(
        openai_models=" gpt-5.5 , ,gpt-x=Custom Name ",
        cors_origins="https://a.example, https://b.example",
        api_keys="0123456789abcdef, fedcba9876543210",
        anthropic_api_key="  ",
        openai_api_key="sk-live",
        trusted_proxies="10.0.0.0/8, 192.168.1.1",
    )
    assert settings.openai_models == ["gpt-5.5", "gpt-x=Custom Name"]
    assert settings.cors_origins == ["https://a.example", "https://b.example"]
    assert settings.api_key_values == ["0123456789abcdef", "fedcba9876543210"]
    assert settings.auth_required
    assert settings.anthropic_api_key is None
    assert settings.openai_api_key is not None
    assert "sk-live" not in repr(settings)
    assert settings.secret_values() == ["sk-live", "0123456789abcdef", "fedcba9876543210"]
    assert [str(net) for net in settings.trusted_proxy_networks] == ["10.0.0.0/8", "192.168.1.1/32"]


def test_env_variables_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_MODELS", "gemini-x")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("LOG_FORMAT", "JSON")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    settings = make()
    assert settings.gemini_models == ["gemini-x"]
    assert settings.log_level == "DEBUG"
    assert settings.log_format == "json"
    assert settings.openai_base_url is None


@pytest.mark.parametrize(
    "values",
    [
        {"rate_limit_runs": "bogus"},
        {"rate_limit_default": "0/minute"},
        {"api_keys": "short"},
        {"openai_models": "bad id!"},
        {"trusted_proxies": "not-an-ip"},
        {"openai_base_url": "ftp://x"},
        {"rate_limit_storage_uri": "memory"},
        {"default_model": "  "},
        {"request_timeout_seconds": 0},
        {"log_format": "xml"},
    ],
)
def test_invalid_settings_fail(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as info:
        make(**values)
    if "api_keys" in values:
        assert "short" not in str(info.value)


#: The documented configuration at the repository root (copied to ``.env`` by users).
ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def _env_example_keys() -> list[str]:
    keys = []
    for raw in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            keys.append(line.split("=", 1)[0])
    return keys


def test_env_example_documents_every_setting() -> None:
    keys = _env_example_keys()
    assert len(keys) == len(set(keys)), "a variable is listed twice in .env.example"
    assert set(keys) == {name.upper() for name in Settings.model_fields}


def test_env_example_values_are_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    from_file = Settings(_env_file=ENV_EXAMPLE)
    assert from_file.model_dump() == make().model_dump()


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_rate_limits_and_limits_payload() -> None:
    settings = make(rate_limit_runs="5/minute;100/day")
    assert [str(item) for item in settings.rate_limits("runs")] == [
        "5 per 1 minute",
        "100 per 1 day",
    ]
    payload = settings.limits_payload()
    assert payload["max_compare_cells"] == 12
    assert payload["request_timeout_seconds"] == 120.0


def test_display_names() -> None:
    assert openai_display_name("gpt-5.4-mini") == "GPT-5.4 mini"
    assert openai_display_name("gpt-5.5") == "GPT-5.5"
    assert openai_display_name("o9") == "o9"
    assert gemini_display_name("gemini-3.1-pro-preview") == "Gemini 3.1 Pro Preview"
    assert parse_model_entries(["a=Alpha", "b"]) == [("a", "Alpha"), ("b", None)]
    with pytest.raises(ValueError, match="invalid model id"):
        parse_model_entries(["-bad"])


def test_catalog_order_and_flags() -> None:
    settings = make(openai_models="gpt-4.1-mini=Mini", gemini_models="gemini-2.0-flash")
    catalog = build_catalog(settings)
    ids = [spec.id for spec in catalog]
    assert ids == [
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-fable-5-1",
        "gpt-4.1-mini",
        "gemini-2.0-flash",
        "demo-concise",
        "demo-verbose",
    ]
    by_id = {spec.id: spec for spec in catalog}
    assert by_id["gpt-4.1-mini"].display_name == "Mini"
    assert by_id["gpt-4.1-mini"].supports_temperature
    assert not by_id["gemini-2.0-flash"].supports_thinking
    assert by_id["claude-opus-5-5"].thinking_always_on
    assert not by_id["claude-haiku-5-5"].supports_temperature
    assert "demo-concise" not in [spec.id for spec in build_catalog(make(demo_enabled=False))]


def test_duplicate_ids_and_unknown_defaults_fail_at_startup() -> None:
    with pytest.raises(ValueError, match="duplicate model id"):
        build_registry(make(openai_models="demo-concise"))
    with pytest.raises(ValueError, match="DEFAULT_MODEL"):
        build_registry(make(default_model="nope"))
    with pytest.raises(ValueError, match="JUDGE_MODEL"):
        build_registry(make(judge_model="nope"))


def test_cost_computation() -> None:
    pricing = Pricing(1.0, 2.0, 100, 10.0, 20.0)
    assert compute_cost(None, 1, 1) is None
    assert compute_cost(pricing, 100, 500_000) == 1.0001
    assert compute_cost(pricing, 101, 0) == round(101 / 1e6 * 10.0, 6)
    assert compute_cost(Pricing(4.0, 20.0), 1234, 567) == 0.016276


def test_effective_default_model_and_availability() -> None:
    settings = make()
    demo_only = build_registry(settings)
    assert demo_only.effective_default_model().id == "demo-concise"
    assert demo_only.demo_mode()
    assert not demo_only.is_available(demo_only.get_model("claude-opus-5-5"))

    anthropic = ScriptedProvider(ProviderName.ANTHROPIC)
    with_claude = build_registry(settings, {ProviderName.ANTHROPIC: anthropic})
    assert with_claude.effective_default_model().id == "claude-opus-5-5"
    assert not with_claude.demo_mode()

    nothing = build_registry(make(demo_enabled=False))
    assert nothing.effective_default_model().id == "claude-opus-5-5"
    assert nothing.get_model("demo-concise") is None


async def test_registry_closes_providers() -> None:
    fake = ScriptedProvider(ProviderName.OPENAI)
    registry = build_registry(make(), {ProviderName.OPENAI: fake})
    await registry.aclose()
    assert fake.closed


async def test_startup_warning_when_open_with_keys(
    make_settings, caplog: pytest.LogCaptureFixture
) -> None:
    settings = make_settings(anthropic_api_key="sk-ant-real-looking-key-000", log_level="INFO")
    caplog.set_level(logging.INFO, logger="app")
    async with running_client(create_app(settings)):
        pass
    assert OPEN_API_WARNING in caplog.text
    assert "providers=anthropic" in caplog.text
    assert "sk-ant-real-looking-key-000" not in caplog.text


async def test_no_startup_warning_with_api_keys(
    make_settings, caplog: pytest.LogCaptureFixture
) -> None:
    settings = make_settings(
        anthropic_api_key="sk-ant-real-looking-key-000", api_keys="0123456789abcdef"
    )
    async with running_client(create_app(settings)):
        pass
    assert OPEN_API_WARNING not in caplog.text


async def test_lazy_module_app(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import app.main as main_module

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'lazy.db'}")
    get_settings.cache_clear()
    monkeypatch.setattr(main_module, "_app", None)
    try:
        built = main_module.app
        assert built is main_module.app
        assert built.title == "Prompt Engineering Studio API"
    finally:
        get_settings.cache_clear()
    with pytest.raises(AttributeError):
        _ = main_module.missing_attribute
