"""Deploy self-refresh (app.refresh) — the data plane is rebuilt to match the shipped image.

DB-backed, self-cleaning. The refresh re-provisions + re-carries every provisioned ``cat_<v>`` so a
deploy never leaves the live app serving stale catalogue / delivery numbers, and a per-schema build
marker (the schema COMMENT) makes a re-run of the SAME image a no-op — no destructive rebuild, no
embedding spend. These cover the three decisions that matter: a new build rebuilds and marks; the
same build skips (provision is never called); ``REFRESH_FORCE`` overrides the marker.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from app import db, refresh
from app.services import provision
from app.services import stories as story_svc

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


@pytest.fixture(scope="module")
def provisioned() -> Iterator[None]:
    from app import migrate

    migrate.run()

    async def _setup() -> None:
        db.init_engine()
        await provision.bring_version_online("v7")
        await story_svc.carry_forward("v7")
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            # discovery rows the run_discovery pass may create — FK-safe: every child of
            # reasoning_chain (change_flag / pending_edge / validation_gate_run / citation /
            # reasoning_step) before the chain itself, then the evidence they cite.
            await conn.execute(text("DELETE FROM control.pending_edge"))
            await conn.execute(text("DELETE FROM control.change_flag"))
            await conn.execute(text("DELETE FROM control.validation_gate_run"))
            await conn.execute(text("DELETE FROM control.citation"))
            await conn.execute(text("DELETE FROM control.reasoning_step"))
            await conn.execute(text("DELETE FROM control.reasoning_chain"))
            await conn.execute(text("DELETE FROM control.evidence_item WHERE kind = 'catalogue'"))
            await conn.execute(text("DELETE FROM control.story_use_case_carry"))
            await conn.execute(text("DELETE FROM control.story_subcap_carry"))
            await conn.execute(text("DELETE FROM control.story"))
            await conn.execute(text("DROP SCHEMA IF EXISTS cat_v7 CASCADE"))
            await conn.execute(
                text("DELETE FROM control.catalogue_version WHERE version_id = 'v7'")
            )
        await db.dispose_engine()

    asyncio.run(_setup())
    yield
    asyncio.run(_teardown())


def _sync_engine() -> object:
    return create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))


def _marker(schema: str = "cat_v7") -> str | None:
    eng = _sync_engine()
    with eng.connect() as conn:  # type: ignore[attr-defined]
        row = conn.execute(
            text(
                "SELECT obj_description(n.oid, 'pg_namespace') FROM pg_namespace n "
                "WHERE n.nspname = :s"
            ),
            {"s": schema},
        ).scalar()
    return str(row) if row is not None else None


def _set_marker(value: str, schema: str = "cat_v7") -> None:
    eng = _sync_engine()
    with eng.begin() as conn:  # type: ignore[attr-defined]
        conn.execute(text(f"COMMENT ON SCHEMA {schema} IS '{value}'"))


@needs_db
def test_new_build_rebuilds_and_marks(provisioned: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A genuinely new build re-provisions + re-carries v7 and stamps the schema with the build id —
    end to end, the data plane is real (851 subcaps, the corpus carried)."""
    monkeypatch.setenv("REFRESH_BUILD_ID", "build-rebuild")
    monkeypatch.delenv("REFRESH_FORCE", raising=False)

    rc = asyncio.run(refresh.refresh_data_plane())
    assert rc == 0
    assert _marker() == "cia-build:build-rebuild"  # provenance stamp written after the rebuild

    eng = _sync_engine()
    with eng.connect() as conn:  # type: ignore[attr-defined]
        subcaps = conn.execute(text("SELECT count(*) FROM cat_v7.subcap")).scalar()
        carried = conn.execute(text("SELECT count(*) FROM control.story_catalogue_link")).scalar()
    assert subcaps == 851  # the whole catalogue rebuilt from the bundled seed
    assert (carried or 0) > 0  # the canonical corpus re-carried onto it


