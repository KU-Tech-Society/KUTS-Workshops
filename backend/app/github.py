import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from .config import GITHUB_API_URL, GITHUB_API_VERSION, MAX_GITHUB_PAGES, ORGANIZATION


class GitHubError(Exception):
    def __init__(self, message: str, *, status_code: int = 502, retry_after: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class AmbiguousInvitationError(GitHubError):
    pass


class GitHubClient:
    def __init__(self, token: str | None):
        self.token = token
        self.client = httpx.AsyncClient(
            base_url=GITHUB_API_URL,
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
                "User-Agent": "KU-Computing-Workshops-Onboarding",
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    def require_token(self) -> None:
        if not self.token:
            raise GitHubError("Set GITHUB_TOKEN in the project .env file before using GitHub features.", status_code=503)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        self.require_token()
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = await self.client.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            if method == "POST" and path.endswith("/invitations"):
                raise AmbiguousInvitationError("Invitation request timed out.", status_code=504) from exc
            raise GitHubError("GitHub request timed out. No invitation was sent by this request.", status_code=504) from exc
        except httpx.HTTPError as exc:
            if method == "POST" and path.endswith("/invitations"):
                raise AmbiguousInvitationError("Invitation request outcome could not be confirmed.", status_code=502) from exc
            raise GitHubError("Could not connect to GitHub.", status_code=502) from exc

        if response.status_code < 400:
            return response

        message = ""
        try:
            data = response.json()
            message = str(data.get("message", "")) if isinstance(data, dict) else ""
        except ValueError:
            pass

        retry_after = _retry_after_seconds(response)
        rate_limited = (
            response.status_code == 429
            or response.headers.get("x-ratelimit-remaining") == "0"
            or (response.status_code == 403 and bool(re.search(r"secondary rate limit|abuse detection", message, re.I)))
        )
        if rate_limited:
            raise GitHubError(
                "GitHub rate limit reached. Stop and review the rate-limit guidance before continuing.",
                status_code=429,
                retry_after=retry_after,
            )
        if method == "POST" and path.endswith("/invitations") and response.status_code >= 500:
            raise AmbiguousInvitationError("GitHub returned an error while creating the invitation.", status_code=502)
        if response.status_code in (401, 403):
            raise GitHubError(
                "GitHub denied access. Check that the token has the required organization Members permission, "
                "is approved for the organization and SSO, and belongs to an organization owner.",
                status_code=403,
            )
        raise GitHubError(
            "GitHub rejected the request. Review token access, organization settings, and the submitted account.",
            status_code=response.status_code if response.status_code < 500 else 502,
        )

    async def paginated(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, MAX_GITHUB_PAGES + 1):
            response = await self._request("GET", path, params={"per_page": 100, "page": page})
            try:
                data = response.json()
            except ValueError as exc:
                raise GitHubError("GitHub returned an invalid paginated response.") from exc
            if not isinstance(data, list):
                raise GitHubError("GitHub returned an unexpected paginated response.")
            items.extend(item for item in data if isinstance(item, dict))
            if len(data) < 100:
                return items
        raise GitHubError("GitHub list exceeded the local pagination safety limit; no partial result was used.")

    async def teams(self) -> list[dict[str, Any]]:
        return await self.paginated(f"/orgs/{ORGANIZATION}/teams")

    async def members(self) -> list[dict[str, Any]]:
        return await self.paginated(f"/orgs/{ORGANIZATION}/members")

    async def invitations(self) -> list[dict[str, Any]]:
        return await self.paginated(f"/orgs/{ORGANIZATION}/invitations")

    async def user(self, login: str) -> dict[str, Any] | None:
        try:
            response = await self._request("GET", f"/users/{quote(login, safe='')}")
        except GitHubError as exc:
            if exc.status_code == 404:
                return None
            raise
        try:
            data = response.json()
        except ValueError as exc:
            raise GitHubError("GitHub returned an invalid user response.") from exc
        if not isinstance(data, dict):
            raise GitHubError("GitHub returned an unexpected user response.")
        return data

    async def invite(self, account_id: int, team_ids: list[int], role: str) -> dict[str, Any]:
        if role != "direct_member":
            raise GitHubError("Only ordinary-member invitations are supported.", status_code=400)
        body: dict[str, Any] = {"invitee_id": account_id, "role": role}
        if team_ids:
            body["team_ids"] = team_ids
        response = await self._request("POST", f"/orgs/{ORGANIZATION}/invitations", json=body)
        try:
            data = response.json()
        except ValueError as exc:
            raise AmbiguousInvitationError("GitHub created or may have created an invitation but returned an invalid response.") from exc
        if not isinstance(data, dict):
            raise GitHubError("GitHub returned an unexpected invitation response.")
        return data


def _retry_after_seconds(response: httpx.Response) -> int | None:
    raw = response.headers.get("retry-after")
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0, int((retry_at - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError):
                pass
    if response.headers.get("x-ratelimit-remaining") == "0":
        try:
            reset = int(response.headers["x-ratelimit-reset"])
            return max(0, reset - int(datetime.now(timezone.utc).timestamp()))
        except (KeyError, ValueError):
            pass
    return None
