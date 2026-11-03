"""Request checks that depend on configured limits (Pydantic models hold only static rules)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.config import Settings
from app.errors import AppError, field_error, not_found, validation_error

Loc = Sequence[str | int]


def check_template(
    settings: Settings, *, system: str | None, prompt: str, loc: Loc = ("body",)
) -> None:
    """``prompt`` within ``MAX_PROMPT_CHARS`` and ``system`` within ``MAX_SYSTEM_CHARS``."""
    errors: list[dict[str, object]] = []
    if len(prompt) > settings.max_prompt_chars:
        errors.append(
            {
                "loc": [*loc, "prompt"],
                "msg": f"String should have at most {settings.max_prompt_chars} characters",
                "type": "string_too_long",
            }
        )
    if system is not None and len(system) > settings.max_system_chars:
        errors.append(
            {
                "loc": [*loc, "system"],
                "msg": f"String should have at most {settings.max_system_chars} characters",
                "type": "string_too_long",
            }
        )
    if errors:
        raise validation_error(errors)


def check_variables(
    settings: Settings, variables: Mapping[str, str], loc: Loc = ("body", "variables")
) -> None:
    """At most ``MAX_VARIABLES`` entries, each value within ``MAX_VARIABLE_VALUE_CHARS``."""
    if len(variables) > settings.max_variables:
        raise field_error(
            loc,
            f"Dictionary should have at most {settings.max_variables} items",
            "too_long",
        )
    for key, value in variables.items():
        if len(value) > settings.max_variable_value_chars:
            raise field_error(
                [*loc, key],
                f"String should have at most {settings.max_variable_value_chars} characters",
                "string_too_long",
            )


def check_max_tokens(
    settings: Settings, value: int | None, loc: Loc = ("body", "max_tokens")
) -> None:
    """``max_tokens`` within ``MAX_OUTPUT_TOKENS`` (the per-model check happens later)."""
    if value is not None and value > settings.max_output_tokens:
        raise field_error(
            loc,
            f"Input should be less than or equal to {settings.max_output_tokens}",
            "less_than_equal",
        )


def check_rendered_length(settings: Settings, system: str | None, prompt: str) -> None:
    if len(system or "") + len(prompt) > settings.max_rendered_chars:
        raise AppError(
            422,
            "limit_exceeded",
            "The rendered prompt is too long.",
            {"limit": "max_rendered_chars", "max": settings.max_rendered_chars},
        )


def parse_id(value: str, resource: str) -> str:
    """Path ids must be 32 lowercase hex characters; anything else is a 404."""
    if len(value) != 32 or any(ch not in "0123456789abcdef" for ch in value):
        raise not_found(resource)
    return value
