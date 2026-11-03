"""History queries and retention; export/import round trips and conflict policies."""

from __future__ import annotations

import json
import re

import pytest

from app.providers.base import ProviderError, ProviderErrorKind, ProviderName
from tests.fakes import Script, ScriptedProvider

ANTHROPIC = ProviderName.ANTHROPIC
MISSING = "c" * 32


async def run(http, prompt: str, **extra) -> dict:
    response = await http.post("/api/runs", json={"prompt": prompt, **extra})
    return response.json()


# ---- history ---------------------------------------------------------------------------------


async def test_history_filters_and_pagination(make_client) -> None:
    def script(req):
        if "boom" in req.prompt:
            return Script(error=ProviderError(ProviderErrorKind.PROVIDER_ERROR, ANTHROPIC))
        return Script(text=f"answer to {req.prompt}")

    providers = {ANTHROPIC: ScriptedProvider(ANTHROPIC, script)}
    async with make_client(providers) as http:
        await run(http, "alpha 50%", model="demo-concise")
        await run(http, "beta", model="claude-opus-5-5")
        await run(http, "boom", model="claude-opus-5-5")
        compare = (
            await http.post(
                "/api/compare", json={"variants": [{"prompt": "gamma"}], "models": ["demo-verbose"]}
            )
        ).json()

        async def ids(**params) -> list[str]:
            body = (await http.get("/api/history", params=params)).json()
            return [item["prompt_preview"] for item in body["items"]]

        assert await ids() == ["gamma", "boom", "beta", "alpha 50%"]
        assert await ids(provider="anthropic") == ["boom", "beta"]
        assert await ids(model="demo-concise") == ["alpha 50%"]
        assert await ids(status="error") == ["boom"]
        assert await ids(source="compare") == ["gamma"]
        assert await ids(group_id=compare["id"]) == ["gamma"]
        assert await ids(q="50%") == ["alpha 50%"]
        assert await ids(q="ANSWER TO BETA") == ["beta"]
        page = (await http.get("/api/history", params={"limit": 2, "offset": 1})).json()
        assert page["total"] == 4
        assert [item["prompt_preview"] for item in page["items"]] == ["boom", "beta"]
        summary = page["items"][0]
        assert summary["status"] == "error"
        assert summary["error_code"] == "provider_error"
        assert summary["output_preview"] == ""
        assert (await http.get("/api/history", params={"status": "nope"})).status_code == 422


async def test_history_detail_delete_and_clear(client) -> None:
    first = await run(client, "one")
    await run(client, "two")
    detail = (await client.get(f"/api/history/{first['id']}")).json()
    assert detail["params"] == first["params"]
    assert detail["output"] == first["text"]
    assert detail["warnings"] == []
    assert (await client.delete(f"/api/history/{first['id']}")).status_code == 204
    assert (await client.get(f"/api/history/{first['id']}")).status_code == 404
    assert (await client.delete(f"/api/history/{first['id']}")).status_code == 404
    assert (await client.get("/api/history/not-hex")).status_code == 404
    cleared = await client.delete("/api/history")
    assert cleared.json() == {"deleted": 1}
    assert (await client.get("/api/history")).json()["total"] == 0


async def test_history_retention(make_client) -> None:
    async with make_client(history_max_rows=3) as http:
        for index in range(5):
            await run(http, f"run {index}")
        items = (await http.get("/api/history")).json()["items"]
        assert [item["prompt_preview"] for item in items] == ["run 4", "run 3", "run 2"]


async def test_history_previews_are_truncated(client) -> None:
    await run(client, "x" * 500)
    item = (await client.get("/api/history")).json()["items"][0]
    assert len(item["prompt_preview"]) == 200
    assert len(item["output_preview"]) <= 200


# ---- export / import -------------------------------------------------------------------------


