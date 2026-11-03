"""Authentication, rate limiting, client identity, proxies, CORS and response headers."""

from __future__ import annotations

import ipaddress

import pytest

from app.security import ApiKeyVerifier, RateLimiter, ip_bucket, key_identity, resolve_client_ip
from tests.conftest import OTHER_API_KEY, TEST_API_KEY


def nets(*entries: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [ipaddress.ip_network(entry, strict=False) for entry in entries]


# ---- unit ------------------------------------------------------------------------------------


def test_verifier_checks_every_key() -> None:
    verifier = ApiKeyVerifier([TEST_API_KEY, OTHER_API_KEY])
    assert verifier.enabled
    assert verifier.verify(TEST_API_KEY)
    assert verifier.verify(OTHER_API_KEY)
    assert not verifier.verify("x" * 20)
    assert not verifier.verify(None)
    assert not ApiKeyVerifier([]).enabled


def test_key_identity_hides_the_key() -> None:
    identity = key_identity(TEST_API_KEY)
    assert identity.startswith("key:")
    assert len(identity) == 4 + 16
    assert TEST_API_KEY not in identity


@pytest.mark.parametrize(
    ("address", "bucket"),
    [
        ("203.0.113.9", "203.0.113.9"),
        ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),
        ("::ffff:198.51.100.7", "198.51.100.7"),
        ("unknown", "unknown"),
    ],
)
def test_ip_buckets(address: str, bucket: str) -> None:
    assert ip_bucket(address) == bucket


def test_ipv6_neighbours_share_a_bucket() -> None:
    assert ip_bucket("2001:db8::1") == ip_bucket("2001:db8::ffff:1")
    assert ip_bucket("2001:db8::1") != ip_bucket("2001:db8:0:1::1")


@pytest.mark.parametrize(
    ("peer", "xff", "trusted", "expected"),
    [
        ("203.0.113.5", "1.2.3.4", [], "203.0.113.5"),  # no trusted proxies: XFF ignored
        ("203.0.113.5", "1.2.3.4", ["10.0.0.0/8"], "203.0.113.5"),  # untrusted peer
        ("10.0.0.2", "1.2.3.4", ["10.0.0.0/8"], "1.2.3.4"),
        ("10.0.0.2", "6.6.6.6, 1.2.3.4, 10.0.0.9", ["10.0.0.0/8"], "1.2.3.4"),  # spoofed left
        ("10.0.0.2", "garbage, 10.0.0.3", ["10.0.0.0/8"], "10.0.0.2"),  # invalid stops the walk
        ("10.0.0.2", "10.0.0.3", ["10.0.0.0/8"], "10.0.0.2"),  # only proxies
        ("10.0.0.2", None, ["10.0.0.0/8"], "10.0.0.2"),
        ("::ffff:10.0.0.2", "1.2.3.4", ["10.0.0.0/8"], "1.2.3.4"),
        (None, None, [], "unknown"),
        ("testclient", None, [], "testclient"),
    ],
)
def test_resolve_client_ip(peer, xff, trusted, expected) -> None:
    assert resolve_client_ip(peer, xff, nets(*trusted)) == expected


async def test_rate_limiter_disabled_and_closing() -> None:
    from limits import parse_many

    limiter = RateLimiter("memory://", enabled=False)
    items = parse_many("1/minute")
    for _ in range(3):
        await limiter.hit(items, "g", "ip:x")
        await limiter.check(items, "g", "ip:x")
    await limiter.aclose()
    prefixed = RateLimiter("async+memory://")
    await prefixed.hit(items, "g", "ip:y")
    await prefixed.aclose()


# ---- HTTP ------------------------------------------------------------------------------------


async def test_auth_disabled_allows_everything(client) -> None:
    response = await client.get("/api/models")
    assert response.status_code == 200


