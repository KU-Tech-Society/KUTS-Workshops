from fastapi.testclient import TestClient

from app.github import AmbiguousInvitationError, GitHubError
from app.main import create_app


ORIGIN = "http://127.0.0.1:5173"
HEADERS = {"Origin": ORIGIN, "Content-Type": "application/json"}


class FakeGitHub:
    token = "test-token"

    def __init__(self):
        self.member_rows = [{"id": 20, "login": "private-member"}]
        self.invitation_rows = [{"id": 33, "login": "waiting-student"}]
        self.invite_calls = []
        self.fail_invite_ids = set()
        self.ambiguous_invite_ids = set()
        self.rate_limited_logins = set()
        self.users = {
            "private-member": {"id": 20, "login": "private-member", "name": None, "avatar_url": "https://avatars.githubusercontent.com/u/20"},
            "waiting-student": {"id": 21, "login": "waiting-student", "name": "Wait", "avatar_url": "https://avatars.githubusercontent.com/u/21"},
            "ready-student": {"id": 22, "login": "ready-student", "name": "Ready", "avatar_url": "https://avatars.githubusercontent.com/u/22"},
            "ready-student-2": {"id": 23, "login": "ready-student-2", "name": "Ready 2", "avatar_url": "https://avatars.githubusercontent.com/u/23"},
        }

    async def close(self):
        pass

    async def teams(self):
        return [{"id": 8, "name": "Workshop cohort", "slug": "workshop-cohort"}]

    async def members(self):
        return list(self.member_rows)

    async def invitations(self):
        return list(self.invitation_rows)

    async def user(self, login):
        if login in self.rate_limited_logins:
            raise GitHubError("GitHub rate limit reached.", status_code=429, retry_after=12)
        return self.users.get(login)

    async def invite(self, account_id, team_ids, role):
        self.invite_calls.append((account_id, team_ids))
        assert role == "direct_member"
        if account_id in self.fail_invite_ids:
            raise GitHubError("GitHub rejected this invitation.", status_code=422)
        if account_id in self.ambiguous_invite_ids:
            self.invitation_rows.append({"id": 501, "login": "ready-student"})
            raise AmbiguousInvitationError("Invitation timed out.")
        return {"id": 90 + len(self.invite_calls)}


def make_client(fake=None):
    github = fake or FakeGitHub()
    return TestClient(create_app(github), base_url="http://127.0.0.1:8000"), github


def import_preview(client, usernames="private-member\nwaiting-student\nready-student"):
    response = client.post(
        "/api/previews",
        headers=HEADERS,
        json={"source": "lines", "text": usernames, "has_header": False},
    )
    assert response.status_code == 200
    return response.json()


def resolve(client, preview_id, team_id=8):
    return client.post(
        f"/api/previews/{preview_id}/resolve",
        headers=HEADERS,
        json={"team_id": team_id},
    )


def test_resolves_private_members_and_pending_invitations_without_misclassifying():
    client, _ = make_client()
    with client:
        preview = import_preview(client)
        response = resolve(client, preview["id"])

    assert response.status_code == 200
    entries = {row["login"]: row for row in response.json()["entries"]}
    assert entries["private-member"]["status"] == "already_member"
    assert entries["waiting-student"]["status"] == "pending_invitation"
    assert entries["ready-student"]["status"] == "ready_to_invite"
    assert response.json()["team"] == {"id": 8, "name": "Workshop cohort", "slug": "workshop-cohort"}
    assert "account_id" not in entries["ready-student"]


def test_confirmation_required_and_selection_cannot_include_unreviewed_accounts():
    client, fake = make_client()
    with client:
        preview = import_preview(client)
        resolved = resolve(client, preview["id"]).json()
        ready = next(row for row in resolved["entries"] if row["status"] == "ready_to_invite")

        no_confirmation = client.post(
            f"/api/previews/{preview['id']}/confirm-and-send",
            headers=HEADERS,
            json={"confirmed": False, "selected_entry_ids": [ready["id"]]},
        )
        tampered = client.post(
            f"/api/previews/{preview['id']}/confirm-and-send",
            headers=HEADERS,
            json={"confirmed": True, "selected_entry_ids": ["attacker-chosen-id"]},
        )

    assert no_confirmation.status_code == 400
    assert tampered.status_code == 422
    assert fake.invite_calls == []


def test_invitation_uses_server_resolved_id_direct_member_role_and_bound_team():
    client, fake = make_client()
    with client:
        preview = import_preview(client, "ready-student")
        resolved = resolve(client, preview["id"], team_id=8).json()
        ready = resolved["entries"][0]
        response = client.post(
            f"/api/previews/{preview['id']}/confirm-and-send",
            headers=HEADERS,
            json={"confirmed": True, "selected_entry_ids": [ready["id"]]},
        )

    assert response.status_code == 200
    assert response.json()["totals"] == {"sent": 1, "failed": 0, "skipped": 0}
    assert fake.invite_calls == [(22, [8])]
    assert response.json()["results"][0]["invitation_id"] == 91
    assert response.json()["organization"] == "KU-Computing-Workshops"
    assert response.json()["role"] == "direct_member"
    assert response.json()["team_id"] == 8


