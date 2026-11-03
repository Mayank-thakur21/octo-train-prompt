"""Runs: validation, provider errors, history persistence and the SSE protocol."""

from __future__ import annotations

import asyncio

import pytest

from app.providers.base import ProviderError, ProviderErrorKind, ProviderName
from app.schemas import RunRequest
from app.services import runner
from tests.fakes import Script, ScriptedProvider, parse_sse

ANTHROPIC = ProviderName.ANTHROPIC
OPENAI = ProviderName.OPENAI


def claude(script: Script | None = None, **kwargs) -> dict[ProviderName, ScriptedProvider]:
    return {ANTHROPIC: ScriptedProvider(ANTHROPIC, script, **kwargs)}


async def test_run_success_saves_history(make_client) -> None:
    providers = claude(Script(text="Hi Ada", input_tokens=1000, output_tokens=500))
    async with make_client(providers) as http:
        response = await http.post(
            "/api/runs",
            json={
                "system": "Greet {{name}}.",
                "prompt": "Say hi to {{name}}",
                "variables": {"name": "Ada"},
                "thinking": True,
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["model"] == "claude-opus-5-5"
        assert result["provider"] == "anthropic"
        assert result["text"] == "Hi Ada"
        assert result["rendered_system"] == "Greet Ada."
        assert result["rendered_prompt"] == "Say hi to Ada"
        assert result["params"] == {"temperature": None, "max_tokens": 4096, "thinking": True}
        assert result["cost_usd"] == round(1000 / 1e6 * 4 + 500 / 1e6 * 20, 6)
        assert result["warnings"] == []
        assert result["created_at"].endswith("Z")
        sent = providers[ANTHROPIC].calls[0]
        assert sent.system == "Greet Ada."
        assert sent.thinking is True
        assert sent.temperature is None

        detail = (await http.get(f"/api/history/{result['id']}")).json()
        assert detail["status"] == "success"
        assert detail["source"] == "run"
        assert detail["variables"] == {"name": "Ada"}
        assert detail["system_template"] == "Greet {{name}}."
        assert detail["output"] == "Hi Ada"
        assert detail["cost_usd"] == result["cost_usd"]


async def test_unsupported_params_are_dropped_with_warnings(make_client) -> None:
    async with make_client(claude()) as http:
        response = await http.post("/api/runs", json={"prompt": "hi", "temperature": 0.5})
        body = response.json()
        assert body["warnings"] == [
            "temperature is not supported by Claude Opus 5.5 and was ignored."
        ]
        assert body["params"]["temperature"] is None
    openai = {OPENAI: ScriptedProvider(OPENAI)}
    async with make_client(openai, openai_models="gpt-4.1-mini") as http:
        response = await http.post(
            "/api/runs",
            json={"model": "gpt-4.1-mini", "prompt": "hi", "temperature": 0.5, "thinking": True},
        )
        body = response.json()
        assert body["warnings"] == ["thinking is not supported by GPT-4.1 mini and was ignored."]
        assert body["params"] == {"temperature": 0.5, "max_tokens": 4096, "thinking": False}
        assert openai[OPENAI].calls[0].temperature == 0.5


async def test_empty_system_is_none_and_save_history_false(client) -> None:
    response = await client.post(
        "/api/runs", json={"system": "{{s|}}  ", "prompt": "hi", "save_history": False}
    )
    body = response.json()
    assert body["id"] is None
    assert body["rendered_system"] is None
    assert (await client.get("/api/history")).json()["total"] == 0


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"prompt": "hi", "model": "nope"}, 422, "unknown_model"),
        ({"prompt": "hi", "model": "claude-opus-5-5"}, 422, "provider_not_configured"),
        ({"prompt": "Hi {{who}} {{also}}"}, 422, "missing_variables"),
        ({"prompt": "hi", "max_tokens": 5000}, 422, "invalid_parameter"),
        ({"prompt": "hi", "max_tokens": 999999}, 422, "validation_error"),
        ({"prompt": "hi", "prompt_version_id": "f" * 32}, 404, "not_found"),
        ({"prompt": "hi", "variables": {"bad key": "x"}}, 422, "validation_error"),
    ],
)
async def test_run_validation(client, payload, status: int, code: str) -> None:
    response = await client.post("/api/runs", json=payload)
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    if code == "missing_variables":
        assert error["details"]["missing"] == ["also", "who"]
    if code == "unknown_model":
        assert error["details"]["model"] == "nope"
    if code == "provider_not_configured":
        assert error["details"] == {"provider": "anthropic", "model": "claude-opus-5-5"}
    if code == "invalid_parameter":
        assert error["details"] == {"param": "max_tokens", "max": 4096}


