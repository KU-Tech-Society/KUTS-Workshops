import time

from fastapi.testclient import TestClient

from app.intake import Intake
from app.student import create_student_app
from app.main import create_app


def setup(monkeypatch):
    monkeypatch.setenv("STUDENT_ORIGIN", "https://society.github.io")
    monkeypatch.setenv("STUDENT_API_HOST", "workshop.trycloudflare.com")
    store = Intake()
    store.enabled = True
    client = TestClient(
        create_student_app(store), base_url="https://workshop.trycloudflare.com"
    )
    return store, client


def post(client, store, username="@Student-One", **extra):
    return client.post(
        "/api/submissions",
        headers={"Origin": "https://society.github.io"},
        json={"username": username, "join_code": store.code, "workshop": "CW", **extra},
    )


def test_submission_normalizes_deduplicates_and_returns_no_private_data(monkeypatch):
    store, client = setup(monkeypatch)
    assert post(client, store).json() == {"accepted": True}
    assert post(client, store, "https://github.com/student-one").status_code == 202
    assert [row["username"] for row in store.snapshot()["submissions"]] == [
        "Student-One"
    ]


def test_workshop_codes_are_short_and_avoid_ambiguous_characters():
    store = Intake()
    for _ in range(20):
        assert len(store.code) == 6
        assert set(store.code) <= set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
        store.clear()


def test_workshop_code_accepts_lowercase_and_surrounding_whitespace(monkeypatch):
    store, client = setup(monkeypatch)
    store.code = "K7MP4R"
    assert post(client, store, join_code="  k7mp4r  ").status_code == 202
    assert post(client, store, join_code="K7MP4Q").status_code == 403


def test_student_listener_cannot_access_organiser_routes(monkeypatch):
    store, client = setup(monkeypatch)
    for path in [
        "/api/teams",
        "/api/intake",
        "/api/previews",
        "/api/session",
        "/openapi.json",
    ]:
        response = client.post(
            path, headers={"Origin": "https://society.github.io"}, json={}
        )
        assert response.status_code == 404
    assert not store.rows


def test_workshop_selection_is_stored_and_deduplicated_per_workshop(monkeypatch):
    store, client = setup(monkeypatch)
    assert post(client, store, workshop="CW").status_code == 202
    assert post(client, store, "student-one", workshop="CW").status_code == 202
    assert post(client, store, workshop="AIW").status_code == 202
    assert post(client, store, "STUDENT-ONE", workshop="AIW").status_code == 202
    rows = store.snapshot()["submissions"]
    assert [(row["username"], row["workshop"]) for row in rows] == [
        ("Student-One", "CW"),
        ("Student-One", "AIW"),
    ]


def test_missing_or_unknown_workshop_is_rejected(monkeypatch):
    store, client = setup(monkeypatch)
    for workshop in ("unknown", "cw", "", None, 1):
        assert post(client, store, workshop=workshop).status_code == 422
    response = client.post(
        "/api/submissions",
        headers={"Origin": "https://society.github.io"},
        json={"username": "student-one", "join_code": store.code},
    )
    assert response.status_code == 422
    assert not store.rows


def test_code_origin_host_and_targets_are_restricted(monkeypatch):
    store, client = setup(monkeypatch)
    assert post(client, store, join_code="wrong").status_code == 403
    assert post(client, store, role="admin").status_code == 422
    assert post(client, store, "https://evil.example/student").status_code == 422
    assert post(client, store, "one\ntwo").status_code == 422
    assert client.post("/api/submissions", json={}).status_code == 403
    assert (
        client.post("/api/submissions", headers={"Host": "evil.example"}).status_code
        == 400
    )
    store.enabled = False
    assert post(client, store).status_code == 403


def test_expiry_clear_and_attempt_limit(monkeypatch):
    store, client = setup(monkeypatch)
    code = store.code
    assert post(client, store).status_code == 202
    store.expires_at = time.time() - 1
    assert post(client, store).status_code == 403
    assert not store.rows and store.code != code
    store.attempts.clear()
    for _ in range(120):
        assert store.allow_attempt()
    assert post(client, store).status_code == 429


def test_streamed_size_limit_and_validation_redaction(monkeypatch):
    store, client = setup(monkeypatch)
    response = client.post(
        "/api/submissions",
        headers={
            "Origin": "https://society.github.io",
            "Content-Type": "application/json",
        },
        content=iter([b"x" * 1024] * 3),
    )
    assert response.status_code == 413
    response = post(client, store, username="x" * 300)
    assert response.status_code == 422
    assert store.code not in response.text


def test_capacity_preflight_and_old_code_rejection(monkeypatch):
    import app.intake as intake_module

    monkeypatch.setattr(intake_module, "MAX_INPUT_ROWS", 1)
    store, client = setup(monkeypatch)
    response = client.options(
        "/api/submissions",
        headers={
            "Origin": "https://society.github.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"] == "https://society.github.io"
    )
    assert post(client, store).status_code == 202
    assert post(client, store, "second-student").status_code == 429
    assert post(client, store).status_code == 202
    old_code = store.code
    store.clear()
    store.enabled = True
    assert post(client, store, join_code=old_code).status_code == 403
    assert post(client, store, "second-student").status_code == 202


def test_local_control_and_shared_intake_clear_without_changing_preview(monkeypatch):
    from test_api import FakeGitHub, HEADERS, import_preview, resolve

    monkeypatch.setenv("STUDENT_ORIGIN", "https://society.github.io")
    monkeypatch.setenv("STUDENT_API_HOST", "workshop.trycloudflare.com")
    fake = FakeGitHub()
    app = create_app(fake)
    with TestClient(app, base_url="http://127.0.0.1:8000") as organiser:
        preview = import_preview(organiser, "ready-student")
        reviewed = resolve(organiser, preview["id"]).json()
        opened = organiser.post("/api/intake", headers=HEADERS, json={"enabled": True})
        assert opened.status_code == 200
        assert organiser.post("/api/intake", json={"enabled": True}).status_code == 403
        student = TestClient(
            create_student_app(app.state.intake),
            base_url="https://workshop.trycloudflare.com",
        )
        assert post(student, app.state.intake).status_code == 202
        snapshot = organiser.get("/api/intake").json()
        assert organiser.get("/api/intake").headers["cache-control"] == "no-store"
        assert len(snapshot["submissions"]) == 1
        assert snapshot["submissions"][0]["workshop"] == "CW"
        assert snapshot["revision"] > opened.json()["revision"]
        assert [
            entry.public() for entry in app.state.store.previews[preview["id"]].entries
        ] == reviewed["entries"]
        organiser.request(
            "DELETE", "/api/session", headers=HEADERS, json={"confirm": True}
        )
        assert organiser.get("/api/intake").json()["submissions"] == []
        assert not app.state.intake.enabled
        assert fake.invite_calls == []