def test_membership_changed_after_preview_is_skipped_without_invitation():
    client, fake = make_client()
    with client:
        preview = import_preview(client, "ready-student")
        resolved = resolve(client, preview["id"], team_id=None).json()
        ready = resolved["entries"][0]
        fake.member_rows.append({"id": 22, "login": "ready-student"})
        response = client.post(
            f"/api/previews/{preview['id']}/confirm-and-send",
            headers=HEADERS,
            json={"confirmed": True, "selected_entry_ids": [ready["id"]]},
        )

    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "already_member"
    assert fake.invite_calls == []


def test_rejects_unexpected_origin_and_non_json_writes():
    client, _ = make_client()
    with client:
        wrong_origin = client.post(
            "/api/previews",
            headers={"Origin": "https://attacker.example", "Content-Type": "application/json"},
            json={"source": "lines", "text": "ready-student"},
        )
        wrong_type = client.post(
            "/api/previews",
            headers={"Origin": ORIGIN, "Content-Type": "text/plain"},
            content='{"source":"lines","text":"ready-student"}',
        )

    assert wrong_origin.status_code == 403
    assert wrong_type.status_code == 415


def test_unknown_account_and_team_are_reported_without_inviting():
    client, fake = make_client()
    with client:
        preview = import_preview(client, "missing-student")
        unknown_team = resolve(client, preview["id"], team_id=999)
        assert unknown_team.status_code == 422
        response = resolve(client, preview["id"], team_id=None)

    assert response.status_code == 200
    assert response.json()["entries"][0]["status"] == "account_not_found"
    assert fake.invite_calls == []


def test_expired_preview_cannot_be_confirmed():
    client, _ = make_client()
    with client:
        preview = import_preview(client, "ready-student")
        resolved = resolve(client, preview["id"], team_id=None).json()
        entry = resolved["entries"][0]
        client.app.state.store.previews[preview["id"]].expires_at = 0
        response = client.post(
            f"/api/previews/{preview['id']}/confirm-and-send",
            headers=HEADERS,
            json={"confirmed": True, "selected_entry_ids": [entry["id"]]},
        )

    assert response.status_code == 410


def test_used_preview_cannot_be_submitted_twice():
    client, fake = make_client()
    with client:
        preview = import_preview(client, "ready-student")
        entry = resolve(client, preview["id"], team_id=None).json()["entries"][0]
        request = {
            "confirmed": True,
            "selected_entry_ids": [entry["id"]],
        }
        first = client.post(f"/api/previews/{preview['id']}/confirm-and-send", headers=HEADERS, json=request)
        second = client.post(f"/api/previews/{preview['id']}/confirm-and-send", headers=HEADERS, json=request)

    assert first.status_code == 200
    assert second.status_code == 409
    assert len(fake.invite_calls) == 1


def test_timeout_with_pending_invitation_is_marked_unknown_and_not_retried():
    fake = FakeGitHub()
    fake.ambiguous_invite_ids.add(22)
    client, fake = make_client(fake)
    with client:
        preview = import_preview(client, "ready-student")
        entry = resolve(client, preview["id"], team_id=None).json()["entries"][0]
        response = client.post(
            f"/api/previews/{preview['id']}/confirm-and-send",
            headers=HEADERS,
            json={"confirmed": True, "selected_entry_ids": [entry["id"]]},
        )

    result = response.json()["results"][0]
    assert response.status_code == 200
    assert result["status"] == "status_unknown"
    assert result["invitation_id"] == 501
    assert len(fake.invite_calls) == 1


def test_rate_limit_stops_lookup_and_exposes_retry_after():
    fake = FakeGitHub()
    fake.rate_limited_logins.add("ready-student")
    client, _ = make_client(fake)
    with client:
        preview = import_preview(client, "ready-student\nready-student-2")
        response = resolve(client, preview["id"], team_id=None)

    entries = response.json()["entries"]
    assert [entry["status"] for entry in entries] == ["rate_limited", "rate_limited"]
    assert all(entry["retry_after_seconds"] == 12 for entry in entries)


def test_request_cannot_replace_fixed_organisation_or_role():
    client, fake = make_client()
    with client:
        response = client.post(
            "/api/previews",
            headers=HEADERS,
            json={"source": "lines", "text": "ready-student", "organization": "attacker-org"},
        )
    assert response.status_code == 422
    assert fake.invite_calls == []


def test_partial_batch_failure_is_reported_without_hiding_successes():
    fake = FakeGitHub()
    fake.fail_invite_ids.add(22)
    client, fake = make_client(fake)
    with client:
        preview = import_preview(client, "ready-student\nready-student-2")
        entries = resolve(client, preview["id"], team_id=None).json()["entries"]
        response = client.post(
            f"/api/previews/{preview['id']}/confirm-and-send",
            headers=HEADERS,
            json={"confirmed": True, "selected_entry_ids": [entry["id"] for entry in entries]},
        )

    assert response.status_code == 200
    assert response.json()["totals"] == {"sent": 1, "failed": 1, "skipped": 0}
    assert [result["status"] for result in response.json()["results"]] == ["failed", "invitation_sent"]
    assert len(fake.invite_calls) == 2


def test_health_never_returns_configured_token():
    client, _ = make_client()
    with client:
        response = client.get("/api/health")
    assert response.json() == {
        "status": "ok",
        "github_token_configured": True,
        "max_input_bytes": 1_048_576,
        "max_input_rows": 500,
        "max_invites_per_batch": 50,
    }
    assert "test-token" not in response.text


def test_rejects_malformed_or_nonlocal_host_headers():
    client, _ = make_client()
    with client:
        response = client.get("/api/health", headers={"Host": "attacker.example"})
    assert response.status_code == 400