async def seed(http) -> dict:
    prompt = (
        await http.post(
            "/api/prompts",
            json={
                "name": "Greeter",
                "prompt": "Hello {{name}}",
                "tags": ["a", "b"],
                "description": "d",
            },
        )
    ).json()
    await http.post(
        f"/api/prompts/{prompt['id']}/versions", json={"prompt": "Hi {{name}}", "notes": "v2"}
    )
    suite = (
        await http.post(
            "/api/suites",
            json={
                "name": "Checks",
                "cases": [
                    {
                        "name": "c1",
                        "variables": {"name": "Ann"},
                        "assertions": [{"type": "json_valid"}],
                    },
                    {
                        "name": "c2",
                        "assertions": [{"type": "regex", "pattern": "^H", "flags": "i"}],
                    },
                ],
            },
        )
    ).json()
    await http.post(
        "/api/runs",
        json={
            "prompt": "Hi {{name}}",
            "variables": {"name": "Z"},
            "prompt_version_id": prompt["latest_version"]["id"],
        },
    )
    return {"prompt": prompt, "suite": suite}


async def export_doc(http, include: str = "prompts,suites,history") -> dict:
    response = await http.get("/api/export", params={"include": include})
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert re.fullmatch(
        r'attachment; filename="prompt-studio-export-\d{8}-\d{6}\.json"', disposition
    )
    return response.json()


async def test_export_document_shape(client) -> None:
    await seed(client)
    doc = await export_doc(client)
    assert doc["format"] == "prompt-studio-export"
    assert doc["format_version"] == 1
    assert doc["app_version"] == "2.0.0"
    assert doc["exported_at"].endswith("Z")
    [prompt] = doc["prompts"]
    assert prompt["tags"] == ["a", "b"]
    assert [v["version"] for v in prompt["versions"]] == [1, 2]
    assert prompt["versions"][0]["settings"] == {
        "model": None,
        "temperature": None,
        "max_tokens": None,
        "thinking": False,
    }
    [suite] = doc["suites"]
    assert [case["position"] for case in suite["cases"]] == [0, 1]
    assert suite["cases"][1]["assertions"] == [{"type": "regex", "pattern": "^H", "flags": "i"}]
    [entry] = doc["history"]
    assert entry["prompt_version_id"] == prompt["versions"][0]["id"]
    default = await export_doc(client, "prompts,suites")
    assert default["history"] == []
    only = await export_doc(client, "suites")
    assert only["prompts"] == []
    assert (await client.get("/api/export", params={"include": "prompts,bogus"})).status_code == 422


async def test_round_trip_into_empty_database(make_client, tmp_path) -> None:
    async with make_client() as http:
        await seed(http)
        doc = await export_doc(http)
    other_db = f"sqlite+aiosqlite:///{tmp_path / 'other.db'}"
    async with make_client(database_url=other_db) as http:
        result = (await http.post("/api/import", json=doc)).json()
        assert result == {
            "prompts": {"created": 1, "updated": 0, "skipped": 0, "renamed": 0},
            "suites": {"created": 1, "updated": 0, "skipped": 0, "renamed": 0},
            "history": {"created": 1},
            "warnings": [],
        }
        again = await export_doc(http)
        assert again["prompts"][0]["name"] == "Greeter"
        assert again["prompts"][0]["id"] != doc["prompts"][0]["id"]
        assert again["prompts"][0]["created_at"] == doc["prompts"][0]["created_at"]
        assert [v["prompt"] for v in again["prompts"][0]["versions"]] == [
            "Hello {{name}}",
            "Hi {{name}}",
        ]
        assert again["suites"][0]["cases"][0]["variables"] == {"name": "Ann"}
        history_version = again["history"][0]["prompt_version_id"]
        assert history_version == again["prompts"][0]["versions"][0]["id"]


