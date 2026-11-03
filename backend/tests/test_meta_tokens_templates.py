"""Health, readiness, meta, models, token estimates and template endpoints."""

from __future__ import annotations

from app.providers.base import ProviderName
from app.services.tokens import EXACT_COUNT_FAILED, estimate, estimate_request
from tests.fakes import ScriptedProvider

ANTHROPIC = ProviderName.ANTHROPIC


async def test_health_and_ready(client) -> None:
    health = (await client.get("/api/health")).json()
    assert health["status"] == "ok"
    assert health["version"] == "2.0.0"
    assert health["time"].endswith("Z")
    assert len(health["time"]) == len("2026-11-03T09:15:02.123456Z")
    ready = await client.get("/api/ready")
    assert ready.json() == {"status": "ready", "checks": {"database": "ok"}}


async def test_ready_fails_when_database_is_down(make_app) -> None:
    from tests.conftest import running_client

    app = make_app()
    async with running_client(app) as http:
        state = app.state.studio

        async def broken_ping() -> bool:
            return False

        state.db.ping = broken_ping
        response = await http.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "not_ready",
        "message": "The service is not ready.",
        "details": {"checks": {"database": "error"}},
    }


async def test_database_ping_reports_failures() -> None:
    from app.db import Database

    broken = Database("sqlite+aiosqlite:////nonexistent-dir/sub/x.db")
    assert not await broken.ping()
    await broken.dispose()


async def test_meta_in_demo_mode(client) -> None:
    meta = (await client.get("/api/meta")).json()
    assert meta["name"] == "Prompt Engineering Studio"
    assert meta["version"] == "2.0.0"
    assert meta["auth_required"] is False
    assert meta["demo_mode"] is True
    assert meta["default_model"] == "demo-concise"
    assert meta["providers"] == [
        {"id": "anthropic", "display_name": "Anthropic", "configured": False},
        {"id": "openai", "display_name": "OpenAI", "configured": False},
        {"id": "gemini", "display_name": "Google Gemini", "configured": False},
        {"id": "demo", "display_name": "Demo", "configured": True},
    ]
    assert meta["limits"]["max_compare_cells"] == 12
    assert set(meta["limits"]) >= {"max_body_bytes", "import_max_bytes", "request_timeout_seconds"}


async def test_meta_without_demo(make_client) -> None:
    providers = {ANTHROPIC: ScriptedProvider(ANTHROPIC)}
    async with make_client(providers, demo_enabled=False) as http:
        meta = (await http.get("/api/meta")).json()
        assert [p["id"] for p in meta["providers"]] == ["anthropic", "openai", "gemini"]
        assert meta["demo_mode"] is False
        assert meta["default_model"] == "claude-opus-5-5"


async def test_models_listing(make_client) -> None:
    providers = {ANTHROPIC: ScriptedProvider(ANTHROPIC)}
    async with make_client(providers, max_output_tokens=8000) as http:
        body = (await http.get("/api/models")).json()
        assert body["default_model"] == "claude-opus-5-5"
        models = {m["id"]: m for m in body["models"]}
        assert [m["is_default"] for m in body["models"]].count(True) == 1
        opus = models["claude-opus-5-5"]
        assert opus["available"]
        assert opus["is_default"]
        assert opus["thinking_always_on"] is True
        assert opus["supports_temperature"] is False
        assert opus["max_output_tokens"] == 8000
        assert opus["context_window"] == 1_000_000
        assert opus["pricing"] == {
            "currency": "USD",
            "input_per_mtok": 4.0,
            "output_per_mtok": 20.0,
            "long_context": None,
        }
        assert models["claude-haiku-5-5"]["pricing"]["long_context"] == {
            "threshold_input_tokens": 100000,
            "input_per_mtok": 0.5,
            "output_per_mtok": 2.5,
        }
        assert models["gpt-5.5"]["available"] is False
        assert models["gpt-5.5"]["pricing"] is None
        assert models["demo-concise"]["available"] is True
        assert models["demo-concise"]["max_output_tokens"] == 4096


