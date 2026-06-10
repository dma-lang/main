"""F5 — canonical story corpus ingest + carry-forward.

Loads the canonical Jira Full Story Catalog (14,406 real stories) into ``control.story`` and carries
the story->subcap mappings onto a provisioned catalogue version (``control.story_subcap_carry``),
adopting the algorithm from ``docs/specs/carry_forward_subcap_mappings.py``:

* ``normalize_id`` splits a subvertical-suffixed id (``P3C1.8.CL2`` -> base ``P3C1.8`` + ``CL2``);
* the raw id is tried first (v7 contains subvertical-specific subcaps such as ``P3C1.8.RIA2``), then
  the base id; a hit on either is a **native** confirmed link (similarity 1.0) because the corpus is
  mapped against the same version it is carried onto;
* a miss is written as an ``unmapped`` carry row — nothing is dropped (plan Part F / D10).

Idempotent: ``story`` upserts on ``story_key``; ``story_subcap_carry`` upserts on
``(story_key, target_version)``. Re-running re-provisions cleanly and never double-writes.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app import db

_BACKEND = Path(__file__).resolve().parents[2]  # app/services/stories.py -> backend
_SEED = _BACKEND / "seed" / "stories.json.gz"

# Same id grammar as the carry-forward spec: base id + optional 2-letter subvertical suffix.
_ID_RE = re.compile(r"^(?P<base>P\d+C\d+(?:\.\d+)*?)(?:\.(?P<sv>[A-Z]{2}\d*))?$")


def normalize_id(sub_cap_id: str) -> tuple[str, str | None]:
    """Split a possibly subvertical-suffixed id, e.g. 'P3C1.8.CL2' -> ('P3C1.8', 'CL2')."""
    m = _ID_RE.match(sub_cap_id.strip())
    if not m:
        return sub_cap_id.strip(), None
    return m.group("base"), m.group("sv")


def _load_seed() -> list[dict[str, Any]]:
    with gzip.open(_SEED, "rt", encoding="utf-8") as fh:
        data: list[dict[str, Any]] = json.load(fh)
    return data


_INGEST = text(
    "INSERT INTO control.story "
    "(story_key, project_key, epic_key, sub_cap_id, cap_id, pillar_id, category_id, category_name, "
    "cap_name, sub_cap_name, tier, story_sv_code, project_sv_code, reusability_layer, population, "
    "summary, ac_quality, sd_quality, delivery_score, composite_score, confidence_level, "
    "ac_score, sd_score, story_score, source_version, is_synthetic) VALUES "
    "(:story_key, :project_key, :epic_key, :sub_cap_id, :cap_id, :pillar_id, :category_id, "
    ":category_name, :cap_name, :sub_cap_name, :tier, :story_sv_code, :project_sv_code, "
    ":reusability_layer, :population, :summary, :ac_quality, :sd_quality, :delivery_score, "
    ":composite_score, CAST(:confidence_level AS confidence_level), "
    ":ac_score, :sd_score, :story_score, "
    ":source_version, false) "
    "ON CONFLICT (story_key) DO UPDATE SET "
    "sub_cap_id = EXCLUDED.sub_cap_id, summary = EXCLUDED.summary, "
    "composite_score = EXCLUDED.composite_score, ac_score = EXCLUDED.ac_score, "
    "sd_score = EXCLUDED.sd_score, story_score = EXCLUDED.story_score, "
    "confidence_level = EXCLUDED.confidence_level, source_version = EXCLUDED.source_version, "
    "ingested_at = now()"
)

_CARRY = text(
    "INSERT INTO control.story_subcap_carry "
    "(story_key, source_version, mapped_in_source, base_subcap, subvertical, target_version, "
    "carried_to_subcap, similarity, status, via) VALUES "
    "(:story_key, :source_version, :mapped_in_source, :base_subcap, :subvertical, :target_version, "
    ":carried_to_subcap, :similarity, CAST(:status AS carry_status), :via) "
    "ON CONFLICT (story_key, target_version) DO UPDATE SET "
    "carried_to_subcap = EXCLUDED.carried_to_subcap, similarity = EXCLUDED.similarity, "
    "status = EXCLUDED.status, via = EXCLUDED.via, mapped_in_source = EXCLUDED.mapped_in_source, "
    "base_subcap = EXCLUDED.base_subcap, subvertical = EXCLUDED.subvertical"
)


def _ingest_row(s: dict[str, Any], source_version: str) -> dict[str, Any]:
    return {
        "story_key": s["k"],
        "project_key": s.get("pk"),
        "epic_key": s.get("ek"),
        "sub_cap_id": s["sc"],
        "cap_id": s.get("capid"),
        "pillar_id": s.get("p"),
        "category_id": s.get("catid"),
        "category_name": s.get("cat"),
        "cap_name": s.get("capn"),
        "sub_cap_name": s.get("scn"),
        "tier": s.get("tier"),
        "story_sv_code": s.get("sv"),
        "project_sv_code": s.get("psv"),
        "reusability_layer": s.get("rl"),
        "population": s.get("pop"),
        "summary": s.get("sum"),
        "ac_quality": s.get("acq"),
        "sd_quality": s.get("sdq"),
        "delivery_score": s.get("dlv"),
        "composite_score": s.get("cs"),
        "confidence_level": s.get("conf"),
        "ac_score": s.get("ac"),
        "sd_score": s.get("sd"),
        "story_score": s.get("ss"),
        "source_version": source_version,
    }


def _carry_row(
    s: dict[str, Any], ids: set[str], source_version: str, target_version: str
) -> dict[str, Any]:
    raw = str(s["sc"]).strip()
    base, sv = normalize_id(raw)
    if raw in ids:
        target, status, via, sim = raw, "confirmed", "native", 1.0
    elif base in ids:
        target, status, via, sim = base, "confirmed", "native", 1.0
    else:
        target, status, via, sim = None, "unmapped", "none", None
    return {
        "story_key": s["k"],
        "source_version": source_version,
        "mapped_in_source": raw,
        "base_subcap": base,
        "subvertical": sv or s.get("sv"),
        "target_version": target_version,
        "carried_to_subcap": target,
        "similarity": sim,
        "status": status,
        "via": via,
    }


async def carry_forward(
    target_version: str = "v7", source_version: str | None = None
) -> dict[str, Any]:
    """Ingest the canonical corpus and carry it onto ``target_version`` (native when the corpus is
    mapped against it). Returns a summary of the carry outcome. Runs in one transaction."""
    src = source_version or target_version
    if set(target_version) - set("abcdefghijklmnopqrstuvwxyz0123456789_"):
        raise ValueError(f"invalid target_version: {target_version!r}")
    engine = db.get_engine()
    if engine is None:
        raise RuntimeError("database not initialised")
    schema = f"cat_{target_version}"
    stories = _load_seed()

    async with engine.begin() as conn:
        ids = {
            r[0] for r in (await conn.execute(text(f"SELECT subcap_id FROM {schema}.subcap"))).all()
        }
        await conn.execute(_INGEST, [_ingest_row(s, src) for s in stories])
        carries = [_carry_row(s, ids, src, target_version) for s in stories]
        await conn.execute(_CARRY, carries)

    confirmed = sum(1 for c in carries if c["status"] == "confirmed")
    unmapped = sum(1 for c in carries if c["status"] == "unmapped")
    distinct = len({c["carried_to_subcap"] for c in carries if c["carried_to_subcap"]})
    return {
        "target_version": target_version,
        "stories_ingested": len(stories),
        "confirmed": confirmed,
        "unmapped": unmapped,
        "distinct_subcaps": distinct,
    }