@needs_db
def test_same_build_skips_without_rebuilding(
    provisioned: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the schema's marker already equals the deploying build, the version is skipped — the
    destructive re-provision is never called (so a re-run of the same image costs nothing)."""
    _set_marker("cia-build:build-skip")
    monkeypatch.setenv("REFRESH_BUILD_ID", "build-skip")
    monkeypatch.delenv("REFRESH_FORCE", raising=False)

    called: list[str] = []

    async def _never_prov(version_id: str, label: str = "") -> dict[str, int]:
        called.append(version_id)
        return {"subcaps": 0}

    async def _never_carry(
        target_version: str, source_version: str | None = None
    ) -> dict[str, int]:
        called.append(target_version)
        return {"stories_ingested": 0, "confirmed": 0, "review": 0}

    monkeypatch.setattr(provision, "bring_version_online", _never_prov)
    monkeypatch.setattr(story_svc, "carry_forward", _never_carry)

    rc = asyncio.run(refresh.refresh_data_plane())
    assert rc == 0
    assert called == []  # neither provision nor carry ran — purely a marker check


@needs_db
def test_force_overrides_matching_marker(
    provisioned: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REFRESH_FORCE=1 rebuilds even when the marker already matches the build (the operator escape
    hatch for a forced re-provision)."""
    _set_marker("cia-build:build-force")
    monkeypatch.setenv("REFRESH_BUILD_ID", "build-force")
    monkeypatch.setenv("REFRESH_FORCE", "1")

    ran: list[str] = []

    async def _spy_prov(version_id: str, label: str = "") -> dict[str, int]:
        ran.append(version_id)
        return {"subcaps": 0}

    async def _spy_carry(target_version: str, source_version: str | None = None) -> dict[str, int]:
        ran.append(target_version)
        return {"stories_ingested": 0, "confirmed": 0, "review": 0}

    monkeypatch.setattr(provision, "bring_version_online", _spy_prov)
    monkeypatch.setattr(story_svc, "carry_forward", _spy_carry)

    rc = asyncio.run(refresh.refresh_data_plane())
    assert rc == 0
    assert "v7" in ran  # forced past the matching marker -> the rebuild ran


@needs_db
def test_run_discovery_surfaces_gated_proposals_on_redeploy(provisioned: None) -> None:
    """The wiring that makes 'new use cases to commit on redeploy' actually appear: after the data
    plane is refreshed, run_discovery() scans the rebuilt version and surfaces its GATED discovery
    proposals into the Change-Flags / Notifications box. The v7 corpus has abundant delivery its use
    cases do not cover, so real NEW-use-case proposals appear — every one carrying a passing gate
    run (trust envelope, nothing shown ungated) — and a second pass proposes nothing new
    (idempotent, so a repeat deploy never duplicates)."""
    asyncio.run(refresh.run_discovery(["v7"]))

    eng = _sync_engine()
    with eng.connect() as conn:  # type: ignore[attr-defined]
        gaps = conn.execute(
            text("SELECT count(*) FROM control.change_flag WHERE kind = 'use_case_gap'")
        ).scalar()
        gated = conn.execute(
            text(
                "SELECT count(*) FROM control.change_flag cf "
                "JOIN control.validation_gate_run vg ON vg.chain_id = cf.chain_id "
                "WHERE cf.kind = 'use_case_gap'"
            )
        ).scalar()
    assert (gaps or 0) > 0  # uncovered delivery -> real gated NEW-use-case proposals to commit
    assert gated == gaps  # every surfaced proposal is gated (trust envelope; nothing ungated)

    asyncio.run(refresh.run_discovery(["v7"]))  # idempotent — a repeat deploy adds no duplicates
    with _sync_engine().connect() as conn:  # type: ignore[attr-defined]
        gaps_again = conn.execute(
            text("SELECT count(*) FROM control.change_flag WHERE kind = 'use_case_gap'")
        ).scalar()
    assert gaps_again == gaps


def test_bootstrap_versions_parses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pure unit: REFRESH_BOOTSTRAP is a comma list of valid version ids (junk is dropped), so a
    brand-new database can be told which versions to provision when none exists yet."""
    monkeypatch.setenv("REFRESH_BOOTSTRAP", "v7, v5 ,, BAD-ID")
    assert refresh._bootstrap_versions() == ["v7", "v5"]
    monkeypatch.delenv("REFRESH_BOOTSTRAP", raising=False)
    assert refresh._bootstrap_versions() == []
