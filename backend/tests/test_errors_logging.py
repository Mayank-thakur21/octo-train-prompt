"""Error envelopes, body limits, unhandled errors, and structured logging with redaction."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi import APIRouter

from app.errors import AppError, provider_app_error, retry_after_seconds
from app.logging_config import (
    REDACTED,
    JsonFormatter,
    Redactor,
    RequestIdFilter,
    TextFormatter,
    configure_logging,
    request_id_var,
)
from app.providers.base import ProviderError, ProviderErrorKind, ProviderName
from tests.conftest import running_client


async def test_unknown_route_and_wrong_method(client) -> None:
    missing = await client.get("/api/does-not-exist")
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {"code": "not_found", "message": "The requested resource was not found."}
    }
    assert "x-request-id" in missing.headers
    wrong = await client.put("/api/health")
    assert wrong.status_code == 405
    assert wrong.json()["error"]["code"] == "method_not_allowed"
    assert wrong.headers["allow"] == "GET"


async def test_method_not_allowed_lists_every_route_of_the_path(client) -> None:
    # GET and POST /api/prompts are separate routes; Starlette named only the first one.
    listing = await client.put("/api/prompts")
    assert listing.status_code == 405
    assert listing.headers["allow"] == "GET, POST"
    item = await client.post(f"/api/prompts/{'a' * 32}")
    assert item.status_code == 405
    assert item.headers["allow"] == "GET, PATCH, DELETE"


async def test_validation_errors_do_not_echo_input(client) -> None:
    response = await client.post(
        "/api/runs", json={"prompt": "", "temperature": 9, "secret_field": "sk-ant-hidden-value"}
    )
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["message"] == "Request validation failed."
    for item in body["details"]["errors"]:
        assert set(item) == {"loc", "msg", "type"}
    assert "sk-ant-hidden-value" not in response.text
    locs = [tuple(item["loc"]) for item in body["details"]["errors"]]
    assert ("body", "prompt") in locs
    assert ("body", "secret_field") in locs


async def test_malformed_json_and_undecodable_body(client) -> None:
    broken = await client.post(
        "/api/runs", content=b'{"prompt": ', headers={"content-type": "application/json"}
    )
    assert broken.status_code == 422
    assert broken.json()["error"]["details"]["errors"][0]["type"] == "json_invalid"
    binary = await client.post(
        "/api/runs", content=b"\xff\xfe\x00", headers={"content-type": "application/json"}
    )
    assert binary.status_code == 422
    assert binary.json()["error"]["code"] == "validation_error"


async def test_payload_too_large_by_content_length(make_client) -> None:
    async with make_client(max_body_bytes=2048) as http:
        response = await http.post("/api/runs", json={"prompt": "x" * 5000})
        assert response.status_code == 413
        error = response.json()["error"]
        assert error["code"] == "payload_too_large"
        assert error["details"] == {"max_bytes": 2048}
        assert "x-request-id" in response.headers
        small = await http.post("/api/runs", json={"prompt": "hi"})
        assert small.status_code == 200


async def test_payload_too_large_chunked(make_client) -> None:
    async def chunks():
        for _ in range(4):
            yield b"x" * 1024

    async with make_client(max_body_bytes=2048) as http:
        response = await http.post(
            "/api/runs", content=chunks(), headers={"content-type": "application/json"}
        )
        assert response.status_code == 413

    async def small_chunks():
        yield b'{"prompt": '
        yield b'"chunked"}'

    async with make_client(max_body_bytes=2048) as http:
        response = await http.post(
            "/api/runs", content=small_chunks(), headers={"content-type": "application/json"}
        )
        assert response.status_code == 200
        assert response.json()["rendered_prompt"] == "chunked"


async def test_import_has_its_own_body_limit(make_client) -> None:
    async with make_client(max_body_bytes=1024, import_max_bytes=4096) as http:
        document = {
            "format": "prompt-studio-export",
            "format_version": 1,
            "prompts": [],
            "suites": [],
            "history": [],
            "padding": "x" * 2000,
        }
        allowed = await http.post("/api/import", json=document)
        assert allowed.status_code == 422  # passes the size check, then fails validation
        document["padding"] = "x" * 5000
        rejected = await http.post("/api/import", json=document)
        assert rejected.status_code == 413
        assert rejected.json()["error"]["details"]["max_bytes"] == 4096


async def test_unhandled_exception_returns_500_envelope(make_app, caplog) -> None:
    app = make_app()
    router = APIRouter()

    @router.get("/api/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    app.include_router(router)
    async with running_client(app) as http:
        response = await http.get("/api/boom", headers={"X-Request-ID": "req-500"})
    assert response.status_code == 500
    body = response.json()["error"]
    assert body == {
        "code": "internal_error",
        "message": "An unexpected error occurred.",
        "details": {"request_id": "req-500"},
    }
    assert "hunter2" not in response.text
    assert "Traceback" not in response.text
    assert response.headers["x-request-id"] == "req-500"
    assert response.headers["x-frame-options"] == "DENY"
    assert "hunter2" in caplog.text  # logged server-side with the traceback


async def test_other_http_exceptions_get_envelopes(make_app) -> None:
    from starlette.exceptions import HTTPException

    app = make_app()
    router = APIRouter()

    @router.get("/api/teapot")
    async def teapot() -> None:
        raise HTTPException(status_code=418)

    @router.get("/api/unavailable")
    async def unavailable() -> None:
        raise HTTPException(status_code=503)

    app.include_router(router)
    async with running_client(app) as http:
        teapot_response = await http.get("/api/teapot")
        unavailable_response = await http.get("/api/unavailable")
    assert teapot_response.json()["error"]["code"] == "bad_request"
    assert unavailable_response.json()["error"]["code"] == "internal_error"


def test_provider_error_mapping() -> None:
    error = provider_app_error(
        ProviderError(
            ProviderErrorKind.RATE_LIMITED,
            ProviderName.ANTHROPIC,
            retry_after=2.2,
            provider_request_id="req_1",
        )
    )
    assert (error.status_code, error.code) == (429, "provider_rate_limited")
    assert error.headers == {"Retry-After": "3"}
    assert error.details == {
        "provider": "anthropic",
        "provider_request_id": "req_1",
        "retry_after": 3,
    }
    timeout = provider_app_error(ProviderError(ProviderErrorKind.TIMEOUT, ProviderName.OPENAI))
    assert (timeout.status_code, timeout.code, timeout.details) == (
        504,
        "provider_timeout",
        {"provider": "openai"},
    )
    invalid = provider_app_error(
        ProviderError(ProviderErrorKind.INVALID_REQUEST, ProviderName.OPENAI, param="temperature")
    )
    assert invalid.status_code == 400
    assert invalid.details is not None
    assert invalid.details["param"] == "temperature"
    assert retry_after_seconds(None) == 30
    assert retry_after_seconds(0.1) == 1
    copy = AppError(400, "x", "y").with_details(a=1)
    assert copy.details == {"a": 1}


# ---- logging ---------------------------------------------------------------------------------


def record(message: str, **extra: object) -> logging.LogRecord:
    rec = logging.LogRecord("app.test", logging.WARNING, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(rec, key, value)
    return rec


def test_redactor_patterns_and_secrets() -> None:
    redact = Redactor(["configured-secret-value", 'quote"secret', ""])
    text = (
        "keys: sk-ant-abcdefgh123 sk-abcdefghijklmnop1234 AIzaSyA1234567890abcdefghij "
        "x-api-key: topsecret Authorization=Bearer configured-secret-value "
        'and {"k": "quote\\"secret"}'
    )
    cleaned = redact(text)
    for leaked in (
        "sk-ant-abcdefgh123",
        "sk-abcdefghijklmnop1234",
        "AIzaSyA1234567890abcdefghij",
        "topsecret",
        "configured-secret-value",
        'quote\\"secret',
    ):
        assert leaked not in cleaned
    assert REDACTED in cleaned


def test_json_formatter_includes_extra_and_request_id() -> None:
    formatter = JsonFormatter(Redactor(["hunter2"]))
    token = request_id_var.set("rid-1")
    try:
        rec = record("login failed for hunter2", provider="anthropic", status=401)
        RequestIdFilter().filter(rec)
        data = json.loads(formatter.format(rec))
    finally:
        request_id_var.reset(token)
    assert data["level"] == "WARNING"
    assert data["logger"] == "app.test"
    assert data["request_id"] == "rid-1"
    assert data["provider"] == "anthropic"
    assert data["status"] == 401
    assert "hunter2" not in data["message"]
    assert data["ts"].endswith("+00:00")


def test_json_formatter_exceptions_are_redacted() -> None:
    formatter = JsonFormatter(Redactor(["s3cr3t-token"]))
    try:
        raise ValueError("bad s3cr3t-token")
    except ValueError:
        import sys

        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "oops", None, sys.exc_info())
    line = formatter.format(rec)
    assert "s3cr3t-token" not in line
    assert "ValueError" in json.loads(line)["exception"]
    assert "request_id" not in json.loads(line)


def test_text_formatter() -> None:
    formatter = TextFormatter(Redactor(["hunter2"]))
    line = formatter.format(record("password hunter2"))
    assert "WARNING app.test [-] password [REDACTED]" in line


def test_configure_logging_replaces_its_handler(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    configure_logging("INFO", "json", ["abc123secret"])
    configure_logging("INFO", "json", ["abc123secret"])
    assert _app_handler_count(root) == 1
    logging.getLogger("app.test").info("hello abc123secret")
    err = capsys.readouterr().err
    line = next(line for line in err.splitlines() if "hello" in line)
    assert json.loads(line)["message"] == "hello [REDACTED]"
    assert logging.getLogger("anthropic").level == logging.WARNING
    configure_logging("WARNING", "text")


def _app_handler_count(root: logging.Logger) -> int:
    return sum(1 for handler in root.handlers if getattr(handler, "_prompt_studio_handler", False))


async def test_access_log_fields(client, caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    await client.get("/api/health?token=abc")
    entries = [rec for rec in caplog.records if rec.name == "app.access"]
    assert entries
    rec = entries[-1]
    assert rec.method == "GET"
    assert rec.path == "/api/health"
    assert rec.status == 200
    assert rec.client_ip == "127.0.0.1"
    assert isinstance(rec.duration_ms, float)
