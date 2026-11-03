"""Structured logging (JSON or text) with request ids and secret redaction.

Redaction runs on the final formatted line, so secrets are removed from messages, ``extra``
fields and tracebacks alike.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Iterable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

REDACTED = "[REDACTED]"

#: Request id of the request being handled (set by the request middleware).
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?i)(x-api-key|authorization)[\"']?\s*[:=]\s*[\"']?[^\s\"',]+"),
)

TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"

SDK_LOGGERS = ("anthropic", "openai", "google_genai", "httpx2", "httpx", "httpcore", "httpcore2")

# Attributes every LogRecord has; anything else was passed through ``extra=``.
_RESERVED = frozenset(
    vars(logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)).keys()
    | {"message", "asctime", "request_id", "taskName"}
)


class Redactor:
    """Replaces configured secret values and key-like patterns with ``[REDACTED]``."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        values: set[str] = set()
        for secret in secrets:
            if secret:
                values.add(secret)
                escaped = json.dumps(secret)[1:-1]
                if escaped != secret:
                    values.add(escaped)
        # Longest first so a secret containing another one is replaced whole.
        self._values = sorted(values, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for value in self._values:
            text = text.replace(value, REDACTED)
        for pattern in SECRET_PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text


class RequestIdFilter(logging.Filter):
    """Adds ``record.request_id`` from the context variable (``-`` outside requests)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get() or "-"
        return True


class TextFormatter(logging.Formatter):
    def __init__(self, redactor: Redactor) -> None:
        super().__init__(TEXT_FORMAT)
        self._redact = redactor

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get() or "-"
        return self._redact(super().format(record))


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, message, request_id and extra fields."""

    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self._redact = redactor

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or request_id_var.get()
        if request_id and request_id != "-":
            payload["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        line = json.dumps(payload, default=str, ensure_ascii=False)
        return self._redact(line)


_HANDLER_FLAG = "_prompt_studio_handler"


def configure_logging(level: str, fmt: str, secrets: Iterable[str] = ()) -> None:
    """Install the app's handler on the root logger (replacing a previous one from this app)."""
    redactor = Redactor(secrets)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter(redactor) if fmt == "json" else TextFormatter(redactor))
    handler.addFilter(RequestIdFilter())
    setattr(handler, _HANDLER_FLAG, True)

    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_FLAG, False):
            root.removeHandler(existing)
            existing.close()
    root.addHandler(handler)
    root.setLevel(level)
    for name in SDK_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
