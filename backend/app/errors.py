"""Error envelope, application errors and FastAPI exception handlers.

Every 4xx/5xx response uses the envelope ``{"error": {"code", "message", "details"?}}``.
Messages are short, safe sentences; provider error bodies, stack traces, SQL and secrets never
reach clients.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

from app.providers.base import ProviderError, ProviderErrorKind

logger = logging.getLogger(__name__)

#: Retry-After used for provider rate limits/overloads when the provider gives no hint.
DEFAULT_PROVIDER_RETRY_AFTER = 30

VALIDATION_MESSAGE = "Request validation failed."
HTTP_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")


class AppError(Exception):
    """An error rendered as the standard envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details: dict[str, Any] | None = dict(details) if details is not None else None
        self.headers: dict[str, str] = dict(headers or {})

    def body(self) -> dict[str, Any]:
        """The ``ErrorBody`` object (without the outer ``error`` key)."""
        return error_body(self.code, self.message, self.details)

    def with_details(self, **extra: Any) -> AppError:
        """A copy with extra ``details`` keys."""
        return AppError(
            self.status_code,
            self.code,
            self.message,
            {**(self.details or {}), **extra},
            self.headers,
        )


def error_body(code: str, message: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = dict(details)
    return body


def error_envelope(
    code: str, message: str, details: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    return {"error": error_body(code, message, details)}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        error_envelope(code, message, details), status_code=status_code, headers=dict(headers or {})
    )


# ---- constructors for common errors --------------------------------------------------------


def not_found(resource: str | None = None) -> AppError:
    if resource is None:
        return AppError(404, "not_found", "The requested resource was not found.")
    label = resource.replace("_", " ")
    return AppError(404, "not_found", f"The {label} was not found.", {"resource": resource})


def conflict(field: str = "name", message: str = "That name is already in use.") -> AppError:
    return AppError(409, "conflict", message, {"field": field})


def validation_error(errors: Sequence[Mapping[str, Any]]) -> AppError:
    """A ``validation_error`` with ``details.errors`` items carrying only loc, msg and type."""
    return AppError(422, "validation_error", VALIDATION_MESSAGE, {"errors": clean_errors(errors)})


def field_error(loc: Sequence[str | int], msg: str, type_: str = "value_error") -> AppError:
    return validation_error([{"loc": list(loc), "msg": msg, "type": type_}])


def limit_exceeded(limit: str, maximum: int | float, message: str | None = None) -> AppError:
    return AppError(
        422,
        "limit_exceeded",
        message or f"The configured limit {limit} ({maximum}) would be exceeded.",
        {"limit": limit, "max": maximum},
    )


def unknown_model(model: str) -> AppError:
    return AppError(422, "unknown_model", "The model is not in the catalog.", {"model": model})


def provider_not_configured(provider: str, model: str) -> AppError:
    return AppError(
        422,
        "provider_not_configured",
        "The model's provider is not configured on this server.",
        {"provider": provider, "model": model},
    )


def invalid_parameter(param: str, message: str, maximum: int | float | None = None) -> AppError:
    details: dict[str, Any] = {"param": param}
    if maximum is not None:
        details["max"] = maximum
    return AppError(422, "invalid_parameter", message, details)


def missing_variables(missing: Sequence[str], **extra: Any) -> AppError:
    names = sorted(set(missing))
    return AppError(
        422,
        "missing_variables",
        "Some template variables have no value: " + ", ".join(names) + ".",
        {"missing": names, **extra},
    )


def invalid_assertion(reason: str, assertion_index: int, **extra: Any) -> AppError:
    return AppError(
        422,
        "invalid_assertion",
        "An assertion is invalid: " + reason,
        {"assertion_index": assertion_index, "reason": reason, **extra},
    )


def clean_errors(errors: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep only ``loc``, ``msg`` and ``type`` (never the rejected input or context)."""
    cleaned: list[dict[str, Any]] = []
    for err in errors:
        loc = [part if isinstance(part, int | str) else str(part) for part in err.get("loc", ())]
        cleaned.append(
            {"loc": loc, "msg": str(err.get("msg", "")), "type": str(err.get("type", ""))}
        )
    return cleaned


def from_pydantic(exc: ValidationError, prefix: Sequence[str | int] = ("body",)) -> AppError:
    """Convert a manual ``model_validate`` failure into a ``validation_error``."""
    return validation_error(
        [
            {"loc": [*prefix, *err["loc"]], "msg": err["msg"], "type": err["type"]}
            for err in exc.errors(include_url=False, include_input=False, include_context=False)
        ]
    )


# ---- provider errors -------------------------------------------------------------------------

_PROVIDER_STATUS: dict[ProviderErrorKind, tuple[int, str]] = {
    ProviderErrorKind.AUTH: (502, "provider_auth_error"),
    ProviderErrorKind.RATE_LIMITED: (429, "provider_rate_limited"),
    ProviderErrorKind.OVERLOADED: (503, "provider_overloaded"),
    ProviderErrorKind.INVALID_REQUEST: (400, "provider_invalid_request"),
    ProviderErrorKind.TIMEOUT: (504, "provider_timeout"),
    ProviderErrorKind.PROVIDER_ERROR: (502, "provider_error"),
}


def retry_after_seconds(value: float | None) -> int:
    """Integer seconds (>= 1) for a ``Retry-After`` header."""
    if value is None:
        return DEFAULT_PROVIDER_RETRY_AFTER
    return max(1, math.ceil(value))


def provider_app_error(error: ProviderError, **extra: Any) -> AppError:
    """Map a :class:`ProviderError` to its HTTP status, code, safe message and details."""
    status, code = _PROVIDER_STATUS[error.kind]
    details: dict[str, Any] = {"provider": error.provider.value}
    headers: dict[str, str] = {}
    if error.kind is not ProviderErrorKind.TIMEOUT:
        details["provider_request_id"] = error.provider_request_id
    if error.kind in {ProviderErrorKind.RATE_LIMITED, ProviderErrorKind.OVERLOADED}:
        seconds = retry_after_seconds(error.retry_after)
        details["retry_after"] = seconds
        headers["Retry-After"] = str(seconds)
    if error.kind is ProviderErrorKind.INVALID_REQUEST and error.param:
        details["param"] = error.param
    details.update(extra)
    return AppError(status, code, error.message, details, headers)


# ---- exception handlers ----------------------------------------------------------------------


async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    err = validation_error(exc.errors())
    return error_response(err.status_code, err.code, err.message, err.details)


_HTTP_CODES: dict[int, tuple[str, str]] = {
    401: ("unauthorized", "Authentication is required."),
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "The method is not allowed for this resource."),
    413: ("payload_too_large", "The request body is too large."),
    429: ("rate_limited", "Too many requests. Try again later."),
}


def allowed_methods(request: Request) -> list[str]:
    """Every method some route accepts for the request's path.

    Starlette builds a 405's ``Allow`` header from the first route whose path matches, so a
    path served by several routes (``GET`` and ``POST /api/prompts``) would list only one of
    them. RFC 9110 requires all of them.
    """
    allowed: list[str] = []
    for method in HTTP_METHODS:
        scope = {**request.scope, "method": method}
        if any(route.matches(scope)[0] == Match.FULL for route in request.app.router.routes):
            allowed.append(method)
    return allowed


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    headers = dict(exc.headers or {})
    if exc.status_code == 405:
        methods = allowed_methods(request)
        if methods:
            headers["Allow"] = ", ".join(methods)
    if exc.status_code == 400:
        # FastAPI raises 400 when a body cannot be decoded at all (e.g. invalid UTF-8).
        err = field_error(["body"], "The request body could not be parsed.", "json_invalid")
        return error_response(err.status_code, err.code, err.message, err.details)
    code, message = _HTTP_CODES.get(
        exc.status_code,
        ("internal_error" if exc.status_code >= 500 else "bad_request", "The request failed."),
    )
    return error_response(exc.status_code, code, message, headers=headers)


def install_exception_handlers(app: FastAPI) -> None:
    """Register envelope-producing handlers (unhandled exceptions: see the request middleware)."""
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
