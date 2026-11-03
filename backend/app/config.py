"""Application settings loaded from environment variables (and an optional ``.env`` file).

Every value is validated when :class:`Settings` is constructed, so an invalid configuration stops
the process at startup with a readable message instead of failing on the first request.
"""

from __future__ import annotations

import ipaddress
from functools import cached_property, lru_cache
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from limits import RateLimitItem, parse_many
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.providers.catalog import parse_model_entries

CommaList = Annotated[list[str], NoDecode]
SecretList = Annotated[list[SecretStr], NoDecode]

#: Minimum length for each entry of ``API_KEYS``.
MIN_API_KEY_LENGTH = 16

RATE_LIMIT_GROUPS = ("default", "runs", "compare", "evals", "tokens", "data")


def _split_commas(value: Any) -> Any:
    """Split a comma separated string into trimmed, non-empty items (lists pass through)."""
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list | tuple):
        return [
            item.strip() if isinstance(item, str) else item
            for item in value
            if not (isinstance(item, str) and not item.strip())
        ]
    return value


class Settings(BaseSettings):
    """Runtime configuration. Field names map case-insensitively to environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    # ---- providers -------------------------------------------------------------------------
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    gemini_api_key: SecretStr | None = None
    openai_models: CommaList = Field(
        default_factory=lambda: ["gpt-5.5", "gpt-5.4-mini", "gpt-4.1-mini"]
    )
    gemini_models: CommaList = Field(
        default_factory=lambda: ["gemini-3.5-flash", "gemini-3.1-pro-preview"]
    )
    openai_temperature_prefixes: CommaList = Field(
        default_factory=lambda: ["gpt-4", "gpt-3.5", "chatgpt-4o"]
    )
    openai_max_output_tokens: int = Field(default=32768, ge=1)
    gemini_max_output_tokens: int = Field(default=65536, ge=1)
    demo_enabled: bool = True
    demo_stream_delay_ms: int = Field(default=20, ge=0, le=1000)
    default_model: str = "claude-opus-5-5"
    judge_model: str | None = None
    judge_max_tokens: int = Field(default=2048, ge=1)

    # ---- storage ---------------------------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./data/studio.db"

    # ---- security --------------------------------------------------------------------------
    api_keys: SecretList = Field(default_factory=list)
    cors_origins: CommaList = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )
    trusted_proxies: CommaList = Field(default_factory=list)
    rate_limit_enabled: bool = True
    rate_limit_storage_uri: str = "memory://"
    rate_limit_default: str = "300/minute"
    rate_limit_runs: str = "30/minute"
    rate_limit_compare: str = "10/minute"
    rate_limit_evals: str = "10/minute"
    rate_limit_tokens: str = "120/minute"
    rate_limit_data: str = "10/minute"
    rate_limit_auth_failures: str = "10/minute"
    max_body_bytes: int = Field(default=2 * 1024 * 1024, ge=1024)
    import_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)

    # ---- request limits --------------------------------------------------------------------
    max_prompt_chars: int = Field(default=100_000, ge=1)
    max_system_chars: int = Field(default=50_000, ge=0)
    max_rendered_chars: int = Field(default=200_000, ge=1)
    max_variables: int = Field(default=50, ge=0)
    max_variable_value_chars: int = Field(default=50_000, ge=0)
    max_output_tokens: int = Field(default=16384, ge=1)
    default_max_tokens: int = Field(default=4096, ge=1)
    max_compare_variants: int = Field(default=4, ge=1)
    max_compare_models: int = Field(default=4, ge=1)
    max_compare_cells: int = Field(default=12, ge=1)
    compare_concurrency: int = Field(default=4, ge=1)
    compare_total_timeout_seconds: float = Field(default=180.0, gt=0)
    max_cases_per_suite: int = Field(default=100, ge=1)
    max_assertions_per_case: int = Field(default=20, ge=1)
    max_eval_models: int = Field(default=4, ge=1)
    max_eval_calls: int = Field(default=200, ge=1)
    eval_concurrency: int = Field(default=4, ge=1)
    max_tags_per_prompt: int = Field(default=10, ge=0)
    max_versions_per_prompt: int = Field(default=200, ge=1)
    history_max_rows: int = Field(default=5000, ge=1)

    # ---- provider calls --------------------------------------------------------------------
    request_timeout_seconds: float = Field(default=120.0, ge=1, le=600)
    provider_max_retries: int = Field(default=2, ge=0, le=5)
    provider_concurrency: int = Field(default=16, ge=1)
    sse_keepalive_seconds: float = Field(default=15.0, gt=0)

    # ---- misc ------------------------------------------------------------------------------
    docs_enabled: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "text"

    # ---- validators ------------------------------------------------------------------------
    @field_validator(
        "openai_models",
        "gemini_models",
        "openai_temperature_prefixes",
        "cors_origins",
        "trusted_proxies",
        "api_keys",
        mode="before",
    )
    @classmethod
    def _comma_lists(cls, value: Any) -> Any:
        return _split_commas(value)

    @field_validator("anthropic_api_key", "openai_api_key", "gemini_api_key", mode="before")
    @classmethod
    def _empty_secret_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, SecretStr) and not value.get_secret_value().strip():
            return None
        return value

    @field_validator("openai_base_url", "judge_model", mode="before")
    @classmethod
    def _empty_str_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("openai_base_url")
    @classmethod
    def _check_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("OPENAI_BASE_URL must be an absolute http(s) URL")
        return value

    @field_validator("api_keys")
    @classmethod
    def _check_api_keys(cls, value: list[SecretStr]) -> list[SecretStr]:
        for key in value:
            if len(key.get_secret_value()) < MIN_API_KEY_LENGTH:
                raise ValueError(
                    f"every API_KEYS entry must be at least {MIN_API_KEY_LENGTH} characters long"
                )
        return value

    @field_validator("openai_models", "gemini_models")
    @classmethod
    def _check_model_entries(cls, value: list[str]) -> list[str]:
        parse_model_entries(value)
        return value

    @field_validator("trusted_proxies")
    @classmethod
    def _check_proxies(cls, value: list[str]) -> list[str]:
        for entry in value:
            try:
                ipaddress.ip_network(entry, strict=False)
            except ValueError as exc:
                raise ValueError(f"invalid TRUSTED_PROXIES entry: {entry!r}") from exc
        return value

    @field_validator(
        "rate_limit_default",
        "rate_limit_runs",
        "rate_limit_compare",
        "rate_limit_evals",
        "rate_limit_tokens",
        "rate_limit_data",
        "rate_limit_auth_failures",
    )
    @classmethod
    def _check_rate_limit(cls, value: str) -> str:
        value = value.strip()
        try:
            items = parse_many(value)
        except ValueError as exc:
            raise ValueError(f"invalid rate limit string: {value!r}") from exc
        if any(item.amount < 1 for item in items):
            raise ValueError(f"rate limit amounts must be at least 1: {value!r}")
        return value

    @field_validator("rate_limit_storage_uri")
    @classmethod
    def _check_storage_uri(cls, value: str) -> str:
        if "://" not in value:
            raise ValueError("RATE_LIMIT_STORAGE_URI must look like 'memory://' or 'redis://host'")
        return value.strip()

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_level(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("log_format", mode="before")
    @classmethod
    def _lower_format(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("default_model", "database_url")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    # ---- derived values --------------------------------------------------------------------
    @cached_property
    def trusted_proxy_networks(self) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
        """``TRUSTED_PROXIES`` parsed into networks (single addresses become /32 or /128)."""
        return tuple(ipaddress.ip_network(entry, strict=False) for entry in self.trusted_proxies)

    def rate_limits(self, group: str) -> list[RateLimitItem]:
        """Parsed limit items for a rate-limit group (``default``, ``runs``, ...)."""
        return parse_many(getattr(self, f"rate_limit_{group}"))

    @property
    def api_key_values(self) -> list[str]:
        """Plain API key values (never log or return these)."""
        return [key.get_secret_value() for key in self.api_keys]

    @property
    def auth_required(self) -> bool:
        return bool(self.api_keys)

    def secret_values(self) -> list[str]:
        """Every configured secret, used by the log redaction filter."""
        secrets = [
            secret.get_secret_value()
            for secret in (self.anthropic_api_key, self.openai_api_key, self.gemini_api_key)
            if secret is not None
        ]
        return [*secrets, *self.api_key_values]

    def limits_payload(self) -> dict[str, int | float]:
        """The ``Limits`` object exposed by ``GET /api/meta``."""
        return {
            "max_prompt_chars": self.max_prompt_chars,
            "max_system_chars": self.max_system_chars,
            "max_rendered_chars": self.max_rendered_chars,
            "max_variables": self.max_variables,
            "max_variable_value_chars": self.max_variable_value_chars,
            "max_output_tokens": self.max_output_tokens,
            "default_max_tokens": self.default_max_tokens,
            "max_compare_variants": self.max_compare_variants,
            "max_compare_models": self.max_compare_models,
            "max_compare_cells": self.max_compare_cells,
            "max_cases_per_suite": self.max_cases_per_suite,
            "max_assertions_per_case": self.max_assertions_per_case,
            "max_eval_models": self.max_eval_models,
            "max_eval_calls": self.max_eval_calls,
            "max_tags_per_prompt": self.max_tags_per_prompt,
            "max_versions_per_prompt": self.max_versions_per_prompt,
            "max_body_bytes": self.max_body_bytes,
            "import_max_bytes": self.import_max_bytes,
            "request_timeout_seconds": self.request_timeout_seconds,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, read once from the environment."""
    return Settings()