async def test_configured_size_limits(make_client) -> None:
    async with make_client(
        max_prompt_chars=10, max_system_chars=5, max_variables=1, max_variable_value_chars=3
    ) as http:
        long_prompt = await http.post("/api/runs", json={"prompt": "x" * 11, "system": "y" * 6})
        locs = [e["loc"] for e in long_prompt.json()["error"]["details"]["errors"]]
        assert locs == [["body", "prompt"], ["body", "system"]]
        too_many = await http.post(
            "/api/runs", json={"prompt": "hi", "variables": {"a": "1", "b": "2"}}
        )
        assert too_many.json()["error"]["code"] == "validation_error"
        too_long = await http.post("/api/runs", json={"prompt": "hi", "variables": {"a": "1234"}})
        assert too_long.json()["error"]["details"]["errors"][0]["loc"] == ["body", "variables", "a"]
    async with make_client(max_rendered_chars=10) as http:
        response = await http.post(
            "/api/runs", json={"prompt": "{{v}}", "variables": {"v": "x" * 20}}
        )
        assert response.json()["error"] == {
            "code": "limit_exceeded",
            "message": "The rendered prompt is too long.",
            "details": {"limit": "max_rendered_chars", "max": 10},
        }


async def test_prompt_version_link(client) -> None:
    created = (await client.post("/api/prompts", json={"name": "P", "prompt": "hi"})).json()
    version_id = created["latest_version"]["id"]
    run = await client.post("/api/runs", json={"prompt": "hi", "prompt_version_id": version_id})
    history = (await client.get(f"/api/history/{run.json()['id']}")).json()
    assert history["prompt_version_id"] == version_id


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        (ProviderErrorKind.AUTH, 502, "provider_auth_error"),
        (ProviderErrorKind.RATE_LIMITED, 429, "provider_rate_limited"),
        (ProviderErrorKind.OVERLOADED, 503, "provider_overloaded"),
        (ProviderErrorKind.INVALID_REQUEST, 400, "provider_invalid_request"),
        (ProviderErrorKind.TIMEOUT, 504, "provider_timeout"),
        (ProviderErrorKind.PROVIDER_ERROR, 502, "provider_error"),
    ],
)
async def test_provider_errors_persist_history(make_client, kind, status: int, code: str) -> None:
    error = ProviderError(kind, ANTHROPIC, retry_after=5, provider_request_id="req_9")
    async with make_client(claude(Script(error=error))) as http:
        response = await http.post("/api/runs", json={"prompt": "hi"})
        assert response.status_code == status
        body = response.json()["error"]
        assert body["code"] == code
        assert body["details"]["provider"] == "anthropic"
        run_id = body["details"]["run_id"]
        if kind in {ProviderErrorKind.RATE_LIMITED, ProviderErrorKind.OVERLOADED}:
            assert response.headers["retry-after"] == "5"
            assert body["details"]["retry_after"] == 5
        history = (await http.get(f"/api/history/{run_id}")).json()
        assert history["status"] == "error"
        assert history["error_code"] == code
        assert history["error_message"] == body["message"]


async def test_provider_error_without_history(make_client) -> None:
    error = ProviderError(ProviderErrorKind.AUTH, ANTHROPIC)
    async with make_client(claude(Script(error=error))) as http:
        response = await http.post("/api/runs", json={"prompt": "hi", "save_history": False})
        assert response.status_code == 502
        assert "run_id" not in response.json()["error"]["details"]


