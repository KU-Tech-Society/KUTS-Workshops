import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from .config import ORGANIZATION


@dataclass
class PreviewEntry:
    id: str
    submitted: str
    source_row: int
    status: str
    message: str | None = None
    login: str | None = None
    account_id: int | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    retry_after_seconds: int | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "submitted_username": self.submitted,
            "login": self.login,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "profile_url": f"https://github.com/{self.login}" if self.login else None,
            "status": self.status,
            "message": self.message,
            "source_row": self.source_row,
            "retry_after_seconds": self.retry_after_seconds,
        }


@dataclass
class Preview:
    id: str
    created_at: float
    expires_at: float
    entries: list[PreviewEntry]
    organization: str
    role: str
    team_id: int | None = None
    team_name: str | None = None
    team_slug: str | None = None
    resolved: bool = False
    consumed: bool = False
    batch_id: str | None = None


@dataclass
class Batch:
    id: str
    created_at: float
    expires_at: float
    preview_id: str
    organization: str
    role: str
    team_id: int | None
    team_name: str | None
    results: list[dict[str, Any]] = field(default_factory=list)
    running: bool = True


class MemoryStore:
    def __init__(self, preview_ttl: int, batch_ttl: int):
        self.preview_ttl = preview_ttl
        self.batch_ttl = batch_ttl
        self.previews: dict[str, Preview] = {}
        self.batches: dict[str, Batch] = {}

    def clean(self) -> None:
        now = time.time()
        self.previews = {key: value for key, value in self.previews.items() if value.expires_at > now}
        self.batches = {key: value for key, value in self.batches.items() if value.expires_at > now or value.running}

    def add_preview(self, entries: list[PreviewEntry]) -> Preview:
        self.clean()
        if len(self.previews) >= 20:
            oldest_id = min(self.previews, key=lambda key: self.previews[key].created_at)
            del self.previews[oldest_id]
        now = time.time()
        preview = Preview(
            id=secrets.token_urlsafe(32),
            created_at=now,
            expires_at=now + self.preview_ttl,
            entries=entries,
            organization=ORGANIZATION,
            role="direct_member",
        )
        self.previews[preview.id] = preview
        return preview

    def add_batch(self, preview: Preview) -> Batch:
        self.clean()
        if len(self.batches) >= 100:
            oldest_id = min(self.batches, key=lambda key: self.batches[key].created_at)
            if not self.batches[oldest_id].running:
                del self.batches[oldest_id]
        now = time.time()
        batch = Batch(
            id=secrets.token_urlsafe(32),
            created_at=now,
            expires_at=now + self.batch_ttl,
            preview_id=preview.id,
            organization=preview.organization,
            role=preview.role,
            team_id=preview.team_id,
            team_name=preview.team_name,
        )
        self.batches[batch.id] = batch
        return batch

    def clear(self) -> None:
        self.previews.clear()
        self.batches.clear()
