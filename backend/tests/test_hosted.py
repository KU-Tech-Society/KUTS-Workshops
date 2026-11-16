import asyncio
import json
import tomllib
from pathlib import Path

import fakeredis.aioredis
import pytest
from fastapi import HTTPException
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import httpx
from urllib.parse import parse_qs, urlsplit

from app.persistence import Repository
from app.hosted_auth import HostedAuth, HostedSettings
from app.hosted import create_hosted_app
from upstash_redis.asyncio import Redis


def test_vercel_manifest_declares_all_backend_runtime_dependencies():
    root = Path(__file__).resolve().parents[2]
    manifest = tomllib.loads((root / "pyproject.toml").read_text())
    requirements = {
        line.strip()
        for line in (root / "backend/requirements.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert set(manifest["project"]["dependencies"]) == requirements
    assert manifest["tool"]["vercel"]["entrypoint"] == "backend.main:app"


def test_vercel_function_includes_built_organiser_frontend():
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "vercel.json").read_text())
    assert config["functions"]["backend/main.py"]["includeFiles"] == "public/**"
    assert "build:hosted" in config["buildCommand"]


def test_hosted_serves_bundled_organiser_html_and_assets(monkeypatch, tmp_path):
    import app.hosted as hosted

    public = tmp_path / "public"
    (public / "assets").mkdir(parents=True)
    (public / "index.html").write_text(
        '<html><div id="root"></div><script src="/assets/organiser.js"></script></html>'
    )
    (public / "assets/organiser.js").write_text('console.log("fixture");')
    monkeypatch.setattr(hosted, "__file__", str(tmp_path / "backend/app/hosted.py"))
    first, second, repository, fake = hosted_clients()
    with first:
        response = first.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert '<div id="root">' in response.text
        asset = first.get("/assets/organiser.js")
        assert asset.status_code == 200
        assert 'console.log("fixture");' in asset.text
        assert first.get("/api/intake").status_code == 401
        assert fake.invite_calls == []


class TestRedis(fakeredis.aioredis.FakeRedis):
    __test__ = False

    async def eval(self, script, keys=None, args=None):
        keys = keys or []
        return await super().eval(script, len(keys), *keys, *(args or []))


def test_repository_lease_fencing_and_shared_state():
    async def scenario():
        redis = TestRedis(decode_responses=True)
        first = Repository(redis)
        second = Repository(redis)
        async with first.lock("operations") as lease:
            await lease.save("state", {"consumed": True}, 900)
            assert await second.get("state") == {"consumed": True}
            with pytest.raises(HTTPException) as conflict:
                async with second.lock("operations"):
                    pass
            assert conflict.value.status_code == 409
            await redis.set(first.key("lock:operations"), "replacement")
            with pytest.raises(HTTPException):
                await lease.save("state", {"consumed": False}, 900)
        assert await redis.get(first.key("lock:operations")) == "replacement"
        assert await second.get("state") == {"consumed": True}

    asyncio.run(scenario())


def test_repository_rate_limit_and_single_use_values():
    async def scenario():
        redis = TestRedis(decode_responses=True)
        repository = Repository(redis)
        await repository.put("oauth:state", {"verifier": "test"}, 600)
        assert await repository.take("oauth:state") == {"verifier": "test"}
        assert await repository.take("oauth:state") is None
        await repository.limited("student", 1)
        with pytest.raises(HTTPException) as limited:
            await Repository(redis).limited("student", 1)
        assert limited.value.status_code == 429

    asyncio.run(scenario())


