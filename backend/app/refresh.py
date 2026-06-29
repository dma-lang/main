"""One-shot deploy self-refresh (§16) — migrate, then re-provision + re-carry the DATA plane.

Runs as the SAME one-shot Cloud Run Job as the migration (``cia-migrate``), right after
``alembic upgrade head`` and **before the new revision gets traffic** (never on app startup). A
deploy ships new code and/or new seeds, but the deployed ``cat_<v>`` catalogue and the carried Jira
delivery were built by the PREVIOUS run — so without this step the live app keeps serving stale
numbers after every deploy. This brings the data plane back in step with what was just shipped:

  * control plane -> ``app.migrate.run()`` (advisory-locked, at-head no-op; reused verbatim).
  * data plane    -> for every provisioned ``cat_<v>``: ``provision.bring_version_online`` (rebuild
                     the catalogue from the bundled seed, transactionally) then
                     ``stories.carry_forward`` (re-ingest the canonical corpus, re-run the
                     offerings matcher + embeddings).

Safe + bounded (safeguard 9). Each version's rebuild is ONE transaction — concurrent readers on the
old revision block briefly and then see the new data, never a half-built schema. A per-schema build
marker (stored as the schema's ``COMMENT``) makes a re-execution of the SAME build a no-op: a
retried job, or a deploy whose data was already refreshed, does no destructive work and spends
nothing on embeddings; only a genuinely new build re-provisions, and it does so exactly once. A
version whose own refresh fails is rolled back to its prior (intact) state and the job exits
non-zero, so the deploy script leaves traffic on the old revision rather than promoting onto a
broken data plane.

Knobs (env): ``REFRESH_BUILD_ID`` the deploy's image digest / git sha (the marker; empty disables
the skip — always refresh); ``REFRESH_FORCE=1`` ignore the marker and refresh regardless;
``REFRESH_BOOTSTRAP=v7,v5`` provision these versions when none is provisioned yet (default: none —
a brand-new database is still loaded once from Settings, per docs/DEPLOYMENT.md A10).

Invoke: ``python -m app.refresh`` (the deploy scripts point the migrate job's args here).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db, migrate
from app.services import provision
from app.services import stories as story_svc

logger = logging.getLogger("cia.refresh")

# cat_<version> components are lowercased ids; this guards the schema name we interpolate into DDL.
_VERSION_RE = re.compile(r"^[a-z0-9_]+$")
# The marker is operator-supplied (an image digest / git sha); keep only safe characters before it
# is inlined into COMMENT ... IS '<literal>' (DDL takes no bind parameter for the comment value).
_BUILD_SANITISE = re.compile(r"[^A-Za-z0-9:_.@/+-]")
_MARKER_PREFIX = "cia-build:"


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _build_id() -> str:
    return (os.environ.get("REFRESH_BUILD_ID") or "").strip()


def _bootstrap_versions() -> list[str]:
    raw = (os.environ.get("REFRESH_BOOTSTRAP") or "").strip()
    return [v.strip() for v in raw.split(",") if v.strip() and _VERSION_RE.match(v.strip())]


async def _provisioned_versions(conn: AsyncConnection) -> list[tuple[str, str]]:
    """Every committable version (provisioned or active) with its label — the data planes a deploy
    must bring back in step. An ``uploaded``/draft version is intentionally excluded."""
    rows = (
        await conn.execute(
            text(
                "SELECT version_id, coalesce(label, version_id) AS label "
                "FROM control.catalogue_version WHERE status IN ('provisioned', 'active') "
                "ORDER BY version_id"
            )
        )
    ).all()
    return [(str(r[0]), str(r[1])) for r in rows]


async def _read_marker(conn: AsyncConnection, schema: str) -> str | None:
    """The build id last written onto ``cat_<v>`` (its schema COMMENT), or None when the schema is
    absent / unmarked (a schema provisioned before this mechanism existed reads as unmarked → it
    refreshes once, which is exactly the staleness we are fixing)."""
    comment = (
        await conn.execute(
            text(
                "SELECT obj_description(n.oid, 'pg_namespace') FROM pg_namespace n "
                "WHERE n.nspname = :s"
            ),
            {"s": schema},
        )
    ).scalar()
    if comment and str(comment).startswith(_MARKER_PREFIX):
        return str(comment)[len(_MARKER_PREFIX) :]
    return None


async def _write_marker(conn: AsyncConnection, schema: str, build: str) -> None:
    safe = _BUILD_SANITISE.sub("", build)[:180]
    literal = (_MARKER_PREFIX + safe).replace("'", "''")
    await conn.execute(text(f"COMMENT ON SCHEMA {schema} IS '{literal}'"))


async def _refresh_version(version_id: str, label: str, build: str) -> dict[str, Any]:
    """Re-provision + re-carry one version, unless its build marker already matches ``build`` (and
    not forced). Writes the marker after a rebuild so the next same-build run is a no-op."""
    if not _VERSION_RE.match(version_id):
        logger.warning("skipping version with unexpected id %r", version_id)
        return {"version": version_id, "skipped": True, "reason": "invalid id"}
    engine = db.require_engine()
    schema = f"cat_{version_id}"

    if build and not _env_flag("REFRESH_FORCE"):
        async with engine.connect() as conn:
            marker = await _read_marker(conn, schema)
        if marker == build:
            logger.info("%s already at build %s — skipping (no rebuild, no spend)", schema, build)
            return {"version": version_id, "skipped": True, "reason": "marker"}

    logger.info("refreshing %s: re-provision (rebuild catalogue) + re-carry (corpus)", schema)
    prov = await provision.bring_version_online(version_id, label=label)
    carry = await story_svc.carry_forward(version_id)
    if build:
        async with engine.begin() as conn:
            await _write_marker(conn, schema, build)
    logger.info(
        "refreshed %s: %s subcaps, %s stories ingested (%s confirmed / %s review)",
        schema,
        prov.get("subcaps"),
        carry.get("stories_ingested"),
        carry.get("confirmed"),
        carry.get("review"),
    )
    return {"version": version_id, "skipped": False, "provision": prov, "carry": carry}


async def refresh_data_plane() -> int:
    """Re-provision + re-carry every provisioned version. Returns 0 on full success, 1 if any
    version failed (its data is rolled back to the prior state; the deploy then holds traffic)."""
    if db.init_engine() is None:
        logger.warning("DATABASE_URL not set; no data plane to refresh")
        return 0
    build = _build_id()
    rc = 0
    try:
        engine = db.require_engine()
        async with engine.connect() as conn:
            versions = await _provisioned_versions(conn)
        if not versions:
            boot = _bootstrap_versions()
            if not boot:
                logger.info(
                    "no provisioned versions — nothing to refresh "
                    "(load the catalogue once via Settings, or set REFRESH_BOOTSTRAP)"
                )
                return 0
            logger.info("no provisioned versions — bootstrapping %s", ", ".join(boot))
            versions = [(v, f"Catalogue {v}.0") for v in boot]
        logger.info(
            "data-plane refresh: %d version(s) [%s], build=%s",
            len(versions),
            ", ".join(v for v, _ in versions),
            build or "<none>",
        )
        for version_id, label in versions:
            try:
                await _refresh_version(version_id, label, build)
            except Exception:  # noqa: BLE001 - one version failing must not abort the others
                logger.exception("refresh FAILED for %s — existing data left intact", version_id)
                rc = 1
    finally:
        await db.dispose_engine()
    return rc


def run() -> int:
    """Migrate the control plane to head, then refresh every provisioned data plane. Exit 0 only
    when BOTH succeed, so a failed migration or refresh keeps traffic on the previous revision."""
    mig = migrate.run()
    if mig != 0:
        logger.error("migration returned %s; not refreshing the data plane", mig)
        return mig
    return asyncio.run(refresh_data_plane())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    raise SystemExit(run())
