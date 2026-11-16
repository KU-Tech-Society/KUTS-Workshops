import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class HostedSettings:
    origin: str
    client_id: str
    client_secret: str
    organiser_ids: frozenset[str]
    student_origin: str = "https://ku-tech-society.github.io"

    @classmethod
    def from_env(cls):
        settings = cls(
            origin=os.environ["APP_ORIGIN"].rstrip("/"),
            client_id=os.environ["GITHUB_OAUTH_CLIENT_ID"],
            client_secret=os.environ["GITHUB_OAUTH_CLIENT_SECRET"],
            organiser_ids=frozenset(
                value.strip()
                for value in os.environ["ORGANISER_GITHUB_IDS"].split(",")
                if value.strip()
            ),
            student_origin=os.getenv(
                "STUDENT_ORIGIN", "https://ku-tech-society.github.io"
            ).rstrip("/"),
        )
        for origin in (settings.origin, settings.student_origin):
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Hosted origins must be HTTPS origins without a path.")
        if not settings.organiser_ids or not all(
            value.isascii() and value.isdigit() for value in settings.organiser_ids
        ):
            raise ValueError("Configure approved organiser numeric GitHub IDs.")
        if not settings.client_id or not settings.client_secret:
            raise ValueError("Configure GitHub OAuth credentials.")
        return settings


class HostedAuth:
    cookie = "__Host-workshop-session"
    oauth_cookie = "__Host-workshop-oauth"

    def __init__(self, repository, settings, client=None):
        self.repository = repository
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=10)

    async def session(self, request: Request):
        token = request.cookies.get(self.cookie, "")
        session = (
            await self.repository.get(f"session:{digest(token)}") if token else None
        )
        if not session or str(session["id"]) not in self.settings.organiser_ids:
            raise HTTPException(
                401, "Sign in with an approved organiser GitHub account."
            )
        return session

    async def login(self):
        await self.repository.limited("login", 30)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        await self.repository.put(f"oauth:{digest(state)}", {"verifier": verifier}, 600)
        response = RedirectResponse(
            "https://github.com/login/oauth/authorize?"
            + urlencode(
                {
                    "client_id": self.settings.client_id,
                    "redirect_uri": f"{self.settings.origin}/auth/callback",
                    "scope": "",
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "allow_signup": "false",
                }
            )
        )
        response.set_cookie(
            self.oauth_cookie,
            state,
            max_age=600,
            secure=True,
            httponly=True,
            samesite="lax",
        )
        return response

    async def callback(self, request: Request):
        state = request.query_params.get("state", "")
        browser_state = request.cookies.get(self.oauth_cookie, "")
        if not state or not secrets.compare_digest(
            state.encode(), browser_state.encode()
        ):
            raise HTTPException(
                400, "Sign-in state did not match. Start sign-in again."
            )
        saved = await self.repository.take(f"oauth:{digest(state)}")
        code = request.query_params.get("code")
        if not saved or not code:
            raise HTTPException(
                400, "Sign-in expired or was already used. Start again."
            )
        try:
            token_response = await self.client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.settings.client_id,
                    "client_secret": self.settings.client_secret,
                    "code": code,
                    "redirect_uri": f"{self.settings.origin}/auth/callback",
                    "code_verifier": saved["verifier"],
                },
            )
            token_response.raise_for_status()
            token = token_response.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise ValueError("Missing OAuth token")
            profile_response = await self.client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            profile_response.raise_for_status()
            profile = profile_response.json()
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            raise HTTPException(
                502, "GitHub sign-in could not be completed. Try again."
            ) from exc
        if str(profile.get("id")) not in self.settings.organiser_ids or not isinstance(
            profile.get("login"), str
        ):
            raise HTTPException(
                403, "This GitHub account is not an approved organiser."
            )
        previous = request.cookies.get(self.cookie)
        if previous:
            await self.repository.take(f"session:{digest(previous)}")
        session_token = secrets.token_urlsafe(32)
        await self.repository.put(
            f"session:{digest(session_token)}",
            {
                "id": profile["id"],
                "login": profile["login"],
                "csrf_token": secrets.token_urlsafe(32),
            },
            28800,
        )
        response = RedirectResponse("/")
        response.delete_cookie(
            self.oauth_cookie, secure=True, httponly=True, samesite="lax"
        )
        response.set_cookie(
            self.cookie,
            session_token,
            max_age=28800,
            secure=True,
            httponly=True,
            samesite="lax",
        )
        return response