async def test_auth_required_and_exempt_routes(make_client) -> None:
    async with make_client(api_keys=f"{TEST_API_KEY},{OTHER_API_KEY}") as http:
        for path in ("/api/health", "/api/ready", "/api/meta", "/api/openapi.json", "/api/docs"):
            assert (await http.get(path)).status_code == 200, path
        meta = (await http.get("/api/meta")).json()
        assert meta["auth_required"] is True

        missing = await http.get("/api/models")
        assert missing.status_code == 401
        assert missing.json()["error"]["code"] == "unauthorized"
        assert missing.headers["www-authenticate"] == 'ApiKey header="X-API-Key"'

        wrong = await http.get("/api/models", headers={"X-API-Key": "nope-nope-nope-nope"})
        assert wrong.status_code == 401
        assert "nope" not in wrong.text

        for key in (TEST_API_KEY, OTHER_API_KEY):
            ok = await http.get("/api/models", headers={"X-API-Key": key})
            assert ok.status_code == 200

        posted = await http.post("/api/runs", json={"prompt": "hi"})
        assert posted.status_code == 401


async def test_auth_failure_limiter(make_client) -> None:
    async with make_client(api_keys=TEST_API_KEY, rate_limit_auth_failures="2/minute") as http:
        for _ in range(2):
            response = await http.get("/api/models", headers={"X-API-Key": "wrong-key-000000"})
            assert response.status_code == 401
        blocked = await http.get("/api/models", headers={"X-API-Key": "wrong-key-000000"})
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "rate_limited"
        assert int(blocked.headers["retry-after"]) >= 1
        # Even the right key is refused from this address until the window passes.
        refused = await http.get("/api/models", headers={"X-API-Key": TEST_API_KEY})
        assert refused.status_code == 429
        # Requests without a key are not attempts: they get the plain 401.
        assert (await http.get("/api/models")).status_code == 401


async def test_auth_is_checked_before_the_body_is_parsed(make_client) -> None:
    malformed = {"content": "{bad", "headers": {"content-type": "application/json"}}
    async with make_client(api_keys=TEST_API_KEY, rate_limit_auth_failures="2/minute") as http:
        for path in ("/api/runs", "/api/runs/stream", "/api/prompts", "/api/import", "/api/evals"):
            missing = await http.post(path, **malformed)
            assert missing.status_code == 401, (path, missing.text)
            assert missing.json()["error"]["code"] == "unauthorized"
        # A wrong key with a malformed body is a failed attempt and is counted.
        wrong = {**malformed, "headers": {**malformed["headers"], "X-API-Key": "wrong-key-0000"}}
        assert (await http.post("/api/runs", **wrong)).status_code == 401
        assert (await http.post("/api/runs", **wrong)).status_code == 401
        assert (await http.post("/api/runs", **wrong)).status_code == 429
    async with make_client(api_keys=TEST_API_KEY) as http:
        good = {**malformed, "headers": {**malformed["headers"], "X-API-Key": TEST_API_KEY}}
        parsed = await http.post("/api/runs", **good)
        assert parsed.status_code == 422
        assert parsed.json()["error"]["code"] == "validation_error"


async def test_rate_limit_envelope_and_retry_after(make_client) -> None:
    async with make_client(rate_limit_default="2/minute") as http:
        assert (await http.get("/api/templates")).status_code == 200
        assert (await http.get("/api/tags")).status_code == 200
        limited = await http.get("/api/templates")
        assert limited.status_code == 429
        body = limited.json()
        assert body["error"]["code"] == "rate_limited"
        assert body["error"]["details"]["retry_after"] >= 1
        assert int(limited.headers["retry-after"]) == body["error"]["details"]["retry_after"]
        # Health checks are never limited.
        for _ in range(3):
            assert (await http.get("/api/health")).status_code == 200