async def test_run_timeout(make_client) -> None:
    async with make_client(claude(Script(delay=2)), request_timeout_seconds=1) as http:
        response = await http.post("/api/runs", json={"prompt": "hi"})
        assert response.status_code == 504
        assert response.json()["error"]["code"] == "provider_timeout"


# ---- streaming ---------------------------------------------------------------------------------


async def test_stream_event_order_and_payloads(make_client) -> None:
    providers = claude(Script(text="Hello brave world", thinking="Pondering"))
    async with make_client(providers) as http:
        response = await http.post("/api/runs/stream", json={"prompt": "hi", "thinking": True})
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
        assert response.headers["cache-control"] == "no-cache, no-transform"
        assert response.headers["x-accel-buffering"] == "no"
        assert "x-request-id" in response.headers
        events = parse_sse(response.text)
        names = [name for name, _ in events]
        assert names == ["start", "delta", "delta", "delta", "delta", "done"]
        start = events[0][1]
        assert start["model"] == "claude-opus-5-5"
        assert len(start["run_id"]) == 32
        assert events[1][1] == {"type": "thinking", "text": "Pondering"}
        assert [data["text"] for _, data in events[2:5]] == ["Hello ", "brave ", "world"]
        done = events[-1][1]
        assert done["text"] == "Hello brave world"
        assert done["id"] == start["run_id"]
        assert done["ttft_ms"] == 7
        history = (await http.get(f"/api/history/{start['run_id']}")).json()
        assert history["status"] == "success"
        assert history["thinking"] == "Pondering"
        assert history["ttft_ms"] == 7


async def test_stream_frames_are_single_line_json(client) -> None:
    response = await client.post("/api/runs/stream", json={"prompt": "line one\nline two"})
    for frame in response.text.split("\n\n"):
        if frame:
            lines = frame.split("\n")
            assert lines[0].startswith("event: ")
            assert len(lines) == 2
            assert lines[1].startswith("data: ")


async def test_stream_error_after_deltas(make_client) -> None:
    error = ProviderError(ProviderErrorKind.OVERLOADED, ANTHROPIC, retry_after=3)
    providers = claude(Script(text="one two three", error=error, error_after_chunks=2))
    async with make_client(providers) as http:
        response = await http.post("/api/runs/stream", json={"prompt": "hi"})
        events = parse_sse(response.text)
        assert [name for name, _ in events] == ["start", "delta", "delta", "error"]
        envelope = events[-1][1]
        assert envelope["error"]["code"] == "provider_overloaded"
        run_id = envelope["error"]["details"]["run_id"]
        assert run_id == events[0][1]["run_id"]
        history = (await http.get(f"/api/history/{run_id}")).json()
        assert history["status"] == "error"
        assert history["output"] == "one two "
        assert history["error_code"] == "provider_overloaded"


async def test_stream_pre_stream_errors_are_json(client) -> None:
    response = await client.post("/api/runs/stream", json={"prompt": "{{x}}"})
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/json"
    assert response.json()["error"]["code"] == "missing_variables"


async def test_stream_timeout_becomes_error_event(make_client) -> None:
    providers = claude(Script(delay=1.5))
    async with make_client(providers, request_timeout_seconds=1) as http:
        response = await http.post("/api/runs/stream", json={"prompt": "hi", "save_history": False})
        events = parse_sse(response.text)
        assert events[0][1]["run_id"] is None
        assert events[-1][0] == "error"
        assert events[-1][1]["error"]["code"] == "provider_timeout"
        assert "run_id" not in events[-1][1]["error"]["details"]


async def test_stream_keepalive_ping(make_client) -> None:
    async with make_client(sse_keepalive_seconds=0.05) as http:
        response = await http.post("/api/runs/stream", json={"prompt": "[[demo:delay=300]] hi"})
        events = parse_sse(response.text)
        assert (":", "ping") in events
        assert events[-1][0] == "done"