async def test_conflict_policies(client) -> None:
    await seed(client)
    doc = await export_doc(client, "prompts,suites")

    skipped = (await client.post("/api/import", json=doc)).json()
    assert skipped["prompts"]["skipped"] == 1
    assert skipped["suites"]["skipped"] == 1

    renamed = (await client.post("/api/import", params={"conflict": "rename"}, json=doc)).json()
    assert renamed["prompts"]["renamed"] == 1
    renamed_again = (
        await client.post("/api/import", params={"conflict": "rename"}, json=doc)
    ).json()
    assert renamed_again["suites"]["renamed"] == 1
    names = sorted(item["name"] for item in (await client.get("/api/prompts")).json()["items"])
    assert names == ["Greeter", "Greeter (imported 2)", "Greeter (imported)"]
    suite_names = sorted(item["name"] for item in (await client.get("/api/suites")).json()["items"])
    assert suite_names == ["Checks", "Checks (imported 2)", "Checks (imported)"]

    doc["prompts"][0]["description"] = "overwritten"
    doc["prompts"][0]["tags"] = ["z"]
    doc["prompts"][0]["versions"].append(
        {**doc["prompts"][0]["versions"][0], "id": "f" * 32, "version": 3, "prompt": "Brand new"}
    )
    doc["suites"][0]["cases"] = doc["suites"][0]["cases"][:1]
    overwritten = (
        await client.post("/api/import", params={"conflict": "overwrite"}, json=doc)
    ).json()
    assert overwritten["prompts"]["updated"] == 1
    assert overwritten["suites"]["updated"] == 1
    listing = (await client.get("/api/prompts", params={"q": "overwritten"})).json()
    [prompt] = listing["items"]
    assert prompt["name"] == "Greeter"
    assert prompt["tags"] == ["z"]
    assert prompt["version_count"] == 3  # duplicates skipped, one new version appended
    versions = (await client.get(f"/api/prompts/{prompt['id']}/versions")).json()["items"]
    assert versions[0]["version"] == 3
    suites = (await client.get("/api/suites", params={"q": "checks"})).json()["items"]
    original = next(item for item in suites if item["name"] == "Checks")
    assert original["case_count"] == 1


async def test_rename_truncates_long_names(client) -> None:
    long_name = "N" * 120
    await client.post("/api/prompts", json={"name": long_name, "prompt": "x"})
    doc = await export_doc(client, "prompts")
    await client.post("/api/import", params={"conflict": "rename"}, json=doc)
    names = [item["name"] for item in (await client.get("/api/prompts")).json()["items"]]
    renamed = next(name for name in names if name != long_name)
    assert len(renamed) == 120
    assert renamed.endswith(" (imported)")


async def test_legacy_placeholders(client) -> None:
    doc = {
        "format": "prompt-studio-export",
        "format_version": 1,
        "prompts": [
            {
                "id": "a" * 32,
                "name": "Legacy",
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-02T00:00:00",
                "versions": [
                    {
                        "id": "b" * 32,
                        "version": 7,
                        "system": "You are {role}.",
                        "prompt": 'Summarize {text} as {"json": 1}',
                        "created_at": "2025-01-01T00:00:00Z",
                    }
                ],
            }
        ],
    }
    result = await client.post("/api/import", params={"legacy_placeholders": "true"}, json=doc)
    assert result.status_code == 200, result.text
    [item] = (await client.get("/api/prompts")).json()["items"]
    detail = (await client.get(f"/api/prompts/{item['id']}")).json()
    latest = detail["latest_version"]
    assert latest["version"] == 1
    assert latest["system"] == "You are {{role}}."
    assert latest["prompt"] == 'Summarize {{text}} as {"json": 1}'
    assert detail["created_at"] == "2025-01-01T00:00:00.000000Z"
    assert detail["updated_at"] == "2025-01-02T00:00:00.000000Z"


@pytest.mark.parametrize(
    "document",
    [
        {"format": "other", "format_version": 1},
        {"format": "prompt-studio-export", "format_version": 2},
        {"format": "prompt-studio-export", "format_version": True},
        {"format_version": 1},
    ],
)
async def test_unsupported_format(client, document) -> None:
    response = await client.post("/api/import", json=document)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_format"


