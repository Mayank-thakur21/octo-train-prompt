"""Comparisons: validation, partial failures, deadlines, summary, history and SSE."""

from __future__ import annotations

import asyncio

import pytest

from app.providers.base import ProviderError, ProviderErrorKind, ProviderName
from app.services.compare import DEADLINE_MESSAGE, variant_label
from tests.fakes import Script, ScriptedProvider, parse_sse

ANTHROPIC = ProviderName.ANTHROPIC

TWO_BY_TWO = {
    "variants": [{"prompt": "Say {{word|hi}}"}, {"label": "Loud", "prompt": "SAY {{word|hi}}"}],
    "models": ["demo-concise", "demo-verbose"],
}


def test_variant_labels() -> None:
    assert [variant_label(i) for i in (0, 1, 25, 26)] == [
        "Variant A",
        "Variant B",
        "Variant Z",
        "Variant 27",
    ]


async def test_compare_two_by_two(client) -> None:
    response = await client.post("/api/compare", json={**TWO_BY_TWO, "variables": {"word": "yo"}})
    assert response.status_code == 200
    body = response.json()
    assert [cell["index"] for cell in body["cells"]] == [0, 1, 2, 3]
    assert [(c["variant_index"], c["model"]) for c in body["cells"]] == [
        (0, "demo-concise"),
        (0, "demo-verbose"),
        (1, "demo-concise"),
        (1, "demo-verbose"),
    ]
    assert [c["variant_label"] for c in body["cells"]] == ["Variant A", "Variant A", "Loud", "Loud"]
    assert all(c["status"] == "ok" and c["error"] is None for c in body["cells"])
    assert body["cells"][0]["result"]["rendered_prompt"] == "Say yo"
    assert body["variants"][1] == {
        "index": 1,
        "label": "Loud",
        "system": None,
        "prompt": "SAY {{word|hi}}",
        "prompt_version_id": None,
    }
    assert body["params"] == {"temperature": None, "max_tokens": 4096, "thinking": False}
    summary = body["summary"]
    assert summary["ok_count"] == 4
    assert summary["error_count"] == 0
    latencies = {c["index"]: c["result"]["latency_ms"] for c in body["cells"]}
    fastest = min(latencies, key=lambda index: (latencies[index], index))
    assert summary["fastest_cell"] == fastest
    assert summary["cheapest_cell"] is None
    history = (await client.get("/api/history", params={"group_id": body["id"]})).json()
    assert history["total"] == 4
    assert {item["source"] for item in history["items"]} == {"compare"}


async def test_partial_failures_and_cheapest(make_client) -> None:
    def script(req):
        if "fail" in req.prompt:
            return Script(
                error=ProviderError(ProviderErrorKind.RATE_LIMITED, ANTHROPIC, retry_after=4)
            )
        return Script(text="ok", input_tokens=100, output_tokens=10)

    providers = {ANTHROPIC: ScriptedProvider(ANTHROPIC, script)}
    async with make_client(providers) as http:
        response = await http.post(
            "/api/compare",
            json={
                "variants": [{"prompt": "fine"}, {"prompt": "please fail"}],
                "models": ["claude-haiku-5-5", "demo-concise"],
                "temperature": 0.4,
                "thinking": True,
            },
        )
        assert response.status_code == 200
        body = response.json()
        statuses = [cell["status"] for cell in body["cells"]]
        assert statuses == ["ok", "ok", "error", "ok"]
        failed = body["cells"][2]
        assert failed["result"] is None
        assert failed["error"]["code"] == "provider_rate_limited"
        assert failed["error"]["details"]["retry_after"] == 4
        run_id = failed["error"]["details"]["run_id"]
        assert (await http.get(f"/api/history/{run_id}")).json()["status"] == "error"
        assert body["summary"]["cheapest_cell"] == 0
        assert body["summary"]["error_count"] == 1
        assert body["warnings"] == [
            "temperature is not supported by Claude Haiku 5.5 and was ignored."
        ]
        haiku = body["cells"][0]["result"]
        assert haiku["params"] == {"temperature": None, "max_tokens": 4096, "thinking": True}
        demo = body["cells"][1]["result"]
        assert demo["params"]["temperature"] == 0.4
        assert body["params"]["temperature"] == 0.4