def test_oauth_pkce_allowlist_and_single_use_state():
    repository = Repository(TestRedis(decode_responses=True))
    settings = HostedSettings(
        "https://workshops.example", "client-id", "client-secret", frozenset({"123"})
    )
    requests = []

    def github(request):
        requests.append(request)
        if request.url.path.endswith("access_token"):
            assert "code_verifier=" in request.content.decode()
            return httpx.Response(200, json={"access_token": "private-oauth-token"})
        return httpx.Response(200, json={"id": 123, "login": "organiser"})

    auth = HostedAuth(
        repository, settings, httpx.AsyncClient(transport=httpx.MockTransport(github))
    )
    app = FastAPI()

    @app.get("/auth/login")
    async def login():
        return await auth.login()

    @app.get("/auth/callback")
    async def callback(request: Request):
        return await auth.callback(request)

    @app.get("/me")
    async def me(request: Request):
        return await auth.session(request)

    with TestClient(app, base_url=settings.origin, follow_redirects=False) as client:
        assert client.get("/me").status_code == 401
        started = client.get("/auth/login")
        query = parse_qs(urlsplit(started.headers["location"]).query)
        assert query["code_challenge_method"] == ["S256"]
        assert (
            "HttpOnly" in started.headers["set-cookie"]
            and "Secure" in started.headers["set-cookie"]
        )
        assert client.get("/auth/callback?state=wrong&code=test").status_code == 400
        callback_url = f"/auth/callback?state={query['state'][0]}&code=test"
        response = client.get(callback_url)
        assert response.status_code == 307
        assert "private-oauth-token" not in response.text + response.headers.get(
            "set-cookie", ""
        )
        assert client.get("/me").json()["login"] == "organiser"
        assert client.get(callback_url).status_code == 400
        assert len(requests) == 2


def hosted_clients():
    from test_api import FakeGitHub

    redis = TestRedis(decode_responses=True)
    repository = Repository(redis)
    settings = HostedSettings(
        "https://workshops.example",
        "client-id",
        "client-secret",
        frozenset({"123", "456"}),
    )
    fake = FakeGitHub()
    first = TestClient(
        create_hosted_app(repository, settings, fake), base_url=settings.origin
    )
    second = TestClient(
        create_hosted_app(Repository(redis), settings, fake), base_url=settings.origin
    )
    return first, second, repository, fake


def sign_in(client, repository, token="test-session", user_id=123):
    from app.hosted_auth import digest

    asyncio.run(
        repository.put(
            f"session:{digest(token)}",
            {"id": user_id, "login": "organiser", "csrf_token": "test-csrf"},
            28800,
        )
    )
    client.cookies.set(HostedAuth.cookie, token)
    return {"Origin": "https://workshops.example", "X-CSRF-Token": "test-csrf"}


