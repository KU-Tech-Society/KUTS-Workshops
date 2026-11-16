import os
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware

from .intake import Intake
from .parsing import ImportErrorDetail


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=256)
    join_code: str = Field(min_length=1, max_length=128)
    workshop: Literal["CW", "AIW"]


def create_student_app(store: Intake) -> FastAPI:
    origin = os.getenv("STUDENT_ORIGIN", "https://ku-tech-society.github.io").rstrip(
        "/"
    )
    host = os.getenv("STUDENT_API_HOST", "127.0.0.1:8001").lower()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    class StudentGuard(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.headers.get("host", "").lower() != host:
                return JSONResponse(
                    {"detail": "Unexpected student API host."}, status_code=400
                )
            if request.headers.get("origin") != origin:
                return JSONResponse(
                    {"detail": "Unexpected student page origin."}, status_code=403
                )
            if request.url.path != "/api/submissions" or request.method != "POST":
                return JSONResponse({"detail": "Not found."}, status_code=404)
            if not store.allow_attempt():
                return JSONResponse(
                    {"detail": "Too many submissions. Wait one minute."},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
            if (
                request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                return JSONResponse(
                    {"detail": "Use application/json."}, status_code=415
                )
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 2048:
                    return JSONResponse(
                        {"detail": "Submission exceeds 2 KiB."}, status_code=413
                    )
            request._body = bytes(body)
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response

    app.add_middleware(StudentGuard)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin],
        allow_methods=["POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_submission(_: Request, __: RequestValidationError):
        return JSONResponse(
            {
                "detail": "Enter a username, workshop code, and workshop (CW or AIW), within the size limits."
            },
            status_code=422,
        )

    @app.post("/api/submissions", status_code=202)
    async def submit(body: Submission):
        try:
            store.submit(body.username, body.join_code, body.workshop)
        except PermissionError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=403)
        except ImportErrorDetail as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        except OverflowError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=429)
        return {"accepted": True}

    return app
