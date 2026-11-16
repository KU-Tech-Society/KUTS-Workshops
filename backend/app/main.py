import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware

from .config import (
    BACKEND_PORT,
    BATCH_TTL_SECONDS,
    FRONTEND_ORIGIN,
    MAX_INPUT_BYTES,
    MAX_INPUT_ROWS,
    MAX_INVITES_PER_BATCH,
    ORGANIZATION,
    PREVIEW_TTL_SECONDS,
)
from .github import AmbiguousInvitationError, GitHubClient, GitHubError
from .intake import Intake
from .parsing import ImportErrorDetail, parse_import
from .state import Batch, MemoryStore, Preview, PreviewEntry


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    text: str = Field(max_length=MAX_INPUT_BYTES)
    username_column: int | None = None
    has_header: bool = False


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: int | None = None


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool
    selected_entry_ids: list[str] = Field(
        min_length=1, max_length=MAX_INVITES_PER_BATCH
    )


class ClearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool


class HealthResponse(BaseModel):
    status: Literal["ok"]
    github_token_configured: bool
    max_input_bytes: int
    max_input_rows: int
    max_invites_per_batch: int


class OrganizationResponse(BaseModel):
    login: str
    url: str


class TeamResponse(BaseModel):
    id: int
    name: str
    slug: str


class PreviewEntryResponse(BaseModel):
    id: str
    submitted_username: str
    login: str | None
    display_name: str | None
    avatar_url: str | None
    profile_url: str | None
    status: Literal[
        "awaiting_resolution",
        "invalid_input",
        "duplicate_input",
        "ready_to_invite",
        "already_member",
        "pending_invitation",
        "account_not_found",
        "lookup_failed",
        "rate_limited",
    ]
    message: str | None
    source_row: int
    retry_after_seconds: int | None


class PreviewResponse(BaseModel):
    id: str
    organization: str
    role: Literal["direct_member"]
    expires_at: str
    resolved: bool
    team: TeamResponse | None
    entries: list[PreviewEntryResponse]


class BatchResultResponse(BaseModel):
    entry_id: str
    submitted_username: str
    login: str | None
    status: Literal[
        "invitation_sent",
        "already_member",
        "pending_invitation",
        "failed",
        "status_unknown",
    ]
    message: str
    invitation_id: int | None
    rate_limited: bool
    retry_after_seconds: int | None


class BatchTotalsResponse(BaseModel):
    sent: int
    failed: int
    skipped: int


class BatchResponse(BaseModel):
    id: str
    organization: str
    role: Literal["direct_member"]
    team_id: int | None
    team_name: str | None
    created_at: str
    running: bool
    results: list[BatchResultResponse]
    totals: BatchTotalsResponse


class ClearResponse(BaseModel):
    cleared: bool


class IntakeControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class StudentSubmissionResponse(BaseModel):
    id: str
    username: str
    workshop: Literal["CW", "AIW"]
    submitted_at: str


class IntakeResponse(BaseModel):
    enabled: bool
    join_code: str
    revision: int
    expires_at: str
    submissions: list[StudentSubmissionResponse]


class LocalRequestGuard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        host_header = request.headers.get("host", "")
        allowed_hosts = {
            "127.0.0.1",
            "localhost",
            f"127.0.0.1:{BACKEND_PORT}",
            f"localhost:{BACKEND_PORT}",
        }
        if host_header.lower() not in allowed_hosts:
            return JSONResponse(
                {"detail": "Requests must target the local server."}, status_code=400
            )

        origin = request.headers.get("origin")
        if origin is not None and origin != FRONTEND_ORIGIN:
            return JSONResponse(
                {"detail": "Unexpected browser origin."}, status_code=403
            )

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if origin != FRONTEND_ORIGIN:
                return JSONResponse(
                    {
                        "detail": "A valid local frontend origin is required for changes."
                    },
                    status_code=403,
                )
            content_type = (
                request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            )
            if content_type != "application/json":
                return JSONResponse(
                    {"detail": "Write requests must use application/json."},
                    status_code=415,
                )
            length = request.headers.get("content-length")
            if length:
                try:
                    if int(length) > MAX_INPUT_BYTES + 4096:
                        return JSONResponse(
                            {
                                "detail": "Request body exceeds the configured size limit."
                            },
                            status_code=413,
                        )
                except ValueError:
                    return JSONResponse(
                        {"detail": "Invalid request size."}, status_code=400
                    )

        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    github = app.state.github
    if hasattr(github, "close"):
        await github.close()


