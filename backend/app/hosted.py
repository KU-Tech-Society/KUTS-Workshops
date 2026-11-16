import asyncio
import os
import secrets
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from upstash_redis.asyncio import Redis

from .config import (
    BATCH_TTL_SECONDS,
    FRONTEND_ORIGIN,
    MAX_INPUT_BYTES,
    PREVIEW_TTL_SECONDS,
)
from .github import GitHubClient
from .hosted_auth import HostedAuth, HostedSettings, digest
from .intake import Intake
from .main import ClearRequest, IntakeControl, IntakeResponse, create_app
from .parsing import ImportErrorDetail
from .persistence import Repository
from .state import Batch, MemoryStore, Preview, PreviewEntry
from .student import Submission


def restore_core(data):
    store = MemoryStore(PREVIEW_TTL_SECONDS, BATCH_TTL_SECONDS)
    if data:
        for saved in data.get("previews", []):
            preview = Preview(
                **{
                    **saved,
                    "entries": [PreviewEntry(**entry) for entry in saved["entries"]],
                }
            )
            store.previews[preview.id] = preview
        for saved in data.get("batches", []):
            batch = Batch(**saved)
            store.batches[batch.id] = batch
    store.clean()
    return store


def restore_intake(data):
    intake = Intake()
    if data:
        intake.enabled = data["enabled"]
        intake.code = data["join_code"]
        intake.revision = data["revision"]
        intake.expires_at = datetime.fromisoformat(data["expires_at"]).timestamp()
        intake.rows = {
            f"{row['workshop']}:{row['username'].casefold()}": row
            for row in data["submissions"]
        }
    intake.snapshot()
    return intake


class LeasedGitHub:
    def __init__(self, client, lease):
        self.client = client
        self.lease = lease
        self.token = client.token

    def __getattr__(self, name):
        async def guarded(*args, **kwargs):
            await self.lease.renew()
            result = await getattr(self.client, name)(*args, **kwargs)
            await self.lease.renew()
            return result

        return guarded