async def test_rate_limit_identity_by_key(make_client) -> None:
    async with make_client(
        api_keys=f"{TEST_API_KEY},{OTHER_API_KEY}", rate_limit_default="1/minute"
    ) as http:
        first = await http.get("/api/templates", headers={"X-API-Key": TEST_API_KEY})
        other = await http.get("/api/templates", headers={"X-API-Key": OTHER_API_KEY})
        again = await http.get("/api/templates", headers={"X-API-Key": TEST_API_KEY})
        assert (first.status_code, other.status_code, again.status_code) == (200, 200, 429)
        # Meta is not authenticated but uses the key identity when a valid key is sent.
        assert (await http.get("/api/meta", headers={"X-API-Key": TEST_API_KEY})).status_code == 429
        assert (await http.get("/api/meta")).status_code == 200


async def test_rate_limit_identity_by_ip_behind_trusted_proxy(make_client) -> None:
    async with make_client(trusted_proxies="127.0.0.1", rate_limit_default="1/minute") as http:
        # httpx's ASGI transport reports the peer as 127.0.0.1.
        a = await http.get("/api/templates", headers={"X-Forwarded-For": "198.51.100.1"})
        b = await http.get("/api/templates", headers={"X-Forwarded-For": "198.51.100.2"})
        a2 = await http.get("/api/templates", headers={"X-Forwarded-For": "198.51.100.1"})
        assert (a.status_code, b.status_code, a2.status_code) == (200, 200, 429)


async def test_rate_limit_switch_off(make_client) -> None:
    async with make_client(rate_limit_default="1/minute", rate_limit_enabled=False) as http:
        for _ in range(3):
            assert (await http.get("/api/templates")).status_code == 200


async def test_security_headers(client) -> None:
    response = await client.get("/api/health")
    headers = response.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cross-origin-opener-policy"] == "same-origin"
    assert headers["cross-origin-resource-policy"] == "same-origin"
    assert headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    docs = await client.get("/api/docs")
    assert docs.status_code == 200
    assert "content-security-policy" not in docs.headers
    assert docs.headers["x-frame-options"] == "DENY"


async def test_docs_can_be_disabled(make_client) -> None:
    async with make_client(docs_enabled=False) as http:
        assert (await http.get("/api/docs")).status_code == 404
        assert (await http.get("/api/openapi.json")).status_code == 404


async def test_cors_preflight(make_client) -> None:
    async with make_client(api_keys=TEST_API_KEY) as http:
        response = await http.options(
            "/api/runs",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-api-key",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert "x-api-key" in response.headers["access-control-allow-headers"].lower()
        denied = await http.options(
            "/api/runs",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in denied.headers
        assert denied.status_code == 400
        assert denied.headers["content-type"] == "application/json"
        assert denied.json()["error"] == {
            "code": "cors_rejected",
            "message": "The cross-origin request is not allowed.",
            "details": {"rejected": ["origin"]},
        }
        assert denied.headers["x-request-id"]
        bad_header = await http.options(
            "/api/prompts",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-Custom",
            },
        )
        assert bad_header.status_code == 400
        assert bad_header.json()["error"]["details"] == {"rejected": ["headers"]}
        # The allowed origin is still echoed, as Starlette computed it.
        assert bad_header.headers["access-control-allow-origin"] == "http://localhost:5173"
        simple = await http.get("/api/health", headers={"Origin": "http://localhost:3000"})
        exposed = simple.headers["access-control-expose-headers"].lower()
        assert "x-request-id" in exposed
        assert "retry-after" in exposed
        assert "content-disposition" in exposed


async def test_request_id_echo_and_validation(client) -> None:
    echoed = await client.get("/api/health", headers={"X-Request-ID": "abc.DEF_123-x"})
    assert echoed.headers["x-request-id"] == "abc.DEF_123-x"
    replaced = await client.get("/api/health", headers={"X-Request-ID": "bad id with spaces"})
    assert replaced.headers["x-request-id"] != "bad id with spaces"
    assert len(replaced.headers["x-request-id"]) == 32
    generated = await client.get("/api/health")
    assert len(generated.headers["x-request-id"]) == 32
