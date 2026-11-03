"""Prompt library: CRUD, names, tags, search, versions, restore, diffs and cascades."""

from __future__ import annotations

import pytest

from app.services.diff import diff_text

MISSING_ID = "0" * 32


async def create(client, name: str = "Greeter", **extra):
    payload = {"name": name, "prompt": "Hello {{name}}", **extra}
    response = await client.post("/api/prompts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_and_get_prompt(client) -> None:
    created = await create(
        client,
        name="  Greeter  ",
        description="  Says hi  ",
        tags=["Fun Stuff", "fun-stuff", "X_1"],
        system="Be {{tone|warm}}",
        notes="first",
        settings={"model": "demo-concise", "temperature": 0.5, "max_tokens": 100, "thinking": True},
    )
    assert created["name"] == "Greeter"
    assert created["description"] == "Says hi"
    assert created["tags"] == ["fun-stuff", "x_1"]
    assert created["archived"] is False
    assert created["version_count"] == 1
    latest = created["latest_version"]
    assert latest["version"] == 1
    assert latest["notes"] == "first"
    assert latest["system"] == "Be {{tone|warm}}"
    assert latest["settings"] == {
        "model": "demo-concise",
        "temperature": 0.5,
        "max_tokens": 100,
        "thinking": True,
    }
    assert latest["variables"] == [
        {"name": "tone", "default": "warm", "required": False},
        {"name": "name", "default": None, "required": True},
    ]
    fetched = (await client.get(f"/api/prompts/{created['id']}")).json()
    assert fetched == created
    by_version_id = (await client.get(f"/api/prompt-versions/{latest['id']}")).json()
    assert by_version_id == latest


async def test_unique_names_case_insensitive(client) -> None:
    await create(client, name="Greeter")
    duplicate = await client.post("/api/prompts", json={"name": "greeter", "prompt": "x"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == {
        "code": "conflict",
        "message": "That name is already in use.",
        "details": {"field": "name"},
    }
    other = await create(client, name="Other")
    renamed = await client.patch(f"/api/prompts/{other['id']}", json={"name": "GREETER"})
    assert renamed.status_code == 409
    same = await client.patch(f"/api/prompts/{other['id']}", json={"name": "Other"})
    assert same.status_code == 200


async def test_invalid_tags_and_tag_limit(make_client) -> None:
    async with make_client(max_tags_per_prompt=2) as http:
        bad = await http.post("/api/prompts", json={"name": "a", "prompt": "x", "tags": ["!!"]})
        assert bad.status_code == 422
        assert bad.json()["error"]["code"] == "validation_error"
        many = await http.post(
            "/api/prompts", json={"name": "a", "prompt": "x", "tags": ["a", "b", "c"]}
        )
        assert many.json()["error"]["code"] == "limit_exceeded"
        assert many.json()["error"]["details"] == {"limit": "max_tags_per_prompt", "max": 2}
        created = (await http.post("/api/prompts", json={"name": "a", "prompt": "x"})).json()
        patched = await http.patch(f"/api/prompts/{created['id']}", json={"tags": ["a", "b", "c"]})
        assert patched.json()["error"]["code"] == "limit_exceeded"


async def test_update_prompt(client) -> None:
    created = await create(client, tags=["one"])
    response = await client.patch(
        f"/api/prompts/{created['id']}",
        json={"name": "Renamed", "description": "new", "tags": ["two", "three"], "archived": True},
    )
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["description"] == "new"
    assert body["tags"] == ["two", "three"]
    assert body["archived"] is True
    assert body["updated_at"] >= created["updated_at"]
    unchanged = (await client.patch(f"/api/prompts/{created['id']}", json={})).json()
    assert unchanged["tags"] == ["two", "three"]
    extra = await client.patch(f"/api/prompts/{created['id']}", json={"bogus": 1})
    assert extra.status_code == 422


async def test_not_found_and_invalid_ids(client) -> None:
    for path in (
        f"/api/prompts/{MISSING_ID}",
        "/api/prompts/not-an-id",
        "/api/prompts/" + "A" * 32,
        f"/api/prompts/{MISSING_ID}/versions",
        f"/api/prompts/{MISSING_ID}/versions/1",
        f"/api/prompt-versions/{MISSING_ID}",
    ):
        response = await client.get(path)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "not_found"
    detail = (await client.get(f"/api/prompts/{MISSING_ID}")).json()["error"]
    assert detail["details"] == {"resource": "prompt"}
    assert (await client.delete(f"/api/prompts/{MISSING_ID}")).status_code == 404
    assert (await client.patch(f"/api/prompts/{MISSING_ID}", json={})).status_code == 404
    bad_version = await client.get(f"/api/prompts/{MISSING_ID}/versions/0")
    assert bad_version.status_code == 422


async def test_list_search_filter_sort_and_paginate(client) -> None:
    alpha = await create(client, name="Alpha", tags=["writing", "email"], description="Mail 100%")
    beta = await create(client, name="beta", tags=["writing"])
    gamma = await create(client, name="Gamma", tags=["code"])
    await client.post(f"/api/prompts/{gamma['id']}/versions", json={"prompt": "find_me here"})
    await client.patch(f"/api/prompts/{beta['id']}", json={"archived": True})

    async def names(**params) -> list[str]:
        response = await client.get("/api/prompts", params=params)
        assert response.status_code == 200, response.text
        return [item["name"] for item in response.json()["items"]]

    assert await names() == ["Gamma", "Alpha"]
    assert await names(archived="true") == ["beta"]
    assert sorted(await names(archived="all")) == ["Alpha", "Gamma", "beta"]
    assert await names(sort="name", order="asc", archived="all") == ["Alpha", "beta", "Gamma"]
    assert await names(sort="created_at", order="asc") == ["Alpha", "Gamma"]
    assert await names(q="FIND_ME") == ["Gamma"]
    assert await names(q="100%") == ["Alpha"]
    assert await names(q="%") == ["Alpha"]
    assert await names(q="_") == ["Gamma"]
    assert await names(tag=["writing"], archived="all") == ["beta", "Alpha"]
    assert await names(tag=["Writing", "email"]) == ["Alpha"]
    page = (await client.get("/api/prompts", params={"limit": 1, "offset": 1})).json()
    assert page["total"] == 2
    assert page["limit"] == 1
    assert page["offset"] == 1
    assert [item["name"] for item in page["items"]] == ["Alpha"]
    summary = page["items"][0]
    assert summary["latest_version"]["variables"] == ["name"]
    assert summary["version_count"] == 1
    assert "prompt" not in summary["latest_version"]
    bad = await client.get("/api/prompts", params={"tag": "!!"})
    assert bad.status_code == 422
    assert (await client.get("/api/prompts", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/prompts", params={"sort": "nope"})).status_code == 422
    tags = (await client.get("/api/tags")).json()["tags"]
    assert tags == [
        {"tag": "writing", "count": 2},
        {"tag": "code", "count": 1},
        {"tag": "email", "count": 1},
    ]
    assert alpha["id"]


async def test_versions_no_changes_restore_and_limit(make_client) -> None:
    async with make_client(max_versions_per_prompt=3) as http:
        created = await create(http, settings={"model": None, "thinking": False})
        prompt_id = created["id"]
        same = await http.post(
            f"/api/prompts/{prompt_id}/versions", json={"prompt": "Hello {{name}}"}
        )
        assert same.status_code == 409
        assert same.json()["error"]["code"] == "no_changes"
        v2 = await http.post(
            f"/api/prompts/{prompt_id}/versions",
            json={"prompt": "Hello {{name}}", "settings": {"thinking": True}, "notes": "think"},
        )
        assert v2.status_code == 201
        assert v2.json()["version"] == 2
        restored = await http.post(f"/api/prompts/{prompt_id}/versions/1/restore")
        assert restored.status_code == 201
        assert restored.json()["version"] == 3
        assert restored.json()["notes"] == "Restored from v1"
        assert restored.json()["settings"]["thinking"] is False
        again = await http.post(f"/api/prompts/{prompt_id}/versions/1/restore")
        assert again.json()["error"]["code"] == "no_changes"
        over = await http.post(f"/api/prompts/{prompt_id}/versions", json={"prompt": "new"})
        assert over.json()["error"]["details"] == {"limit": "max_versions_per_prompt", "max": 3}
        missing = await http.post(f"/api/prompts/{prompt_id}/versions/9/restore")
        assert missing.status_code == 404

        listing = (await http.get(f"/api/prompts/{prompt_id}/versions")).json()
        assert [item["version"] for item in listing["items"]] == [3, 2, 1]
        assert listing["total"] == 3
        v1 = (await http.get(f"/api/prompts/{prompt_id}/versions/1")).json()
        assert v1["prompt"] == "Hello {{name}}"
        detail = (await http.get(f"/api/prompts/{prompt_id}")).json()
        assert detail["version_count"] == 3
        assert detail["latest_version"]["version"] == 3
        assert detail["updated_at"] > created["updated_at"]


async def test_diff_endpoint(client) -> None:
    created = await create(client, system="Line A")
    prompt_id = created["id"]
    await client.post(
        f"/api/prompts/{prompt_id}/versions",
        json={
            "prompt": "Hello {{name}}\nSecond line",
            "settings": {"max_tokens": 5},
            "notes": "n2",
        },
    )
    diff = (
        await client.get(
            f"/api/prompts/{prompt_id}/diff", params={"from_version": 1, "to_version": 2}
        )
    ).json()
    assert diff["from_version"] == 1
    assert diff["to_version"] == 2
    assert diff["prompt"]["added"] == 1
    assert diff["prompt"]["removed"] == 0
    assert diff["system"]["removed"] == 1
    assert diff["system"]["lines"] == [
        {"op": "delete", "old_line": 1, "new_line": None, "text": "Line A"}
    ]
    assert diff["settings_changed"] is True
    assert diff["settings_to"]["max_tokens"] == 5
    assert diff["notes_from"] == ""
    assert diff["notes_to"] == "n2"
    same = (
        await client.get(
            f"/api/prompts/{prompt_id}/diff", params={"from_version": 2, "to_version": 2}
        )
    ).json()
    assert same["prompt"]["changed"] is False
    assert same["prompt"]["unified"] == ""
    missing = await client.get(
        f"/api/prompts/{prompt_id}/diff", params={"from_version": 1, "to_version": 7}
    )
    assert missing.status_code == 404
    no_params = await client.get(f"/api/prompts/{prompt_id}/diff")
    assert no_params.status_code == 422


def test_diff_text_replace_and_unified() -> None:
    diff = diff_text("a\nb\nc", "a\nB\nc\nd", 1, 2)
    assert [(line.op, line.old_line, line.new_line, line.text) for line in diff.lines] == [
        ("equal", 1, 1, "a"),
        ("delete", 2, None, "b"),
        ("insert", None, 2, "B"),
        ("equal", 3, 3, "c"),
        ("insert", None, 4, "d"),
    ]
    assert diff.added == 2
    assert diff.removed == 1
    assert diff.changed
    assert diff.unified.startswith("--- v1\n+++ v2\n@@")
    assert diff_text(None, None, 1, 1).lines == []


async def test_delete_prompt_cascades(client) -> None:
    created = await create(client, tags=["x"])
    version_id = created["latest_version"]["id"]
    run = await client.post("/api/runs", json={"prompt": "hi", "prompt_version_id": version_id})
    history_id = run.json()["id"]
    response = await client.delete(f"/api/prompts/{created['id']}")
    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get(f"/api/prompts/{created['id']}")).status_code == 404
    assert (await client.get(f"/api/prompt-versions/{version_id}")).status_code == 404
    history = (await client.get(f"/api/history/{history_id}")).json()
    assert history["prompt_version_id"] is None
    assert (await client.get("/api/tags")).json() == {"tags": []}


@pytest.mark.parametrize("field", ["name", "prompt"])
async def test_create_validation(client, field: str) -> None:
    payload = {"name": "x", "prompt": "y"}
    payload[field] = "" if field == "prompt" else "   "
    response = await client.post("/api/prompts", json=payload)
    assert response.status_code == 422


async def test_prompt_template_limits(make_client) -> None:
    async with make_client(max_prompt_chars=5) as http:
        response = await http.post("/api/prompts", json={"name": "x", "prompt": "123456"})
        assert response.json()["error"]["code"] == "validation_error"
        created = (await http.post("/api/prompts", json={"name": "x", "prompt": "1"})).json()
        version = await http.post(
            f"/api/prompts/{created['id']}/versions", json={"prompt": "123456"}
        )
        assert version.json()["error"]["code"] == "validation_error"


async def test_oversized_integers_in_query_and_path_are_validation_errors(client) -> None:
    prompt_id = (await create(client))["id"]
    huge = str(10**20)  # SQLite cannot bind integers of 2**63 or more
    urls = [
        f"/api/prompts?offset={huge}",
        f"/api/history?offset={huge}",
        f"/api/suites?offset={huge}",
        f"/api/evals?offset={huge}",
        f"/api/prompts/{prompt_id}/versions?offset={huge}",
        f"/api/prompts/{prompt_id}/versions/{huge}",
        f"/api/prompts/{prompt_id}/diff?from_version=1&to_version={huge}",
        f"/api/prompts/{prompt_id}/diff?from_version={2**31}&to_version=1",
    ]
    for url in urls:
        response = await client.get(url)
        assert response.status_code == 422, (url, response.text)
        assert response.json()["error"]["code"] == "validation_error", url
    restore = await client.post(f"/api/prompts/{prompt_id}/versions/{huge}/restore")
    assert restore.status_code == 422
    # The largest accepted values still work.
    largest = await client.get(f"/api/prompts?offset={2**31 - 1}")
    assert largest.status_code == 200
    assert largest.json()["items"] == []
    missing = await client.get(f"/api/prompts/{prompt_id}/versions/{2**31 - 1}")
    assert missing.status_code == 404
