"""Shared API response conventions (F9): pagination, error envelope, job status.

Heavy lists are server-paginated (Page); errors are a single, consistent envelope; long-running work
is polled via JobStatus. These shapes are stable across every surface.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field


class Page[T](BaseModel):
    """A server-paginated slice. `has_more` is derived so clients can lazily fetch."""

    items: list[T]
    total: int
    page: int = 1
    page_size: int = 50

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_more(self) -> bool:
        return self.page * self.page_size < self.total


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Every error response is `{"error": {"code", "message"}}` (see app/errors.py)."""

    error: ErrorDetail


class JobStatus(BaseModel):
    """Polling shape for async work (ingest/provision/carry-forward)."""

    run_id: str
    status: str  # running | ok | failed
    stats: dict[str, object] = Field(default_factory=dict)