async def test_stream_unexpected_failure(make_client) -> None:
    class Exploding(ScriptedProvider):
        async def stream(self, req):
            await asyncio.sleep(0)
            if req.prompt:
                raise RuntimeError("kaboom")
            yield  # pragma: no cover - only makes this an async generator

    async with make_client({ANTHROPIC: Exploding(ANTHROPIC)}) as http:
        response = await http.post("/api/runs/stream", json={"prompt": "hi"})
        events = parse_sse(response.text)
        assert events[-1][0] == "error"
        assert events[-1][1]["error"]["code"] == "internal_error"
        assert "kaboom" not in response.text
        run_id = events[-1][1]["error"]["details"]["run_id"]
        history = (await http.get(f"/api/history/{run_id}")).json()
        assert history["error_code"] == "internal_error"


async def test_stream_generator_close_saves_cancelled_row(make_app) -> None:
    """Closing the generator (client disconnect) cancels the call and records partial text."""
    from tests.conftest import running_client

    providers = claude(Script(text="partial words that never finish"))
    app = make_app(providers)
    async with running_client(app) as http:
        state = app.state.studio
        prepared = await runner.prepare_run(state, RunRequest(prompt="hi"))
        frames = runner.stream_run(state, prepared)
        first = await anext(frames)
        assert first.startswith("event: start")
        second = await anext(frames)
        assert "partial " in second
        await frames.aclose()
        run_id = parse_sse(first)[0][1]["run_id"]
        history = (await http.get(f"/api/history/{run_id}")).json()
        assert history["status"] == "cancelled"
        assert history["output"] == "partial "
        assert history["finish_reason"] is None


async def test_stream_task_cancellation_saves_cancelled_row(make_app) -> None:
    from app.sse import with_keepalive
    from tests.conftest import running_client

    providers = claude(Script(text="slow", delay=5))
    app = make_app(providers)
    async with running_client(app) as http:
        state = app.state.studio
        prepared = await runner.prepare_run(state, RunRequest(prompt="hi"))
        stream = with_keepalive(runner.stream_run(state, prepared), 10)
        first = await anext(stream)
        pending = asyncio.ensure_future(anext(stream))
        await asyncio.sleep(0.05)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await stream.aclose()
        run_id = parse_sse(first)[0][1]["run_id"]
        history = (await http.get(f"/api/history/{run_id}")).json()
        assert history["status"] == "cancelled"
        assert history["output"] == ""


# ---- the linked prompt is deleted while the provider call runs -------------------------------


async def _linked_prompt(http) -> tuple[str, str]:
    created = (await http.post("/api/prompts", json={"name": "Linked", "prompt": "hi"})).json()
    return created["id"], created["latest_version"]["id"]


async def _delete_soon(http, prompt_id: str) -> None:
    await asyncio.sleep(0.1)
    assert (await http.delete(f"/api/prompts/{prompt_id}")).status_code == 204


async def test_run_keeps_its_result_when_the_linked_prompt_is_deleted(make_client) -> None:
    async with make_client(claude(Script(text="finished", delay=0.4))) as http:
        prompt_id, version_id = await _linked_prompt(http)
        payload = {"prompt": "hi", "prompt_version_id": version_id}
        run, _ = await asyncio.gather(
            http.post("/api/runs", json=payload), _delete_soon(http, prompt_id)
        )
        assert run.status_code == 200, run.text
        assert run.json()["text"] == "finished"
        detail = (await http.get(f"/api/history/{run.json()['id']}")).json()
        assert detail["status"] == "success"
        assert detail["prompt_version_id"] is None


async def test_stream_keeps_its_result_when_the_linked_prompt_is_deleted(make_client) -> None:
    async with make_client(claude(Script(text="streamed text", delay=0.4))) as http:
        prompt_id, version_id = await _linked_prompt(http)
        payload = {"prompt": "hi", "prompt_version_id": version_id}
        stream, _ = await asyncio.gather(
            http.post("/api/runs/stream", json=payload), _delete_soon(http, prompt_id)
        )
        events = parse_sse(stream.text)
        assert [name for name, _ in events][-1] == "done", events
        run_id = events[0][1]["run_id"]
        detail = (await http.get(f"/api/history/{run_id}")).json()
        assert detail["status"] == "success"
        assert detail["output"] == "streamed text"
        assert detail["prompt_version_id"] is None