def test_hosted_intake_survives_instances_and_rejects_public_admin_access():
    first, second, repository, fake = hosted_clients()
    with first, second:
        assert first.get("/api/intake").status_code == 401
        headers = sign_in(first, repository)
        opened = first.post("/api/intake", headers=headers, json={"enabled": True})
        assert opened.status_code == 200
        response = second.post(
            "/api/submissions",
            headers={"Origin": "https://ku-tech-society.github.io"},
            json={
                "username": "@student-one",
                "join_code": opened.json()["join_code"].lower(),
                "workshop": "AIW",
            },
        )
        assert response.status_code == 202
        assert response.json() == {"accepted": True}
        sign_in(second, repository)
        assert second.get("/api/intake").json()["submissions"][0]["workshop"] == "AIW"
        assert first.post("/api/intake", json={"enabled": False}).status_code == 403
        assert (
            first.get(
                "/api/intake", headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert (
            first.get("/api/health", headers={"Host": "evil.example"}).status_code
            == 400
        )
        assert fake.invite_calls == []


def test_hosted_confirmation_is_durable_and_bound_to_organiser():
    first, second, repository, fake = hosted_clients()
    with first, second:
        headers = sign_in(first, repository)
        preview = first.post(
            "/api/previews",
            headers=headers,
            json={"source": "lines", "text": "ready-student"},
        ).json()
        resolved = first.post(
            f"/api/previews/{preview['id']}/resolve",
            headers=headers,
            json={"team_id": 8},
        )
        assert resolved.status_code == 200
        entry = resolved.json()["entries"][0]
        other_headers = sign_in(second, repository, "other-session", 456)
        assert (
            second.post(
                f"/api/previews/{preview['id']}/confirm-and-send",
                headers=other_headers,
                json={"confirmed": True, "selected_entry_ids": [entry["id"]]},
            ).status_code
            == 404
        )
        body = {"confirmed": True, "selected_entry_ids": [entry["id"]]}
        sent = first.post(
            f"/api/previews/{preview['id']}/confirm-and-send",
            headers=headers,
            json=body,
        )
        assert sent.status_code == 200, sent.text
        assert fake.invite_calls == [(22, [8])]
        assert sent.json()["results"][0]["status"] == "invitation_sent"
        sign_in(second, repository)
        assert (
            second.post(
                f"/api/previews/{preview['id']}/confirm-and-send",
                headers=headers,
                json=body,
            ).status_code
            == 409
        )
        assert (
            second.get("/api/batches/latest").json()["batch"]["id"] == sent.json()["id"]
        )
        assert len(fake.invite_calls) == 1


def test_upstash_sdk_command_contract_with_local_redis():
    async def scenario():
        local = fakeredis.aioredis.FakeRedis(decode_responses=True)
        sdk = Redis(url="https://unused.example", token="test-only", rest_retries=0)

        async def execute(*, command, **kwargs):
            value = await local.execute_command(*command)
            return "OK" if command[0] == "SET" and value is True else value

        sdk._http.execute = execute
        repository = Repository(sdk)
        async with repository.lock("sdk") as lease:
            await lease.save("state", {"saved": True}, 60)
            assert await repository.get("state") == {"saved": True}
            await lease.renew()
        await repository.put("one-use", {"value": 1}, 60)
        assert await repository.take("one-use") == {"value": 1}
        await repository.limited("sdk", 1)
        with pytest.raises(HTTPException):
            await repository.limited("sdk", 1)

    asyncio.run(scenario())


def test_interrupted_invitation_is_saved_unknown_and_never_replayed():
    first, second, repository, fake = hosted_clients()
    with first, second:
        headers = sign_in(first, repository)
        preview = first.post(
            "/api/previews",
            headers=headers,
            json={"source": "lines", "text": "ready-student"},
        ).json()
        entry = first.post(
            f"/api/previews/{preview['id']}/resolve", headers=headers, json={}
        ).json()["entries"][0]
        calls = []

        async def interrupted(account_id, team_ids, role):
            saved = await repository.get("core")
            assert saved["previews"][0]["consumed"] is True
            assert saved["batches"][0]["results"][0]["status"] == "status_unknown"
            calls.append(account_id)
            await repository.redis.delete(repository.key("lock:operations"))
            raise RuntimeError(
                "test-only transport interruption with sensitive upstream details"
            )

        fake.invite = interrupted
        body = {"confirmed": True, "selected_entry_ids": [entry["id"]]}
        response = first.post(
            f"/api/previews/{preview['id']}/confirm-and-send",
            headers=headers,
            json=body,
        )
        assert response.status_code in {409, 503}
        assert "sensitive upstream details" not in response.text
        sign_in(second, repository)
        recovered = second.get("/api/batches/latest").json()["batch"]
        assert recovered["running"] is False
        assert recovered["results"][0]["status"] == "status_unknown"
        assert (
            second.post(
                f"/api/previews/{preview['id']}/confirm-and-send",
                headers=headers,
                json=body,
            ).status_code
            == 409
        )
        assert calls == [22]


def test_batch_owner_survives_preview_expiry_and_other_organiser_activity():
    first, second, repository, fake = hosted_clients()
    with first, second:
        headers = sign_in(first, repository)
        preview = first.post(
            "/api/previews",
            headers=headers,
            json={"source": "lines", "text": "ready-student"},
        ).json()
        entry = first.post(
            f"/api/previews/{preview['id']}/resolve", headers=headers, json={}
        ).json()["entries"][0]
        sent = first.post(
            f"/api/previews/{preview['id']}/confirm-and-send",
            headers=headers,
            json={"confirmed": True, "selected_entry_ids": [entry["id"]]},
        ).json()

        async def expire():
            raw = await repository.get("core")
            raw["previews"] = []
            raw["owners"].pop(preview["id"])
            await repository.put("core", raw, 86400)

        asyncio.run(expire())
        other = sign_in(second, repository, "other-session", 456)
        assert (
            second.post(
                "/api/previews",
                headers=other,
                json={"source": "lines", "text": "ready-student-2"},
            ).status_code
            == 200
        )
        assert second.get(f"/api/batches/{sent['id']}").status_code == 404
        assert first.get(f"/api/batches/{sent['id']}").status_code == 200


def test_hosted_logout_revokes_session_and_public_api_rejects_bad_requests():
    first, second, repository, fake = hosted_clients()
    with first, second:
        headers = sign_in(first, repository)
        assert (
            first.post("/api/auth/logout", headers=headers, json={}).status_code == 200
        )
        assert first.get("/api/intake").status_code == 401
        response = second.post(
            "/api/submissions",
            headers={
                "Origin": "https://ku-tech-society.github.io",
                "Content-Type": "application/json",
            },
            content=iter([b"x" * 1024] * 3),
        )
        assert response.status_code == 413
        response = second.post(
            "/api/submissions", headers={"Origin": "https://evil.example"}, json={}
        )
        assert response.status_code == 403
        assert fake.invite_calls == []


def test_hosted_storage_errors_are_redacted():
    first, second, repository, fake = hosted_clients()

    async def unavailable(*args, **kwargs):
        raise RuntimeError("redis-password-must-not-escape")

    repository.redis.get = unavailable
    with first:
        first.cookies.set(HostedAuth.cookie, "opaque")
        response = first.get("/api/intake")
        assert response.status_code == 503
        assert "redis-password" not in response.text
        assert fake.invite_calls == []


def test_oauth_unapproved_account_never_receives_an_organiser_session():
    from test_api import FakeGitHub

    repository = Repository(TestRedis(decode_responses=True))
    settings = HostedSettings(
        "https://workshops.example", "client-id", "client-secret", frozenset({"123"})
    )
    fake = FakeGitHub()

    def github(request):
        if request.url.path.endswith("access_token"):
            return httpx.Response(200, json={"access_token": "private-test-token"})
        return httpx.Response(200, json={"id": 999, "login": "not-approved"})

    app = create_hosted_app(
        repository,
        settings,
        fake,
        httpx.AsyncClient(transport=httpx.MockTransport(github)),
    )
    with TestClient(app, base_url=settings.origin, follow_redirects=False) as client:
        started = client.get("/auth/login")
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
        response = client.get(f"/auth/callback?state={state}&code=test")
        assert response.status_code == 403
        assert HostedAuth.cookie not in response.headers.get("set-cookie", "")
        assert client.get("/api/intake").status_code == 401
        assert "private-test-token" not in response.text
        assert fake.invite_calls == []


def test_hosted_clear_rotates_shared_code_and_rejects_old_code():
    first, second, repository, fake = hosted_clients()
    with first, second:
        headers = sign_in(first, repository)
        opened = first.post(
            "/api/intake", headers=headers, json={"enabled": True}
        ).json()
        submission = {
            "username": "student-one",
            "join_code": opened["join_code"],
            "workshop": "CW",
        }
        student_headers = {"Origin": "https://ku-tech-society.github.io"}
        assert (
            second.post(
                "/api/submissions", headers=student_headers, json=submission
            ).status_code
            == 202
        )
        assert (
            first.request(
                "DELETE", "/api/session", headers=headers, json={"confirm": True}
            ).status_code
            == 200
        )
        current = first.get("/api/intake").json()
        assert current["submissions"] == [] and current["enabled"] is False
        assert current["join_code"] != opened["join_code"]
        first.post("/api/intake", headers=headers, json={"enabled": True})
        assert (
            second.post(
                "/api/submissions", headers=student_headers, json=submission
            ).status_code
            == 403
        )
        assert fake.invite_calls == []


def test_hosted_expired_review_and_removed_account_fail_closed():
    first, second, repository, fake = hosted_clients()
    with first, second:
        headers = sign_in(first, repository)
        preview = first.post(
            "/api/previews",
            headers=headers,
            json={"source": "lines", "text": "ready-student"},
        ).json()
        entry = first.post(
            f"/api/previews/{preview['id']}/resolve", headers=headers, json={}
        ).json()["entries"][0]

        async def expire():
            raw = await repository.get("core")
            raw["previews"][0]["expires_at"] = 0
            await repository.put("core", raw, 86400)

        asyncio.run(expire())
        response = first.post(
            f"/api/previews/{preview['id']}/confirm-and-send",
            headers=headers,
            json={"confirmed": True, "selected_entry_ids": [entry["id"]]},
        )
        assert response.status_code == 410
        sign_in(second, repository, "removed-session", 999)
        assert second.get("/api/intake").status_code == 401
        assert fake.invite_calls == []