def create_app(github_client: Any | None = None) -> FastAPI:
    app = FastAPI(
        title="Workshop Onboarding", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.state.github = github_client or GitHubClient(os.getenv("GITHUB_TOKEN"))
    app.state.store = MemoryStore(PREVIEW_TTL_SECONDS, BATCH_TTL_SECONDS)
    app.state.intake = Intake()
    app.state.batch_guard = asyncio.Lock()
    app.state.batch_running = False
    app.state.checkpoint = None

    app.add_middleware(LocalRequestGuard)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(GitHubError)
    async def github_error_handler(_: Request, exc: GitHubError):
        body: dict[str, Any] = {"detail": str(exc)}
        if exc.retry_after is not None:
            body["retry_after_seconds"] = exc.retry_after
        return JSONResponse(body, status_code=exc.status_code)

    @app.get("/api/health", response_model=HealthResponse)
    async def health():
        return {
            "status": "ok",
            "github_token_configured": (
                bool(app.state.github.token)
                if hasattr(app.state.github, "token")
                else True
            ),
            "max_input_bytes": MAX_INPUT_BYTES,
            "max_input_rows": MAX_INPUT_ROWS,
            "max_invites_per_batch": MAX_INVITES_PER_BATCH,
        }

    @app.get("/api/organisation", response_model=OrganizationResponse)
    async def organisation():
        return {"login": ORGANIZATION, "url": f"https://github.com/{ORGANIZATION}"}

    @app.get("/api/intake", response_model=IntakeResponse)
    async def get_intake():
        return app.state.intake.snapshot()

    @app.post("/api/intake", response_model=IntakeResponse)
    async def control_intake(body: IntakeControl):
        app.state.intake.snapshot()
        app.state.intake.enabled = body.enabled
        app.state.intake.revision += 1
        return app.state.intake.snapshot()

    @app.get("/api/intake/events")
    async def intake_events(request: Request):
        async def events():
            revision = -1
            while not await request.is_disconnected():
                snapshot = app.state.intake.snapshot()
                if snapshot["revision"] != revision:
                    revision = snapshot["revision"]
                    yield f"data: {json.dumps(snapshot)}\n\n"
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/teams", response_model=list[TeamResponse])
    async def teams():
        data = await app.state.github.teams()
        return [
            {"id": team["id"], "name": team["name"], "slug": team["slug"]}
            for team in data
            if isinstance(team.get("id"), int)
            and isinstance(team.get("name"), str)
            and isinstance(team.get("slug"), str)
        ]

    @app.post("/api/previews", response_model=PreviewResponse)
    async def create_preview(body: ImportRequest):
        try:
            imported = parse_import(
                source=body.source,
                text=body.text,
                username_column=body.username_column,
                has_header=body.has_header,
                max_bytes=MAX_INPUT_BYTES,
                max_rows=MAX_INPUT_ROWS,
            )
        except ImportErrorDetail as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        entries = [
            PreviewEntry(
                id=secrets.token_urlsafe(12),
                submitted=item.submitted,
                source_row=item.source_row,
                status=item.status,
                message=item.message,
                login=item.login,
            )
            for item in imported
        ]
        preview = app.state.store.add_preview(entries)
        return _preview_response(preview)

    @app.post("/api/previews/{preview_id}/resolve", response_model=PreviewResponse)
    async def resolve_preview(preview_id: str, body: ResolveRequest):
        preview = _get_preview(app.state.store, preview_id)
        if preview.resolved or preview.consumed:
            raise HTTPException(
                status_code=409,
                detail="This preview was already resolved or used. Create a fresh review.",
            )

        teams_data = await app.state.github.teams()
        selected_team = (
            next((team for team in teams_data if team.get("id") == body.team_id), None)
            if body.team_id is not None
            else None
        )
        if body.team_id is not None and selected_team is None:
            raise HTTPException(
                status_code=422,
                detail="Selected team is not available in the fixed organisation.",
            )

        members, invitations = await asyncio.gather(
            app.state.github.members(),
            app.state.github.invitations(),
        )
        member_ids = {
            member.get("id") for member in members if isinstance(member.get("id"), int)
        }
        member_logins = {str(member.get("login", "")).casefold() for member in members}
        pending_logins = {
            str(invitation.get("login", "")).casefold()
            for invitation in invitations
            if invitation.get("login")
        }

        for entry in preview.entries:
            if entry.status != "awaiting_resolution" or not entry.login:
                continue
            try:
                user = await app.state.github.user(entry.login)
            except GitHubError as exc:
                entry.status = (
                    "rate_limited" if exc.status_code == 429 else "lookup_failed"
                )
                entry.message = str(exc)
                entry.retry_after_seconds = exc.retry_after
                if exc.status_code == 429:
                    for remaining in preview.entries:
                        if remaining.status == "awaiting_resolution":
                            remaining.status = "rate_limited"
                            remaining.message = str(exc)
                            remaining.retry_after_seconds = exc.retry_after
                    break
                continue
            if user is None:
                entry.status = "account_not_found"
                entry.message = "No GitHub account matched this username."
                continue

            resolved_login = str(user.get("login", ""))
            account_id = user.get("id")
            if not resolved_login or not isinstance(account_id, int):
                entry.status = "lookup_failed"
                entry.message = "GitHub returned incomplete account information."
                continue
            entry.login = resolved_login
            entry.account_id = account_id
            entry.display_name = (
                user.get("name") if isinstance(user.get("name"), str) else None
            )
            entry.avatar_url = (
                user.get("avatar_url")
                if isinstance(user.get("avatar_url"), str)
                else None
            )

            key = resolved_login.casefold()
            if account_id in member_ids or key in member_logins:
                entry.status = "already_member"
                entry.message = (
                    "Already a member. Team assignment is not changed by this tool."
                )
            elif key in pending_logins:
                entry.status = "pending_invitation"
                entry.message = "An organisation invitation is already pending."
            else:
                entry.status = "ready_to_invite"

        preview.resolved = True
        if selected_team:
            preview.team_id = selected_team["id"]
            preview.team_name = selected_team["name"]
            preview.team_slug = selected_team["slug"]
        return _preview_response(preview)

    @app.post(
        "/api/previews/{preview_id}/confirm-and-send", response_model=BatchResponse
    )
    async def confirm_and_send(preview_id: str, body: ConfirmRequest):
        preview = _get_preview(app.state.store, preview_id)
        if not body.confirmed:
            raise HTTPException(
                status_code=400, detail="Explicit confirmation is required."
            )
        if not preview.resolved or preview.consumed:
            raise HTTPException(
                status_code=409,
                detail="Preview is unresolved, expired, or already used. Create a fresh review.",
            )
        if preview.organization != ORGANIZATION or preview.role != "direct_member":
            raise HTTPException(
                status_code=409,
                detail="The reviewed organisation or role is no longer valid. Create a fresh review.",
            )
        selected_ids = set(body.selected_entry_ids)
        if len(selected_ids) != len(body.selected_entry_ids):
            raise HTTPException(
                status_code=422, detail="Selected accounts must be unique."
            )
        eligible = {
            entry.id: entry
            for entry in preview.entries
            if entry.status == "ready_to_invite" and entry.account_id
        }
        if not selected_ids or not selected_ids.issubset(eligible):
            raise HTTPException(
                status_code=422,
                detail="Selection includes an account that is not eligible in this reviewed preview.",
            )
        if len(selected_ids) > MAX_INVITES_PER_BATCH:
            raise HTTPException(
                status_code=422,
                detail=f"Select no more than {MAX_INVITES_PER_BATCH} accounts per batch.",
            )

        async with app.state.batch_guard:
            if app.state.batch_running:
                raise HTTPException(
                    status_code=409,
                    detail="Another invitation batch is currently running.",
                )
            if preview.consumed:
                raise HTTPException(
                    status_code=409,
                    detail="This preview was already used. Create a fresh review.",
                )
            app.state.batch_running = True
            preview.consumed = True
            batch = app.state.store.add_batch(preview)
            preview.batch_id = batch.id

        try:
            batch.results = [
                _result(
                    eligible[entry_id],
                    "status_unknown",
                    "Processing was not completed. Review GitHub before any fresh retry.",
                )
                for entry_id in body.selected_entry_ids
            ]
            if app.state.checkpoint:
                await app.state.checkpoint()
            for index, entry_id in enumerate(body.selected_entry_ids):
                entry = eligible[entry_id]
                result = await _invite_one(app.state.github, entry, preview)
                batch.results[index] = result
                if app.state.checkpoint:
                    await app.state.checkpoint()
                if result["status"] == "failed" and result.get("rate_limited"):
                    for remaining_index, remaining_id in enumerate(
                        body.selected_entry_ids[index + 1 :], start=index + 1
                    ):
                        remaining = eligible[remaining_id]
                        batch.results[remaining_index] = _result(
                            remaining,
                            "failed",
                            "Batch stopped after GitHub rate limiting; review before starting a new batch.",
                        )
                    break
                if index + 1 < len(body.selected_entry_ids):
                    await asyncio.sleep(1)
        finally:
            batch.running = False
            app.state.batch_running = False
            if app.state.checkpoint:
                await app.state.checkpoint()

        return _batch_response(batch)

    @app.get("/api/batches/{batch_id}", response_model=BatchResponse)
    async def get_batch(batch_id: str):
        app.state.store.clean()
        batch = app.state.store.batches.get(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Batch not found or expired.")
        return _batch_response(batch)

    @app.delete("/api/session", response_model=ClearResponse)
    async def clear_session(body: ClearRequest):
        if not body.confirm:
            raise HTTPException(
                status_code=400,
                detail="Explicit clear-session confirmation is required.",
            )
        if app.state.batch_running:
            raise HTTPException(
                status_code=409,
                detail="Wait for the running invitation batch to finish before clearing the session.",
            )
        app.state.store.clear()
        app.state.intake.clear()
        return {"cleared": True}

    return app


def _get_preview(store: MemoryStore, preview_id: str) -> Preview:
    store.clean()
    preview = store.previews.get(preview_id)
    if preview is None:
        raise HTTPException(
            status_code=410,
            detail="Preview expired or not found. Import and review the accounts again.",
        )
    return preview


async def _invite_one(
    github: Any, entry: PreviewEntry, preview: Preview
) -> dict[str, Any]:
    if entry.account_id is None or entry.login is None:
        return _result(
            entry, "failed", "Resolved account data is missing. Create a fresh review."
        )
    try:
        members, invitations = await asyncio.gather(
            github.members(), github.invitations()
        )
    except GitHubError as exc:
        return _result(
            entry,
            "failed",
            f"Could not recheck organisation state: {exc}",
            rate_limited=exc.status_code == 429,
            retry_after_seconds=exc.retry_after,
        )

    member_ids = {
        member.get("id") for member in members if isinstance(member.get("id"), int)
    }
    member_logins = {str(member.get("login", "")).casefold() for member in members}
    pending = {
        str(invitation.get("login", "")).casefold(): invitation
        for invitation in invitations
        if invitation.get("login")
    }
    if (
        entry.account_id in member_ids
        or (entry.login or "").casefold() in member_logins
    ):
        return _result(
            entry,
            "already_member",
            "Account became an organisation member after review; no invitation sent.",
        )
    if (entry.login or "").casefold() in pending:
        return _result(
            entry,
            "pending_invitation",
            "An invitation became pending after review; no invitation sent.",
        )

    try:
        response = await github.invite(
            entry.account_id,
            [preview.team_id] if preview.team_id is not None else [],
            preview.role,
        )
        return _result(
            entry,
            "invitation_sent",
            "Invitation sent. The student must accept it.",
            response.get("id"),
        )
    except AmbiguousInvitationError:
        return await _reconcile_ambiguous(github, entry)
    except GitHubError as exc:
        return _result(
            entry,
            "failed",
            str(exc),
            rate_limited=exc.status_code == 429,
            retry_after_seconds=exc.retry_after,
        )


async def _reconcile_ambiguous(github: Any, entry: PreviewEntry) -> dict[str, Any]:
    try:
        members, invitations = await asyncio.gather(
            github.members(), github.invitations()
        )
    except GitHubError:
        return _result(
            entry,
            "status_unknown",
            "Invitation request outcome is unknown. Review GitHub organisation members and pending invitations before any retry.",
        )
    pending = next(
        (
            invitation
            for invitation in invitations
            if str(invitation.get("login", "")).casefold()
            == (entry.login or "").casefold()
        ),
        None,
    )
    if pending:
        return _result(
            entry,
            "status_unknown",
            "A pending invitation appeared after the timeout, but its source is uncertain. Do not retry; review it in GitHub.",
            pending.get("id"),
        )
    member_ids = {
        member.get("id") for member in members if isinstance(member.get("id"), int)
    }
    member_logins = {str(member.get("login", "")).casefold() for member in members}
    if (
        entry.account_id in member_ids
        or (entry.login or "").casefold() in member_logins
    ):
        return _result(
            entry,
            "status_unknown",
            "Account is now a member, but the invitation outcome cannot be proven. Review organisation activity.",
        )
    return _result(
        entry,
        "status_unknown",
        "Invitation request outcome is unknown. Review GitHub organisation members and pending invitations before any retry.",
    )


def _result(
    entry: PreviewEntry,
    status: str,
    message: str,
    invitation_id: int | None = None,
    *,
    rate_limited: bool = False,
    retry_after_seconds: int | None = None,
) -> dict[str, Any]:
    return {
        "entry_id": entry.id,
        "submitted_username": entry.submitted,
        "login": entry.login,
        "status": status,
        "message": message,
        "invitation_id": invitation_id if isinstance(invitation_id, int) else None,
        "rate_limited": rate_limited,
        "retry_after_seconds": retry_after_seconds,
    }


def _preview_response(preview: Preview) -> dict[str, Any]:
    return {
        "id": preview.id,
        "organization": preview.organization,
        "role": preview.role,
        "expires_at": datetime.fromtimestamp(
            preview.expires_at, timezone.utc
        ).isoformat(),
        "resolved": preview.resolved,
        "team": (
            {
                "id": preview.team_id,
                "name": preview.team_name,
                "slug": preview.team_slug,
            }
            if preview.team_id is not None
            else None
        ),
        "entries": [entry.public() for entry in preview.entries],
    }


def _batch_response(batch: Batch) -> dict[str, Any]:
    return {
        "id": batch.id,
        "organization": batch.organization,
        "role": batch.role,
        "team_id": batch.team_id,
        "team_name": batch.team_name,
        "created_at": datetime.fromtimestamp(
            batch.created_at, timezone.utc
        ).isoformat(),
        "running": batch.running,
        "results": batch.results,
        "totals": {
            "sent": sum(
                result["status"] == "invitation_sent" for result in batch.results
            ),
            "failed": sum(
                result["status"] in {"failed", "status_unknown"}
                for result in batch.results
            ),
            "skipped": sum(
                result["status"] in {"already_member", "pending_invitation"}
                for result in batch.results
            ),
        },
    }


app = create_app()