async def test_import_validation_errors(client) -> None:
    base = {"format": "prompt-studio-export", "format_version": 1}
    shape = await client.post("/api/import", json={**base, "prompts": [{"name": "x"}]})
    assert shape.json()["error"]["code"] == "validation_error"
    assert shape.json()["error"]["details"]["errors"][0]["loc"][:3] == ["body", "prompts", 0]
    version = {"id": "1" * 32, "version": 1, "prompt": "p", "created_at": "2025-01-01T00:00:00Z"}
    prompt = {
        "id": "2" * 32,
        "name": "Dup",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "versions": [version],
    }
    dup = await client.post(
        "/api/import", json={**base, "prompts": [prompt, {**prompt, "name": "dup"}]}
    )
    assert dup.json()["error"]["details"]["errors"][0]["loc"] == ["body", "prompts", 1, "name"]
    suite = {
        "id": "3" * 32,
        "name": "S",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "cases": [
            {
                "id": "4" * 32,
                "name": "c",
                "assertions": [{"type": "regex", "pattern": "["}],
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
            }
        ],
    }
    bad_assertion = await client.post("/api/import", json={**base, "suites": [suite]})
    details = bad_assertion.json()["error"]["details"]
    assert bad_assertion.json()["error"]["code"] == "invalid_assertion"
    assert (details["suite_index"], details["case_index"], details["assertion_index"]) == (0, 0, 0)
    assert (await client.get("/api/prompts")).json()["total"] == 0
    assert (await client.post("/api/import", json=[1, 2])).status_code == 422


async def test_import_limits(make_client) -> None:
    version = {"id": "1" * 32, "version": 1, "prompt": "p", "created_at": "2025-01-01T00:00:00Z"}
    prompt = {
        "id": "2" * 32,
        "name": "P",
        "tags": ["a", "b"],
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "versions": [version, {**version, "version": 2, "prompt": "q"}],
    }
    base = {"format": "prompt-studio-export", "format_version": 1}
    async with make_client(max_tags_per_prompt=1) as http:
        response = await http.post("/api/import", json={**base, "prompts": [prompt]})
        assert response.json()["error"]["details"]["limit"] == "max_tags_per_prompt"
    async with make_client(max_versions_per_prompt=1) as http:
        response = await http.post("/api/import", json={**base, "prompts": [prompt]})
        assert response.json()["error"]["details"]["limit"] == "max_versions_per_prompt"
    async with make_client(history_max_rows=1) as http:
        entry = {
            "id": "5" * 32,
            "created_at": "2025-01-01T00:00:00Z",
            "source": "run",
            "model": "demo-concise",
            "provider": "demo",
            "status": "success",
            "prompt_template": "p",
            "rendered_prompt": "p",
            "params": {"temperature": None, "max_tokens": 5, "thinking": False},
        }
        response = await http.post("/api/import", json={**base, "history": [entry, entry]})
        assert response.json()["error"]["details"]["limit"] == "history_max_rows"
        ok = await http.post(
            "/api/import", json={**base, "history": [{**entry, "prompt_version_id": "9" * 32}]}
        )
        assert ok.json()["history"] == {"created": 1}
        assert ok.json()["warnings"] == [
            "History entry 1 references a version that was not imported."
        ]
    async with make_client(max_cases_per_suite=1) as http:
        case = {
            "id": "4" * 32,
            "name": "c",
            "assertions": [{"type": "json_valid"}],
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        }
        suite = {
            "id": "3" * 32,
            "name": "S",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "cases": [case, case],
        }
        response = await http.post("/api/import", json={**base, "suites": [suite]})
        assert response.json()["error"]["details"]["limit"] == "max_cases_per_suite"


