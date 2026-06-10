"""Source registry (Settings · admin): the app's ingestion points as persisted configuration.

GET /api/admin/sources composes control.ingest_source (persisted registry, seeded by migration
0006) with config/schedules.yaml and the last ingest_run — naming which origin is ACTIVE
(database fixture vs online) per LLM_MODE. The enable switch persists, is audited, and is
ENFORCED: a disabled source refuses to scan with a readable 409, and re-enabling restores it.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.main import create_app
from app.services import sources as sources_svc

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app import migrate

    migrate.run()
    with TestClient(create_app()) as c:
        yield c


@needs_db
def test_registry_lists_every_ingestion_point(client: TestClient) -> None:
    rows = client.get("/api/admin/sources").json()
    by_key = {r["key"]: r for r in rows}
    # the six seeded ingestion points, every one naming both origins + the active one
    assert set(by_key) == {"jira", "sow", "news", "trends", "benchmarks", "vendor"}
    for r in rows:
        assert r["tier"] in ("T1", "T2", "T3", "T4", "T5")
        assert r["origin_recorded"] and r["origin_live"]
        # hermetic test run: the app picks from the database-backed recorded origin and says so
        assert r["mode"] == "recorded" and r["origin_active"] == r["origin_recorded"]
        assert r["status"] in ("ok", "stale", "never_run", "disabled")
        assert r["cadence"] in ("hourly", "weekly", "monthly", "on-upload")
    # scheduled sources carry their cron + next run; upload sources are on-demand
    assert by_key["news"]["cron"] == "0 6 * * MON" and by_key["news"]["next_run"]
    assert by_key["benchmarks"]["cadence"] == "monthly"
    assert by_key["sow"]["cron"] is None and by_key["sow"]["cadence"] == "on-upload"
    # a source that has never run says so (last poll shown, not hidden)
    assert by_key["jira"]["status"] == "never_run" and by_key["jira"]["last_run"] is None


@needs_db
def test_disable_is_persisted_audited_and_enforced(client: TestClient) -> None:
    # disable -> persisted + readable status
    assert client.patch("/api/admin/sources/news", json={"enabled": False}).json()["ok"]
    row = next(r for r in client.get("/api/admin/sources").json() if r["key"] == "news")
    assert row["enabled"] is False and row["status"] == "disabled"

    # enforced at the write path: the guard every scan job calls raises (the HTTP 409 mapping is
    # asserted end-to-end in test_vendors, where a provisioned version exists). A fresh engine —
    # the app's pool is bound to the TestClient's loop.
    async def _guard_raises() -> None:
        engine = create_async_engine(os.environ["DATABASE_URL"])
        async with engine.connect() as conn:
            with pytest.raises(sources_svc.SourceDisabledError):
                await sources_svc.ensure_enabled(conn, "news")
        await engine.dispose()

    asyncio.run(_guard_raises())

    # re-enable -> restored; the flips are in the append-only audit log
    assert client.patch("/api/admin/sources/news", json={"enabled": True}).json()["enabled"]
    audit = client.get("/api/audit-log").json()
    actions = [a["action"] for a in audit if a.get("target_ref") == "source:news"]
    assert "source_disabled" in actions and "source_enabled" in actions

    # unknown source -> 404, not a silent no-op
    assert client.patch("/api/admin/sources/nope", json={"enabled": False}).status_code == 404