def test_heuristic_estimate() -> None:
    assert estimate("") == 0
    assert estimate(None) == 0
    assert estimate("abc") == 1
    assert estimate("abcde") == 2
    assert estimate_request("abcd", "abcdefgh") == 3


async def test_token_estimate_heuristic(client) -> None:
    response = await client.post(
        "/api/tokens/estimate",
        json={"system": "Be {{tone|kind}}.", "prompt": "Hello {{name}} there", "variables": {}},
    )
    body = response.json()
    assert body["method"] == "heuristic"
    assert body["model"] == "demo-concise"
    assert body["provider"] == "demo"
    combined = "Be kind.\nHello {{name}} there"
    assert body["characters"] == len(combined)
    assert body["words"] == 5
    assert body["input_tokens"] == estimate("Be kind.") + estimate("Hello {{name}} there")
    assert body["warnings"] == []


async def test_token_estimate_for_unconfigured_anthropic_uses_heuristic(client) -> None:
    body = (
        await client.post("/api/tokens/estimate", json={"model": "claude-opus-5-5", "prompt": "hi"})
    ).json()
    assert body["method"] == "heuristic"
    assert body["warnings"] == []
    unknown = await client.post("/api/tokens/estimate", json={"model": "x", "prompt": "hi"})
    assert unknown.json()["error"]["code"] == "unknown_model"


async def test_token_estimate_exact_count(make_client) -> None:
    fake = ScriptedProvider(ANTHROPIC, count=321)
    async with make_client({ANTHROPIC: fake}) as http:
        body = (
            await http.post("/api/tokens/estimate", json={"system": " ", "prompt": "hi"})
        ).json()
        assert body["method"] == "anthropic_count_tokens"
        assert body["input_tokens"] == 321
        assert fake.count_calls[0].system is None
        assert body["characters"] == 2


async def test_token_estimate_fallback_warning(make_client) -> None:
    async with make_client({ANTHROPIC: ScriptedProvider(ANTHROPIC, count=None)}) as http:
        body = (await http.post("/api/tokens/estimate", json={"prompt": "hello"})).json()
        assert body["method"] == "heuristic"
        assert body["warnings"] == [EXACT_COUNT_FAILED]
        assert body["input_tokens"] == 2

    from app.providers.base import ProviderError, ProviderErrorKind

    failing = ScriptedProvider(
        ANTHROPIC, count_error=ProviderError(ProviderErrorKind.TIMEOUT, ANTHROPIC)
    )
    async with make_client({ANTHROPIC: failing}) as http:
        body = (await http.post("/api/tokens/estimate", json={"prompt": "hello"})).json()
        assert body["warnings"] == [EXACT_COUNT_FAILED]


async def test_templates_listing(client) -> None:
    templates = (await client.get("/api/templates")).json()["templates"]
    assert len(templates) == 10
    first = templates[0]
    assert first == {
        "id": "summarizer",
        "name": "Summarizer",
        "description": first["description"],
        "tags": ["writing"],
        "system": "You are a concise summarizer.",
        "prompt": "Summarize the following text in 3 bullet points:\n\n{{text}}",
        "variables": [{"name": "text", "default": None, "required": True}],
    }


async def test_render_strict_and_lenient(client) -> None:
    strict = await client.post(
        "/api/templates/render", json={"prompt": "{{a}} {{b}} {{c|z}}", "variables": {"a": "1"}}
    )
    assert strict.status_code == 422
    assert strict.json()["error"]["details"]["missing"] == ["b"]
    lenient = await client.post(
        "/api/templates/render",
        json={
            "system": "{{a}}",
            "prompt": "{{a}} {{b}} {{c|z}}",
            "variables": {"a": "1"},
            "strict": False,
        },
    )
    assert lenient.json() == {
        "system": "1",
        "prompt": "1 {{b}} z",
        "variables": [
            {"name": "a", "default": None, "required": True},
            {"name": "b", "default": None, "required": True},
            {"name": "c", "default": "z", "required": False},
        ],
        "missing": ["b"],
    }