async def test_compare_validation(make_client) -> None:
    async with make_client(
        max_compare_variants=2, max_compare_models=2, max_compare_cells=3
    ) as http:

        async def error_of(payload):
            response = await http.post("/api/compare", json=payload)
            assert response.status_code in {404, 422}, response.text
            return response.json()["error"]

        too_many_variants = await error_of(
            {"variants": [{"prompt": "a"}] * 3, "models": ["demo-concise"]}
        )
        assert too_many_variants["details"] == {"limit": "max_compare_variants", "max": 2}
        too_many_models = await error_of(
            {
                "variants": [{"prompt": "a"}],
                "models": ["demo-concise", "demo-verbose", "claude-opus-5-5"],
            }
        )
        assert too_many_models["details"]["limit"] == "max_compare_models"
        cells = await error_of(
            {
                "variants": [{"prompt": "a"}, {"prompt": "b"}],
                "models": ["demo-concise", "demo-verbose"],
            }
        )
        assert cells["details"] == {"limit": "max_compare_cells", "max": 3}
        missing = await error_of(
            {
                "variants": [{"prompt": "{{a}} {{b}}"}, {"prompt": "{{c|x}}"}],
                "models": ["demo-concise"],
            }
        )
        assert missing["code"] == "missing_variables"
        assert missing["details"]["missing"] == ["a", "b"]
        assert missing["details"]["by_variant"] == [["a", "b"], []]
        unknown = await error_of({"variants": [{"prompt": "a"}], "models": ["nope"]})
        assert unknown["code"] == "unknown_model"
        unavailable = await error_of({"variants": [{"prompt": "a"}], "models": ["claude-opus-5-5"]})
        assert unavailable["code"] == "provider_not_configured"
        duplicate = await error_of(
            {"variants": [{"prompt": "a"}], "models": ["demo-concise", "demo-concise"]}
        )
        assert duplicate["code"] == "validation_error"
        tokens = await error_of(
            {"variants": [{"prompt": "a"}], "models": ["demo-concise"], "max_tokens": 5000}
        )
        assert tokens["code"] == "invalid_parameter"
        assert tokens["details"] == {"param": "max_tokens", "max": 4096}
        timeout = await error_of(
            {"variants": [{"prompt": "a"}], "models": ["demo-concise"], "timeout_seconds": 0.5}
        )
        assert timeout["details"]["param"] == "timeout_seconds"
        version = await error_of(
            {
                "variants": [{"prompt": "a", "prompt_version_id": "1" * 32}],
                "models": ["demo-concise"],
            }
        )
        assert version["code"] == "not_found"
        empty = await error_of({"variants": [], "models": ["demo-concise"]})
        assert empty["code"] == "validation_error"


async def test_multi_model_max_tokens_rule(make_client) -> None:
    providers = {ANTHROPIC: ScriptedProvider(ANTHROPIC)}
    async with make_client(providers, default_max_tokens=8000) as http:
        body = (
            await http.post(
                "/api/compare",
                json={"variants": [{"prompt": "a"}], "models": ["claude-opus-5-5", "demo-concise"]},
            )
        ).json()
        assert body["params"]["max_tokens"] == 4096
        assert {c["result"]["params"]["max_tokens"] for c in body["cells"]} == {4096}


async def test_per_cell_timeout(make_client) -> None:
    providers = {ANTHROPIC: ScriptedProvider(ANTHROPIC, Script(delay=1.5))}
    async with make_client(providers) as http:
        body = (
            await http.post(
                "/api/compare",
                json={
                    "variants": [{"prompt": "a"}],
                    "models": ["claude-opus-5-5", "demo-concise"],
                    "timeout_seconds": 1,
                    "save_history": False,
                },
            )
        ).json()
        assert body["cells"][0]["error"]["code"] == "provider_timeout"
        assert "run_id" not in body["cells"][0]["error"]["details"]
        assert body["cells"][1]["status"] == "ok"
        assert body["cells"][1]["result"]["id"] is None
        assert (await http.get("/api/history")).json()["total"] == 0


async def test_overall_deadline(make_client) -> None:
    def script(req):
        return Script(delay=5 if "slow" in req.prompt else 0)

    providers = {ANTHROPIC: ScriptedProvider(ANTHROPIC, script)}
    async with make_client(providers, compare_total_timeout_seconds=0.3) as http:
        body = (
            await http.post(
                "/api/compare",
                json={
                    "variants": [{"prompt": "fast"}, {"prompt": "slow"}],
                    "models": ["claude-opus-5-5"],
                },
            )
        ).json()
        fast, slow = body["cells"]
        assert fast["status"] == "ok"
        assert slow["status"] == "error"
        assert slow["error"]["code"] == "provider_timeout"
        assert slow["error"]["message"] == DEADLINE_MESSAGE
        history = (await http.get(f"/api/history/{slow['error']['details']['run_id']}")).json()
        assert history["error_message"] == DEADLINE_MESSAGE