async def test_overwrite_version_limit_rolls_back(make_client) -> None:
    async with make_client(max_versions_per_prompt=2) as http:
        await http.post("/api/prompts", json={"name": "P", "prompt": "one"})
        await http.post("/api/prompts", json={"name": "Untouched", "prompt": "one"})
        version = {
            "id": "1" * 32,
            "version": 1,
            "prompt": "two",
            "created_at": "2025-01-01T00:00:00Z",
        }
        doc = {
            "format": "prompt-studio-export",
            "format_version": 1,
            "prompts": [
                {
                    "id": "7" * 32,
                    "name": "New One",
                    "created_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-01T00:00:00Z",
                    "versions": [version],
                },
                {
                    "id": "2" * 32,
                    "name": "P",
                    "description": "changed",
                    "created_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-01T00:00:00Z",
                    "versions": [version, {**version, "version": 2, "prompt": "three"}],
                },
            ],
        }
        response = await http.post("/api/import", params={"conflict": "overwrite"}, json=doc)
        assert response.json()["error"]["details"]["limit"] == "max_versions_per_prompt"
        names = sorted(item["name"] for item in (await http.get("/api/prompts")).json()["items"])
        assert names == ["P", "Untouched"]  # nothing from the file was kept
        [p] = (await http.get("/api/prompts", params={"q": "P", "sort": "name"})).json()["items"][
            :1
        ]
        assert p["description"] == ""


async def test_bad_conflict_policy(client) -> None:
    response = await client.post(
        "/api/import",
        params={"conflict": "merge"},
        json={"format": "prompt-studio-export", "format_version": 1},
    )
    assert response.status_code == 422


async def test_search_folds_non_ascii_case_everywhere(client) -> None:
    """SQLite's lower() only folds ASCII; search uses Unicode casefold on both sides."""
    prompt = await client.post(
        "/api/prompts", json={"name": "Ärger Привет prompt", "prompt": "Über alles: Привет мир"}
    )
    assert prompt.status_code == 201
    suite = await client.post("/api/suites", json={"name": "Évaluation Übersetzung"})
    assert suite.status_code == 201
    run = await client.post("/api/runs", json={"prompt": "Привет мир, Über alles STRASSE"})
    assert run.status_code == 200

    async def total(path: str, query: str) -> int:
        response = await client.get(path, params={"q": query})
        assert response.status_code == 200
        return response.json()["total"]

    for query in ("Ärger", "ärger", "ÄRGER", "Привет", "привет", "über"):
        assert await total("/api/prompts", query) == 1, query
    for query in ("Évaluation", "évaluation", "ÜBERSETZUNG"):
        assert await total("/api/suites", query) == 1, query
    for query in ("Привет", "привет", "Über", "über", "straße"):
        assert await total("/api/history", query) >= 1, query
    assert await total("/api/history", "Ärger") == 0


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        ("params.temperature", "NaN"),
        ("params.temperature", "Infinity"),
        ("params.max_tokens", "0"),
        ("params.unknown", "1"),
        ("input_tokens", "-5"),
        ("input_tokens", str(10**29)),
        ("output_tokens", str(2**31)),
        ("latency_ms", str(10**20)),
        ("ttft_ms", "-1"),
        ("cost_usd", "NaN"),
    ],
)
async def test_import_rejects_out_of_range_history_values(client, field: str, raw: str) -> None:
    run = await client.post("/api/runs", json={"prompt": "hello"})
    assert run.status_code == 200
    document = await export_doc(client, "history")
    entry = document["history"][0]
    marker = "__RAW_VALUE__"
    if field.startswith("params."):
        entry["params"][field.removeprefix("params.")] = marker
    else:
        entry[field] = marker
    body = json.dumps(document).replace(f'"{marker}"', raw)
    response = await client.post(
        "/api/import", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    # Nothing was stored, so the export still works.
    exported = await client.get("/api/export", params={"include": "history"})
    assert exported.status_code == 200
    assert len(exported.json()["history"]) == 1
