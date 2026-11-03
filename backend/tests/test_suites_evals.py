"""Test suites, cases and evaluation runs (background execution, cancel, delete, recovery)."""

from __future__ import annotations

import asyncio
import json

from app.db import Database, new_id, utcnow
from app.models import EvalRun
from app.providers.base import ProviderError, ProviderErrorKind, ProviderName
from app.services.evaluation import INTERRUPTED_MESSAGE, JUDGE_SYSTEM_PROMPT, JUDGE_UNPARSEABLE
from tests.conftest import running_client
from tests.fakes import Script, ScriptedProvider

ANTHROPIC = ProviderName.ANTHROPIC
OPENAI = ProviderName.OPENAI
MISSING = "e" * 32


async def make_suite(http, name: str = "Suite", cases: list | None = None) -> dict:
    payload = {
        "name": name,
        "description": "desc",
        "cases": cases
        if cases is not None
        else [
            {
                "name": "greets",
                "variables": {"who": "Bob"},
                "assertions": [{"type": "contains", "value": "demo"}],
            },
            {
                "name": "judge",
                "variables": {"who": "Ann"},
                "assertions": [
                    {"type": "max_chars", "value": 10_000},
                    {"type": "llm_judge", "rubric": "an offline demo response", "threshold": 3},
                ],
            },
        ],
    }
    response = await http.post("/api/suites", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def wait_finished(http, eval_id: str, max_wait: float = 10.0) -> dict:
    deadline = asyncio.get_running_loop().time() + max_wait
    while True:
        detail = (await http.get(f"/api/evals/{eval_id}")).json()
        if detail["status"] not in {"queued", "running"}:
            return detail
        assert asyncio.get_running_loop().time() < deadline, detail
        await asyncio.sleep(0.02)


# ---- suites ----------------------------------------------------------------------------------


async def test_suite_crud_and_cases(client) -> None:
    suite = await make_suite(client)
    assert suite["case_count"] == 2
    assert [case["position"] for case in suite["cases"]] == [0, 1]
    assert suite["cases"][0]["assertions"] == [
        {"type": "contains", "value": "demo", "case_sensitive": False}
    ]
    assert suite["last_eval"] is None
    suite_id = suite["id"]

    added = await client.post(
        f"/api/suites/{suite_id}/cases",
        json={"name": "third", "assertions": [{"type": "json_valid"}]},
    )
    assert added.status_code == 201
    case = added.json()
    assert case["position"] == 2
    assert case["variables"] == {}

    updated = await client.put(
        f"/api/suites/{suite_id}/cases/{case['id']}",
        json={
            "name": "third!",
            "variables": {"x": "1"},
            "assertions": [{"type": "equals", "value": "{}"}],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "third!"
    assert updated.json()["assertions"][0]["trim"] is True

    patched = await client.patch(
        f"/api/suites/{suite_id}", json={"name": "Renamed", "description": "d2"}
    )
    assert patched.json()["name"] == "Renamed"
    assert patched.json()["case_count"] == 3

    assert (await client.delete(f"/api/suites/{suite_id}/cases/{case['id']}")).status_code == 204
    assert (await client.delete(f"/api/suites/{suite_id}/cases/{case['id']}")).status_code == 404
    other = await make_suite(client, name="Other", cases=[])
    wrong_suite = await client.put(
        f"/api/suites/{other['id']}/cases/{suite['cases'][0]['id']}",
        json={"name": "x", "assertions": [{"type": "json_valid"}]},
    )
    assert wrong_suite.status_code == 404

    listing = (await client.get("/api/suites")).json()
    assert listing["total"] == 2
    assert [item["name"] for item in listing["items"]] == ["Other", "Renamed"]
    searched = (await client.get("/api/suites", params={"q": "renam"})).json()
    assert [item["name"] for item in searched["items"]] == ["Renamed"]
    paged = (await client.get("/api/suites", params={"limit": 1, "offset": 1})).json()
    assert len(paged["items"]) == 1

    conflict = await client.post("/api/suites", json={"name": "renamed"})
    assert conflict.status_code == 409
    rename_conflict = await client.patch(f"/api/suites/{other['id']}", json={"name": "RENAMED"})
    assert rename_conflict.status_code == 409

    assert (await client.delete(f"/api/suites/{suite_id}")).status_code == 204
    assert (await client.get(f"/api/suites/{suite_id}")).status_code == 404
    for method, path in (
        ("get", f"/api/suites/{MISSING}"),
        ("patch", f"/api/suites/{MISSING}"),
        ("delete", f"/api/suites/{MISSING}"),
        ("get", "/api/suites/xyz"),
    ):
        kwargs = {"json": {}} if method == "patch" else {}
        assert (await getattr(client, method)(path, **kwargs)).status_code == 404


async def test_assertion_validation_on_save(client) -> None:
    bad_regex = await client.post(
        "/api/suites",
        json={
            "name": "S",
            "cases": [
                {"name": "ok", "assertions": [{"type": "json_valid"}]},
                {
                    "name": "bad",
                    "assertions": [{"type": "json_valid"}, {"type": "regex", "pattern": "("}],
                },
            ],
        },
    )
    assert bad_regex.status_code == 422
    error = bad_regex.json()["error"]
    assert error["code"] == "invalid_assertion"
    assert error["details"]["case_index"] == 1
    assert error["details"]["assertion_index"] == 1
    assert error["details"]["reason"].startswith("Invalid regular expression")

    suite = await make_suite(client, cases=[])
    bad_schema = await client.post(
        f"/api/suites/{suite['id']}/cases",
        json={"name": "c", "assertions": [{"type": "json_schema", "schema": {"oneOf": []}}]},
    )
    assert bad_schema.json()["error"]["code"] == "invalid_assertion"
    assert "case_index" not in bad_schema.json()["error"]["details"]
    bad_judge = await client.post(
        f"/api/suites/{suite['id']}/cases",
        json={
            "name": "c",
            "assertions": [{"type": "llm_judge", "rubric": "r", "judge_model": "x"}],
        },
    )
    assert bad_judge.json()["error"]["details"]["reason"] == "Unknown judge model: x"
    shape = await client.post(
        f"/api/suites/{suite['id']}/cases", json={"name": "c", "assertions": [{"type": "contains"}]}
    )
    assert shape.json()["error"]["code"] == "validation_error"
    empty = await client.post(
        f"/api/suites/{suite['id']}/cases", json={"name": "c", "assertions": []}
    )
    assert empty.json()["error"]["code"] == "validation_error"
    unknown_type = await client.post(
        f"/api/suites/{suite['id']}/cases", json={"name": "c", "assertions": [{"type": "magic"}]}
    )
    assert unknown_type.json()["error"]["code"] == "validation_error"


async def test_suite_limits(make_client) -> None:
    async with make_client(max_cases_per_suite=1, max_assertions_per_case=1) as http:
        case = {"name": "c", "assertions": [{"type": "json_valid"}]}
        too_many = await http.post("/api/suites", json={"name": "S", "cases": [case, case]})
        assert too_many.json()["error"]["details"] == {"limit": "max_cases_per_suite", "max": 1}
        suite = (await http.post("/api/suites", json={"name": "S", "cases": [case]})).json()
        extra = await http.post(f"/api/suites/{suite['id']}/cases", json=case)
        assert extra.json()["error"]["details"]["limit"] == "max_cases_per_suite"
        assertions = await http.put(
            f"/api/suites/{suite['id']}/cases/{suite['cases'][0]['id']}",
            json={"name": "c", "assertions": [{"type": "json_valid"}] * 2},
        )
        assert assertions.json()["error"]["details"]["limit"] == "max_assertions_per_case"


# ---- evaluations -------------------------------------------------------------------------------


async def test_eval_runs_to_completion(client) -> None:
    suite = await make_suite(client)
    created = await client.post(
        "/api/evals",
        json={
            "suite_id": suite["id"],
            "prompt": "Say hi to {{who}}",
            "models": ["demo-concise", "demo-verbose"],
        },
    )
    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "queued"
    assert body["progress"] == {"completed": 0, "total": 4}
    assert {result["status"] for result in body["results"]} == {"pending"}
    assert body["prompt_label"] == "Ad-hoc prompt"
    assert body["judge_model"] == "demo-concise"
    assert body["params"] == {"temperature": None, "max_tokens": 4096, "thinking": False}
    assert [(r["case_index"], r["model"]) for r in body["results"]] == [
        (0, "demo-concise"),
        (0, "demo-verbose"),
        (1, "demo-concise"),
        (1, "demo-verbose"),
    ]

    detail = await wait_finished(client, body["id"])
    assert detail["status"] == "completed"
    assert detail["progress"] == {"completed": 4, "total": 4}
    assert detail["started_at"] is not None
    assert detail["finished_at"] is not None
    assert detail["passed"] + detail["failed"] + detail["errored"] == 4
    assert detail["pass_rate"] == detail["passed"] / 4
    first = detail["results"][0]
    assert first["status"] == "passed"
    assert first["output"].startswith("This is an offline demo response")
    assert first["score"] == 1.0
    assert first["assertions"][0]["detail"] == 'Output contains "demo".'
    judged = detail["results"][2]["assertions"][1]
    assert judged["type"] == "llm_judge"
    assert 1 <= judged["score"] <= 5
    assert judged["detail"].startswith("Judge score")
    per_model = {item["model"]: item for item in detail["per_model"]}
    assert per_model["demo-concise"]["pending"] == 0
    assert per_model["demo-concise"]["total_cost_usd"] is None
    assert per_model["demo-concise"]["avg_latency_ms"] is not None
    assert detail["cases"][0]["variables"] == {"who": "Bob"}

    suites = (await client.get("/api/suites")).json()["items"]
    assert suites[0]["last_eval"]["id"] == body["id"]
    assert suites[0]["last_eval"]["status"] == "completed"
    listing = (await client.get("/api/evals", params={"suite_id": suite["id"]})).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == body["id"]
    assert (await client.get("/api/evals", params={"status": "failed"})).json()["total"] == 0
    assert (await client.get("/api/evals", params={"prompt_id": MISSING})).json()["total"] == 0
    assert (await client.get("/api/evals", params={"status": "bogus"})).status_code == 422


async def test_eval_from_library_version(client) -> None:
    prompt = (
        await client.post("/api/prompts", json={"name": "Hi", "prompt": "Hello {{who}}"})
    ).json()
    suite = await make_suite(client)
    created = (
        await client.post(
            "/api/evals",
            json={
                "suite_id": suite["id"],
                "prompt_version_id": prompt["latest_version"]["id"],
                "models": ["demo-concise"],
            },
        )
    ).json()
    assert created["prompt_label"] == "Hi v1"
    assert created["prompt_id"] == prompt["id"]
    assert created["prompt"] == "Hello {{who}}"
    await wait_finished(client, created["id"])
    by_prompt = (await client.get("/api/evals", params={"prompt_id": prompt["id"]})).json()
    assert by_prompt["total"] == 1


async def test_eval_validation(make_client) -> None:
    # The default suite needs 3 calls per model: 2 generations and 1 judge call.
    async with make_client(max_eval_models=1, max_eval_calls=3) as http:
        suite = await make_suite(http)
        empty = await make_suite(http, name="Empty", cases=[])

        async def error_of(payload) -> dict:
            response = await http.post("/api/evals", json=payload)
            assert response.status_code in {404, 422}, response.text
            return response.json()["error"]

        base = {"suite_id": suite["id"], "prompt": "Hi {{who}}", "models": ["demo-concise"]}
        assert (await error_of({**base, "suite_id": MISSING}))["details"] == {"resource": "suite"}
        assert (await error_of({**base, "suite_id": empty["id"]}))["code"] == "empty_suite"
        both = await error_of({**base, "prompt_version_id": MISSING})
        assert both["code"] == "validation_error"
        neither = await error_of({"suite_id": suite["id"], "models": ["demo-concise"]})
        assert neither["code"] == "validation_error"
        version = await error_of(
            {"suite_id": suite["id"], "prompt_version_id": MISSING, "models": ["demo-concise"]}
        )
        assert version["details"] == {"resource": "prompt_version"}
        models = await error_of({**base, "models": ["demo-concise", "demo-verbose"]})
        assert models["details"] == {"limit": "max_eval_models", "max": 1}
        assert (await error_of({**base, "models": ["nope"]}))["code"] == "unknown_model"
        assert (await error_of({**base, "models": ["gpt-5.5"]}))[
            "code"
        ] == "provider_not_configured"
        assert (await error_of({**base, "max_tokens": 5000}))["code"] == "invalid_parameter"
        missing = await error_of({**base, "prompt": "{{who}} {{what}}"})
        assert missing["code"] == "missing_variables"
        assert missing["details"]["missing"] == ["what"]
        assert [item["case_name"] for item in missing["details"]["cases"]] == ["greets", "judge"]
        assert missing["details"]["cases"][0]["missing"] == ["what"]
        judge = await error_of({**base, "judge_model": "nope"})
        assert judge["code"] == "invalid_assertion"
        assert judge["details"] == {
            "assertion_index": 1,
            "reason": "Unknown judge model: nope",
            "case_index": 1,
        }
        no_judge_suite = await make_suite(
            http,
            name="No judge",
            cases=[{"name": "c", "assertions": [{"type": "json_valid"}]}],
        )
        unused = await error_of(
            {**base, "suite_id": no_judge_suite["id"], "prompt": "Hi", "judge_model": "nope"}
        )
        assert unused["code"] == "unknown_model"

    async with make_client(max_eval_calls=1) as http:
        suite = await make_suite(http, name="Second")
        response = await http.post(
            "/api/evals",
            json={"suite_id": suite["id"], "prompt": "Hi", "models": ["demo-concise"]},
        )
        assert response.json()["error"]["details"] == {"limit": "max_eval_calls", "max": 1}


async def test_judge_calls_count_against_max_eval_calls(make_client) -> None:
    async with make_client(max_eval_calls=5) as http:
        suite = await make_suite(http)  # 2 cases, one llm_judge assertion: 3 calls per model
        payload = {"suite_id": suite["id"], "prompt": "Hi {{who}}"}
        over = await http.post(
            "/api/evals", json={**payload, "models": ["demo-concise", "demo-verbose"]}
        )
        assert over.status_code == 422
        error = over.json()["error"]
        assert error["code"] == "limit_exceeded"
        assert error["details"] == {"limit": "max_eval_calls", "max": 5}
        assert "needs 6 provider calls" in error["message"]
        within = await http.post("/api/evals", json={**payload, "models": ["demo-concise"]})
        assert within.status_code == 202, within.text
        assert (await wait_finished(http, within.json()["id"]))["status"] == "completed"


async def test_judge_heavy_suite_is_rejected_at_the_default_limits(client) -> None:
    judge = {"type": "llm_judge", "rubric": "be helpful", "threshold": 1}
    cases = [{"name": f"c{i}", "assertions": [judge] * 20} for i in range(100)]
    suite = await make_suite(client, name="Judges", cases=cases)
    # 100 jobs per model looked like 200 calls, but the judges add 4,000 more.
    response = await client.post(
        "/api/evals",
        json={"suite_id": suite["id"], "prompt": "Hi", "models": ["demo-concise", "demo-verbose"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"limit": "max_eval_calls", "max": 200}
    assert "needs 4200 provider calls" in response.json()["error"]["message"]


async def test_unavailable_judge_model_is_invalid_assertion(client) -> None:
    suite = await make_suite(
        client,
        cases=[
            {
                "name": "c",
                "assertions": [
                    {"type": "json_valid"},
                    {"type": "llm_judge", "rubric": "r", "judge_model": "claude-opus-5-5"},
                ],
            }
        ],
    )
    response = await client.post(
        "/api/evals", json={"suite_id": suite["id"], "prompt": "x", "models": ["demo-concise"]}
    )
    error = response.json()["error"]
    assert error["code"] == "invalid_assertion"
    assert error["details"]["case_index"] == 0
    assert error["details"]["assertion_index"] == 1
    default_judge = await client.post(
        "/api/evals",
        json={
            "suite_id": (await make_suite(client, name="J"))["id"],
            "prompt": "x",
            "models": ["demo-concise"],
            "judge_model": "claude-opus-5-5",
        },
    )
    assert default_judge.json()["error"]["code"] == "invalid_assertion"


async def test_generation_and_judge_failures(make_client) -> None:
    def script(req):
        if req.system == JUDGE_SYSTEM_PROMPT:
            if "unparseable" in req.prompt:
                return Script(text="I refuse to grade")
            if "explode" in req.prompt:
                return Script(error=ProviderError(ProviderErrorKind.PROVIDER_ERROR, ANTHROPIC))
            return Script(text='{"score": 5, "reason": "great"}')
        if "fail generation" in req.prompt:
            return Script(error=ProviderError(ProviderErrorKind.AUTH, ANTHROPIC))
        return Script(text="output text", input_tokens=1000, output_tokens=100)

    providers = {ANTHROPIC: ScriptedProvider(ANTHROPIC, script)}
    async with make_client(providers, judge_model="claude-haiku-5-5") as http:
        cases = [
            {
                "name": "good",
                "variables": {"mode": "fine"},
                "assertions": [{"type": "llm_judge", "rubric": "fine"}],
            },
            {
                "name": "unparseable",
                "variables": {"mode": "unparseable"},
                "assertions": [{"type": "llm_judge", "rubric": "unparseable"}],
            },
            {
                "name": "explode",
                "variables": {"mode": "explode"},
                "assertions": [{"type": "llm_judge", "rubric": "explode"}, {"type": "json_valid"}],
            },
            {
                "name": "gen fails",
                "variables": {"mode": "fail generation"},
                "assertions": [{"type": "json_valid"}],
            },
        ]
        suite = await make_suite(http, cases=cases)
        created = (
            await http.post(
                "/api/evals",
                json={
                    "suite_id": suite["id"],
                    "prompt": "Mode: {{mode}}",
                    "models": ["claude-sonnet-5-5"],
                    "temperature": 0.9,
                    "thinking": True,
                },
            )
        ).json()
        assert created["judge_model"] == "claude-haiku-5-5"
        detail = await wait_finished(http, created["id"])
        results = detail["results"]
        assert results[0]["status"] == "passed"
        assert results[0]["assertions"][0]["detail"] == "Judge score 5/5 (threshold 4): great"
        assert results[0]["cost_usd"] == round(1000 / 1e6 * 2 + 100 / 1e6 * 10, 6)
        assert results[1]["status"] == "error"
        assert results[1]["assertions"][0]["error"] == JUDGE_UNPARSEABLE
        assert results[2]["status"] == "error"
        assert results[2]["assertions"][0]["error"] == "Judge call failed: provider_error"
        assert results[2]["assertions"][1]["passed"] is False
        assert results[2]["score"] == 0.0
        assert results[3]["status"] == "error"
        assert results[3]["assertions"] == []
        assert results[3]["score"] is None
        assert results[3]["error"]["code"] == "provider_auth_error"
        assert detail["errored"] == 3
        assert detail["passed"] == 1
        per_model = detail["per_model"][0]
        assert per_model["total_input_tokens"] == 3000
        assert per_model["total_cost_usd"] == round(3 * 0.003, 6)
        generation_calls = [
            call for call in providers[ANTHROPIC].calls if call.system != JUDGE_SYSTEM_PROMPT
        ]
        assert all(call.temperature is None and call.thinking for call in generation_calls)
        judge_calls = [c for c in providers[ANTHROPIC].calls if c.system == JUDGE_SYSTEM_PROMPT]
        assert judge_calls[0].model.id == "claude-haiku-5-5"
        assert judge_calls[0].thinking is False
        assert judge_calls[0].max_tokens == 2048
        assert "<rubric>\nfine\n</rubric>" in judge_calls[0].prompt
        assert "<input>\nMode: fine\n</input>" in judge_calls[0].prompt
        assert "<output>\noutput text\n</output>" in judge_calls[0].prompt


async def test_unexpected_job_failure_marks_result(make_client, monkeypatch) -> None:
    from app.services import evaluation

    def broken(*_args, **_kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(evaluation, "case_status", broken)
    async with make_client() as http:
        suite = await make_suite(http)
        created = (
            await http.post(
                "/api/evals",
                json={"suite_id": suite["id"], "prompt": "x", "models": ["demo-concise"]},
            )
        ).json()
        detail = await wait_finished(http, created["id"])
        assert detail["status"] == "completed"
        assert {r["error"]["code"] for r in detail["results"]} == {"internal_error"}


async def test_run_level_failure(make_client, monkeypatch) -> None:
    from app.services import evaluation

    def broken(*_args, **_kwargs):
        raise LookupError("gone")

    monkeypatch.setattr(evaluation, "_model_spec", broken)
    async with make_client() as http:
        suite = await make_suite(http)
        created = (
            await http.post(
                "/api/evals",
                json={"suite_id": suite["id"], "prompt": "x", "models": ["demo-concise"]},
            )
        ).json()
        detail = await wait_finished(http, created["id"])
        assert detail["status"] == "failed"
        assert detail["error"] == {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "details": None,
        }


async def test_cancel_and_delete_running_eval(make_client) -> None:
    providers = {ANTHROPIC: ScriptedProvider(ANTHROPIC, Script(delay=5))}
    async with make_client(providers, eval_concurrency=1) as http:
        suite = await make_suite(http)
        created = (
            await http.post(
                "/api/evals",
                json={"suite_id": suite["id"], "prompt": "x", "models": ["claude-opus-5-5"]},
            )
        ).json()
        await asyncio.sleep(0.05)
        cancelled = await http.post(f"/api/evals/{created['id']}/cancel")
        assert cancelled.status_code == 200
        summary = cancelled.json()
        assert summary["status"] == "cancelled"
        assert summary["finished_at"] is not None
        assert "results" not in summary
        detail = (await http.get(f"/api/evals/{created['id']}")).json()
        assert {r["status"] for r in detail["results"]} == {"pending"}
        assert detail["per_model"][0]["pending"] == 2
        again = await http.post(f"/api/evals/{created['id']}/cancel")
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "eval_not_running"

        running = (
            await http.post(
                "/api/evals",
                json={"suite_id": suite["id"], "prompt": "y", "models": ["claude-opus-5-5"]},
            )
        ).json()
        await asyncio.sleep(0.05)
        assert (await http.delete(f"/api/evals/{running['id']}")).status_code == 204
        assert (await http.get(f"/api/evals/{running['id']}")).status_code == 404
        assert (await http.delete(f"/api/evals/{running['id']}")).status_code == 404
        assert (await http.post(f"/api/evals/{MISSING}/cancel")).status_code == 404
        assert (await http.get("/api/evals/bad")).status_code == 404


async def test_shutdown_cancels_and_restart_marks_interrupted(make_settings) -> None:
    from app.main import create_app
    from app.providers.registry import build_registry

    settings = make_settings()
    providers = {ANTHROPIC: ScriptedProvider(ANTHROPIC, Script(delay=5))}
    app = create_app(settings, build_registry(settings, providers))
    async with running_client(app) as http:
        suite = await make_suite(http)
        created = (
            await http.post(
                "/api/evals",
                json={"suite_id": suite["id"], "prompt": "x", "models": ["claude-opus-5-5"]},
            )
        ).json()
        await asyncio.sleep(0.05)
    async with running_client(create_app(settings)) as http:
        assert (await http.get(f"/api/evals/{created['id']}")).json()["status"] == "cancelled"

    # A run left "running" by a crashed process is failed on the next start.
    db = Database(settings.database_url)
    async with db.write() as session:
        session.add(
            EvalRun(
                id=new_id(),
                suite_name="Crashed",
                prompt_label="Ad-hoc prompt",
                prompt="x",
                models=["demo-concise"],
                params={"temperature": None, "max_tokens": 10, "thinking": False},
                judge_model="demo-concise",
                cases_snapshot=[],
                status="running",
                total=1,
                created_at=utcnow(),
            )
        )
    await db.dispose()
    async with running_client(create_app(settings)) as http:
        failed = (await http.get("/api/evals", params={"status": "failed"})).json()
        assert failed["total"] == 1
        assert failed["items"][0]["error"] == {
            "code": "interrupted",
            "message": INTERRUPTED_MESSAGE,
            "details": None,
        }
        assert json.dumps(failed)  # serializable


async def test_suite_delete_keeps_eval_snapshot(client) -> None:
    suite = await make_suite(client)
    created = (
        await client.post(
            "/api/evals", json={"suite_id": suite["id"], "prompt": "x", "models": ["demo-concise"]}
        )
    ).json()
    await wait_finished(client, created["id"])
    await client.delete(f"/api/suites/{suite['id']}")
    detail = (await client.get(f"/api/evals/{created['id']}")).json()
    assert detail["suite_id"] is None
    assert detail["suite_name"] == "Suite"
    assert len(detail["cases"]) == 2


async def test_judge_model_removed_from_catalog(make_client) -> None:
    case = {
        "name": "c",
        "assertions": [{"type": "llm_judge", "rubric": "r", "judge_model": "gpt-5.5"}],
    }
    async with make_client() as http:
        suite = await make_suite(http, name="Judged", cases=[case])
    async with make_client(openai_models="gpt-4.1-mini") as http:
        response = await http.post(
            "/api/evals", json={"suite_id": suite["id"], "prompt": "x", "models": ["demo-concise"]}
        )
        error = response.json()["error"]
        assert error["code"] == "invalid_assertion"
        assert error["details"]["reason"] == "Unknown judge model: gpt-5.5"