async def test_concurrency_limit(make_client) -> None:
    active = 0
    peak = 0

    class Counting(ScriptedProvider):
        async def generate(self, req):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.05)
            active -= 1
            return await super().generate(req)

    providers = {ANTHROPIC: Counting(ANTHROPIC)}
    async with make_client(providers, compare_concurrency=2) as http:
        response = await http.post(
            "/api/compare",
            json={
                "variants": [{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}],
                "models": ["claude-opus-5-5"],
            },
        )
        assert response.status_code == 200
    assert peak == 2


async def test_unexpected_cell_failure_is_internal_error(make_client) -> None:
    class Broken(ScriptedProvider):
        async def generate(self, req):
            raise RuntimeError("secret details")

    async with make_client({ANTHROPIC: Broken(ANTHROPIC)}) as http:
        body = (
            await http.post(
                "/api/compare", json={"variants": [{"prompt": "a"}], "models": ["claude-opus-5-5"]}
            )
        ).json()
        assert body["cells"][0]["error"]["code"] == "internal_error"
        assert "secret details" not in str(body)


async def test_compare_stream_events(client) -> None:
    response = await client.post("/api/compare/stream", json=TWO_BY_TWO)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "start"
    assert names[-1] == "done"
    assert names.count("cell") == 4
    start = events[0][1]
    assert [ref["index"] for ref in start["cells"]] == [0, 1, 2, 3]
    done = events[-1][1]
    assert done["id"] == start["comparison_id"]
    assert sorted(data["index"] for name, data in events if name == "cell") == [0, 1, 2, 3]
    assert done["summary"]["ok_count"] == 4


async def test_compare_stream_prevalidation_is_json(client) -> None:
    response = await client.post(
        "/api/compare/stream", json={"variants": [{"prompt": "{{x}}"}], "models": ["demo-concise"]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "missing_variables"


async def test_compare_stream_close_cancels_outstanding_cells(make_app) -> None:
    from app.schemas import CompareRequest
    from app.services import compare
    from tests.conftest import running_client

    def script(req):
        return Script(delay=5 if "slow" in req.prompt else 0)

    app = make_app({ANTHROPIC: ScriptedProvider(ANTHROPIC, script)})
    async with running_client(app) as http:
        state = app.state.studio
        prepared = await compare.prepare_compare(
            state,
            CompareRequest(
                variants=[{"prompt": "fast"}, {"prompt": "slow"}], models=["claude-opus-5-5"]
            ),
        )
        frames = compare.stream_compare(state, prepared)
        start = await anext(frames)
        first_cell = await anext(frames)
        assert start.startswith("event: start")
        assert first_cell.startswith("event: cell")
        await frames.aclose()
        history = (await http.get("/api/history", params={"group_id": prepared.id})).json()
        assert history["total"] == 1  # the slow cell was cancelled and not recorded


async def test_compare_stream_unexpected_error_event(make_app, monkeypatch) -> None:
    from app.services import compare
    from tests.conftest import running_client

    app = make_app()

    def broken(self):
        raise RuntimeError("bad summary")

    monkeypatch.setattr(compare.CompareExecution, "result", broken)
    async with running_client(app) as http:
        response = await http.post("/api/compare/stream", json=TWO_BY_TWO)
    events = parse_sse(response.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["error"]["code"] == "internal_error"


@pytest.mark.parametrize("save", [True, False])
async def test_compare_history_toggle(client, save: bool) -> None:
    body = (await client.post("/api/compare", json={**TWO_BY_TWO, "save_history": save})).json()
    total = (await client.get("/api/history")).json()["total"]
    assert total == (4 if save else 0)
    assert all((cell["result"]["id"] is not None) == save for cell in body["cells"])


async def test_compare_keeps_every_cell_when_a_linked_prompt_is_deleted(make_client) -> None:
    providers = {ANTHROPIC: ScriptedProvider(ANTHROPIC, Script(text="slow", delay=0.4))}
    async with make_client(providers) as http:
        created = (await http.post("/api/prompts", json={"name": "Linked", "prompt": "a"})).json()
        version_id = created["latest_version"]["id"]

        async def delete_soon() -> None:
            await asyncio.sleep(0.1)
            assert (await http.delete(f"/api/prompts/{created['id']}")).status_code == 204

        payload = {
            "variants": [{"prompt": "a", "prompt_version_id": version_id}, {"prompt": "b"}],
            "models": ["claude-opus-5-5", "demo-concise"],
        }
        response, _ = await asyncio.gather(http.post("/api/compare", json=payload), delete_soon())
        assert response.status_code == 200, response.text
        body = response.json()
        assert [cell["status"] for cell in body["cells"]] == ["ok"] * 4
        history = (await http.get("/api/history", params={"group_id": body["id"]})).json()
        assert history["total"] == 4
        assert {item["prompt_version_id"] for item in history["items"]} == {None}