def create_hosted_app(
    repository=None, settings=None, github_client=None, oauth_client=None
):
    settings = settings or HostedSettings.from_env()
    if repository is None:
        if not os.environ["UPSTASH_REDIS_REST_URL"].startswith("https://"):
            raise ValueError("Redis REST URL must use HTTPS.")
        repository = Repository(
            Redis.from_env(rest_retries=0, allow_telemetry=False),
            os.getenv(
                "REDIS_NAMESPACE", f"kuts-{os.getenv('VERCEL_ENV', 'development')}"
            ),
        )
    auth = HostedAuth(repository, settings, oauth_client)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.repository = repository

    @app.middleware("http")
    async def guard(request: Request, call_next):
        try:
            if (
                request.headers.get("host", "").lower()
                != urlsplit(settings.origin).netloc.lower()
            ):
                raise HTTPException(400, "Unexpected application host.")
            path = request.url.path
            origin = request.headers.get("origin")
            student = path == "/api/submissions"
            if student:
                if request.method != "POST" or origin != settings.student_origin:
                    raise HTTPException(
                        403, "Unexpected student request origin or method."
                    )
                await repository.limited("student", 120)
            else:
                if origin is not None and origin != settings.origin:
                    raise HTTPException(403, "Unexpected organiser origin.")
                if path.startswith("/api/"):
                    request.state.organiser = await auth.session(request)
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                if (
                    request.headers.get("content-type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                    != "application/json"
                ):
                    raise HTTPException(415, "Write requests require application/json.")
                if not student:
                    if origin != settings.origin:
                        raise HTTPException(
                            403, "Same-origin confirmation is required."
                        )
                    csrf = request.headers.get("x-csrf-token", "")
                    if not secrets.compare_digest(
                        csrf.encode(), request.state.organiser["csrf_token"].encode()
                    ):
                        raise HTTPException(
                            403, "Refresh the page before making changes."
                        )
                    await repository.limited(
                        f"organiser:{request.state.organiser['id']}", 120
                    )
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > (2048 if student else MAX_INPUT_BYTES + 4096):
                        raise HTTPException(
                            413, "Request exceeds the configured size limit."
                        )
                request._body = bytes(body)
            response = await call_next(request)
        except HTTPException as exc:
            response = JSONResponse(
                {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
            )
        except Exception:
            response = JSONResponse(
                {
                    "detail": "The hosted service is unavailable. No automatic retry was made; review saved results before any new batch."
                },
                status_code=503,
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.student_origin],
        allow_methods=["POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError):
        return JSONResponse(
            {
                "detail": "Check the request fields, workshop (CW or AIW), and size limits."
            },
            status_code=422,
        )

    @app.get("/auth/login")
    async def login():
        return await auth.login()

    @app.get("/auth/callback")
    async def callback(request: Request):
        return await auth.callback(request)

    @app.get("/api/auth/session")
    async def session(request: Request):
        return {**request.state.organiser, "hosted": True}

    @app.post("/api/auth/logout")
    async def logout(request: Request):
        await repository.take(f"session:{digest(request.cookies.get(auth.cookie, ''))}")
        response = JSONResponse({"signed_out": True})
        response.delete_cookie(auth.cookie, secure=True, httponly=True, samesite="lax")
        return response

    async def intake_operation(operation):
        async with repository.lock("intake") as lease:
            intake = restore_intake(await repository.get("intake"))
            operation(intake)
            snapshot = intake.snapshot()
            await lease.save(
                "intake", snapshot, max(1, int(intake.expires_at - time.time()))
            )
            return snapshot

    @app.post("/api/submissions", status_code=202)
    async def submit(body: Submission):
        try:
            await intake_operation(
                lambda intake: intake.submit(
                    body.username, body.join_code, body.workshop
                )
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ImportErrorDetail as exc:
            raise HTTPException(422, str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(429, str(exc)) from exc
        return {"accepted": True}

    @app.get("/api/intake", response_model=IntakeResponse)
    async def get_intake():
        return await intake_operation(lambda intake: None)

    @app.post("/api/intake", response_model=IntakeResponse)
    async def control_intake(body: IntakeControl):
        def update(intake):
            intake.enabled = body.enabled
            intake.revision += 1

        return await intake_operation(update)

    async def forward(request, lease=None):
        raw = await repository.get("core") or {}
        store = restore_core(raw)
        owners = raw.get("owners", {})
        if not lease:
            active = await repository.redis.get(repository.key("lock:operations"))
            if not active:
                for batch in store.batches.values():
                    batch.running = False
        else:
            for batch in store.batches.values():
                batch.running = False
        organiser_id = str(request.state.organiser["id"])
        parts = request.url.path.split("/")
        if len(parts) >= 4 and parts[2] in {"previews", "batches"}:
            target = parts[3]
            if owners.get(target) != organiser_id:
                raise HTTPException(
                    404, "Review or batch not found for this organiser."
                )
        github = github_client or GitHubClient(os.getenv("GITHUB_TOKEN"))
        core = create_app(LeasedGitHub(github, lease) if lease else github)
        core.state.store = store

        async def checkpoint():
            for batch in store.batches.values():
                owners[batch.id] = owners.get(
                    batch.id, owners.get(batch.preview_id, organiser_id)
                )
            await lease.renew()
            await lease.save(
                "core",
                {
                    "previews": [
                        asdict(preview) for preview in store.previews.values()
                    ],
                    "batches": [asdict(batch) for batch in store.batches.values()],
                    "owners": {
                        key: value
                        for key, value in owners.items()
                        if key in store.previews or key in store.batches
                    },
                },
                max(BATCH_TTL_SECONDS, PREVIEW_TTL_SECONDS),
            )

        core.state.checkpoint = checkpoint if lease else None
        try:
            async with asyncio.timeout(240):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=core),
                    base_url="http://127.0.0.1:8000",
                ) as client:
                    response = await client.request(
                        request.method,
                        request.url.path,
                        content=await request.body(),
                        headers={
                            "Origin": FRONTEND_ORIGIN,
                            "Content-Type": "application/json",
                        },
                    )
            if lease and response.status_code < 300:
                if request.url.path == "/api/previews":
                    owners[response.json()["id"]] = organiser_id
                await checkpoint()
            if request.method == "DELETE" and response.status_code < 300:
                await intake_operation(lambda intake: intake.clear())
            if response.status_code == 422:
                return JSONResponse(
                    {
                        "detail": "Check your selection and request fields. Targets cannot be replaced."
                    },
                    status_code=422,
                )
            return JSONResponse(response.json(), status_code=response.status_code)
        except TimeoutError as exc:
            raise HTTPException(
                504,
                "The operation exceeded its time budget. Check saved results; do not resend this batch.",
            ) from exc
        finally:
            if github_client is None:
                await github.close()

    @app.get("/api/batches/latest")
    async def latest_batch(request: Request):
        from .main import _batch_response

        raw = await repository.get("core") or {}
        store = restore_core(raw)
        owned = [
            batch
            for batch in store.batches.values()
            if raw.get("owners", {}).get(batch.id) == str(request.state.organiser["id"])
        ]
        if not owned:
            return {"batch": None}
        batch = max(owned, key=lambda value: value.created_at)
        if not await repository.redis.get(repository.key("lock:operations")):
            batch.running = False
        return {"batch": _batch_response(batch)}

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "DELETE"])
    async def organiser_api(request: Request, path: str):
        if path == "intake/events":
            raise HTTPException(404, "Use the hosted inbox polling endpoint.")
        if request.method == "GET":
            return await forward(request)
        if request.method == "DELETE":
            body = ClearRequest.model_validate_json(await request.body())
            if not body.confirm:
                raise HTTPException(400, "Explicit confirmation is required.")
        async with repository.lock("operations") as lease:
            return await forward(request, lease)

    public = Path(__file__).resolve().parents[2] / "public"

    @app.get("/")
    async def organiser_page():
        if (public / "index.html").exists():
            return FileResponse(public / "index.html")
        return JSONResponse(
            {"detail": "Build the hosted organiser frontend before serving this page."},
            status_code=503,
        )

    if (public / "assets").exists():
        app.mount("/assets", StaticFiles(directory=public / "assets"), name="assets")
    return app
