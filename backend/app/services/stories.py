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
_SYN_GLOB = "stories_synthetic_*.json.gz"  # one per catalogue version that embeds story tabs

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


def _load_synthetic() -> list[dict[str, Any]]:
    """Every catalogue version's workbook-embedded SYNTHETIC stories (GEN-*/PUB-*, parsed by
    services/workbooks; the v7 seed is committed, others land on upload). Each row is stamped
    with the version it came from. Distinct from the real Jira corpus by is_synthetic=true +
    source_system; no files => none."""
    out: list[dict[str, Any]] = []
    for path in sorted((_BACKEND / "seed").glob(_SYN_GLOB)):
        version = path.name[len("stories_synthetic_") : -len(".json.gz")]
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            rows: list[dict[str, Any]] = json.load(fh)
        for r in rows:
            r.setdefault("source_version", version)
        out.extend(rows)
    return out


_INGEST_SYN = text(
    "INSERT INTO control.story "
    "(story_key, sub_cap_id, sub_cap_name, summary, ac_text, solution_design_text, "
    "confidence_level, source_system, source_version, is_synthetic) VALUES "
    "(:story_key, :sub_cap_id, :sub_cap_name, :summary, :ac_text, :solution_design_text, "
    "CAST(:confidence_level AS confidence_level), :source_system, :source_version, true) "
    "ON CONFLICT (story_key) DO UPDATE SET "
    "sub_cap_id = EXCLUDED.sub_cap_id, summary = EXCLUDED.summary, "
    "source_system = EXCLUDED.source_system, is_synthetic = true"
)


_INGEST = text(
    "INSERT INTO control.story "
    "(story_key, project_key, epic_key, sub_cap_id, cap_id, pillar_id, category_id, category_name, "
    "cap_name, sub_cap_name, tier, story_sv_code, project_sv_code, reusability_layer, population, "
    "summary, ac_quality, sd_quality, delivery_score, composite_score, confidence_level, "
    "ac_score, sd_score, story_score, delivered_at, source_version, is_synthetic) VALUES "
    "(:story_key, :project_key, :epic_key, :sub_cap_id, :cap_id, :pillar_id, :category_id, "
    ":category_name, :cap_name, :sub_cap_name, :tier, :story_sv_code, :project_sv_code, "
    ":reusability_layer, :population, :summary, :ac_quality, :sd_quality, :delivery_score, "
    ":composite_score, CAST(:confidence_level AS confidence_level), "
    ":ac_score, :sd_score, :story_score, :delivered_at, "
    ":source_version, false) "
    "ON CONFLICT (story_key) DO UPDATE SET "
    "sub_cap_id = EXCLUDED.sub_cap_id, summary = EXCLUDED.summary, "
    "composite_score = EXCLUDED.composite_score, ac_score = EXCLUDED.ac_score, "
    "sd_score = EXCLUDED.sd_score, story_score = EXCLUDED.story_score, "
    "confidence_level = EXCLUDED.confidence_level, source_version = EXCLUDED.source_version, "
    "delivered_at = EXCLUDED.delivered_at, ingested_at = now()"
)

# One story may evidence SEVERAL subcaps (corpus mapping + the catalogue's own story refs), so the
# key is (story_key, target_version, carried_to_subcap) — migration 0012. carry_forward RECONSTRUCTS
# a version's rows inside its transaction (delete -> insert), so re-carries stay idempotent and a
# remapped story never leaves a stale link behind; DO NOTHING guards in-batch duplicates.
_CARRY = text(
    "INSERT INTO control.story_subcap_carry "
    "(story_key, source_version, mapped_in_source, base_subcap, subvertical, target_version, "
    "carried_to_subcap, similarity, status, via) VALUES "
    "(:story_key, :source_version, :mapped_in_source, :base_subcap, :subvertical, :target_version, "
    ":carried_to_subcap, :similarity, CAST(:status AS carry_status), :via) "
    "ON CONFLICT (story_key, target_version, carried_to_subcap) DO NOTHING"
)


def _parse_date(raw: Any) -> Any:
    """Best-effort parse of an export delivery date (ISO 8601) to a datetime; None when absent or
    unparseable. The canonical corpus has no date, so this is None today; present so a future dated
    export can populate control.story.delivered_at (we never invent a date)."""
    if not raw:
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00").strip())
    except ValueError:
        return None


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
        "delivered_at": _parse_date(
            s.get("dt")
            or s.get("rd")
            or s.get("resolved")
            or s.get("delivered")
            or s.get("created")
        ),
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


def _syn_ingest_row(r: dict[str, Any]) -> dict[str, Any]:
    conf = str(r.get("confidence_level") or "").upper()
    return {
        "story_key": r["story_key"],
        "sub_cap_id": r.get("sub_cap_id"),
        "sub_cap_name": r.get("sub_cap_name"),
        "summary": r.get("summary"),
        "ac_text": r.get("ac_text"),
        "solution_design_text": r.get("solution_design_text"),
        "confidence_level": conf if conf in ("HIGH", "MEDIUM", "LOW") else None,
        "source_system": r.get("source_type") or "synthetic",
        "source_version": r.get("source_version") or "v7",
    }


_NN_CAP = 2000  # bound the per-run NN work (§15 bounded-everything); the rest stays unmapped


async def _nearest_neighbour_pass(
    conn: Any, schema: str, stories: list[dict[str, Any]], carries: list[dict[str, Any]]
) -> None:
    """Banded lexical nearest-neighbour for carries the id rules could not place: retrieve over
    the TARGET version's own catalogue with the story's subcap/cluster names, map the rank onto
    the configured matching bands (>= confirm auto-confirms, the middle band routes to review,
    sub-floor stays unmapped) — same scale the SOW matcher uses, recalibrated together (R4)."""
    from app.intelligence import gates, retrieval
    from app.services.sow import _similarity

    floor, strong = gates.evidence_thresholds()
    confirm_at, review_low = gates.matching_bands()
    misses = [i for i, c in enumerate(carries) if c["status"] == "unmapped"]
    for i in misses[:_NN_CAP]:
        srow = stories[i]
        query = " ".join(
            str(srow.get(k) or "") for k in ("scn", "capn", "cat") if srow.get(k)
        ).strip()
        if not query:
            continue
        matches = await retrieval.retrieve(conn, schema, query, k=1)
        if not matches:
            continue
        rank = float(matches[0]["rank"])
        if rank < floor:
            continue  # noise — never mapped (G5)
        sim = _similarity(rank, floor, strong)
        if sim >= confirm_at:
            status = "confirmed"
        elif sim >= review_low:
            status = "review"
        else:
            continue
        carries[i].update(
            carried_to_subcap=str(matches[0]["subcap_id"]),
            similarity=sim,
            status=status,
            via="nearest_neighbour",
        )


async def carry_forward(
    target_version: str = "v7", source_version: str | None = None
) -> dict[str, Any]:
    """Ingest the canonical corpus and carry it onto ``target_version`` (native when the corpus is
    mapped against it). Returns a summary of the carry outcome. Runs in one transaction."""
    src = source_version or target_version
    if set(target_version) - set("abcdefghijklmnopqrstuvwxyz0123456789_"):
        raise ValueError(f"invalid target_version: {target_version!r}")
    engine = db.require_engine()
    schema = f"cat_{target_version}"
    stories = _load_seed()

    synthetic = _load_synthetic()
    async with engine.begin() as conn:
        # RECONSTRUCT this version's carries (idempotent re-carry; no stale links survive a remap)
        await conn.execute(
            text("DELETE FROM control.story_subcap_carry WHERE target_version = :tv"),
            {"tv": target_version},
        )
        ids = {
            r[0] for r in (await conn.execute(text(f"SELECT subcap_id FROM {schema}.subcap"))).all()
        }
        await conn.execute(_INGEST, [_ingest_row(s, src) for s in stories])
        carries = [_carry_row(s, ids, src, target_version) for s in stories]
        # Robust subcap matching: native -> base-id; the residue gets a banded nearest-neighbour
        # over the TARGET catalogue (config matching bands; review unless strongly grounded) so a
        # renamed/restructured version (e.g. v5) still lands carries instead of dropping them.
        await _nearest_neighbour_pass(conn, schema, stories, carries)
        await conn.execute(_CARRY, carries)
        if synthetic:
            await conn.execute(_INGEST_SYN, [_syn_ingest_row(r) for r in synthetic])
            syn_carries = [
                _carry_row(
                    {"k": r["story_key"], "sc": r.get("sub_cap_id") or ""},
                    ids,
                    str(r.get("source_version") or "v7"),
                    target_version,
                )
                for r in synthetic
            ]
            await conn.execute(_CARRY, syn_carries)
        # CATALOGUE-REF pass: the catalogue's own per-subcap Jira story references (the v7
        # Capability Map's Story_Refs_with_UC_Links / the seed's embedded story keys) become real
        # links wherever the key resolves to a stored, non-synthetic corpus story — the catalogue
        # authors' mapping, T1, citation-verified (G7 style: only resolvable refs link; the
        # unresolved are counted, never invented).
        ref_stats = await _catalogue_ref_pass(conn, schema, target_version)
        # A drifted version (e.g. v5: ids renamed vs v7) shares enrichment with v7 by capability
        # NAME, not id — so the id-only corpus carry above leaves its delivery (and the mission-
        # control heatmap) empty even though the deep-dive details inherit. Carry the v7 corpus
        # mapping onto the resolved subcaps (the SAME rule enrichment uses), via='inherited_v7'.
        inherit_stats = await _corpus_inherit_pass(conn, schema, target_version)

    confirmed = sum(1 for c in carries if c["status"] == "confirmed")
    unmapped = sum(1 for c in carries if c["status"] == "unmapped")
    distinct = len({c["carried_to_subcap"] for c in carries if c["carried_to_subcap"]})
    return {
        "target_version": target_version,
        "stories_ingested": len(stories),
        "synthetic_ingested": len(synthetic),
        "review": sum(1 for c in carries if c["status"] == "review"),
        "confirmed": confirmed,
        "unmapped": unmapped,
        "distinct_subcaps": distinct,
        **ref_stats,
        **inherit_stats,
    }


async def _catalogue_ref_pass(conn: Any, schema: str, target_version: str) -> dict[str, int]:
    """Link cat_<v>.subcap.story_refs against the ingested corpus. Returns honest stats: how many
    additional (story, subcap) links landed, how many refs could not be resolved to a stored
    story, and the resulting count of distinct Jira-linked subcaps."""
    rows = (
        await conn.execute(
            text(
                f"SELECT subcap_id, story_refs FROM {schema}.subcap "
                "WHERE jsonb_array_length(story_refs) > 0"
            )
        )
    ).all()
    if not rows:
        # a version with no refs of its own (e.g. v5) borrows the reference catalogue's refs,
        # resolving each subcap through the ONE canonical rule the enrichment paths share
        # (services/subcap_xref) — so the borrowed refs land on the same subcaps the enrichment did
        from app.services import subcap_xref
        from app.services.enrichment_seed import reference_subcap_index, story_refs_map

        ref_map = story_refs_map()
        ref_ver, ref_index = reference_subcap_index()
        cur = [
            dict(r)
            for r in (
                await conn.execute(
                    text(
                        f"SELECT s.subcap_id AS id, cap.name AS l2, s.description AS descr "
                        f"FROM {schema}.subcap s "
                        f"JOIN {schema}.capability cap ON cap.capability_id = s.capability_id"
                    )
                )
            ).mappings()
        ]
        crosswalk = {
            str(a): str(b)
            for a, b in await conn.execute(
                text(
                    "SELECT from_subcap, to_subcap FROM control.version_crosswalk "
                    "WHERE from_version = :v AND to_version = :r AND to_subcap IS NOT NULL"
                ),
                {"v": target_version, "r": ref_ver},
            )
        }
        mapping, _unmapped = subcap_xref.resolve_map(cur, ref_index, crosswalk)
        rows = [(sid, ref_map[ref_id]) for sid, ref_id in mapping.items() if ref_id in ref_map]
    real = {
        str(r[0]): str(r[1] or "")
        for r in await conn.execute(
            text("SELECT story_key, sub_cap_id FROM control.story WHERE NOT is_synthetic")
        )
    }
    links: list[dict[str, Any]] = []
    unresolved = 0
    for subcap_id, refs in ((str(r[0]), r[1] or []) for r in rows):
        for key in refs:
            k = str(key)
            if k not in real:
                unresolved += 1
                continue
            base, sv = normalize_id(subcap_id)
            links.append(
                {
                    "story_key": k,
                    "source_version": target_version,
                    "mapped_in_source": real[k] or subcap_id,
                    "base_subcap": base,
                    "subvertical": sv,
                    "target_version": target_version,
                    "carried_to_subcap": subcap_id,
                    "similarity": 1.0,
                    "status": "confirmed",
                    "via": "catalogue_ref",
                }
            )
    if links:
        await conn.execute(_CARRY, links)
    # report what actually LANDED: refs that duplicate the corpus' own (story, subcap) row
    # conflict away (DO NOTHING), so the inserted count is the honest "additional links" figure
    inserted = (
        await conn.execute(
            text(
                "SELECT count(*) FROM control.story_subcap_carry "
                "WHERE target_version = :tv AND via = 'catalogue_ref'"
            ),
            {"tv": target_version},
        )
    ).scalar() or 0
    n_linked = (
        await conn.execute(
            text(
                "SELECT count(DISTINCT carried_to_subcap) FROM control.story_subcap_carry c "
                "JOIN control.story s ON s.story_key = c.story_key "
                "WHERE c.target_version = :tv AND c.carried_to_subcap IS NOT NULL "
                "AND c.status IN ('confirmed', 'review') AND NOT s.is_synthetic"
            ),
            {"tv": target_version},
        )
    ).scalar() or 0
    return {
        "catalogue_ref_links": int(inserted),
        "catalogue_refs_resolved_pairs": len(links),
        "catalogue_refs_unresolved": unresolved,
        "jira_linked_subcaps": int(n_linked),
    }


def _invert_to_reference(
    target_subcaps: list[dict[str, Any]],
    ref_index: Any,
    crosswalk: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Inverse of the target->reference subcap map: ``{reference_subcap_id -> [target ids]}``.

    The corpus is mapped against the reference catalogue (v7). A version whose ids drifted (mapped
    to v7 by capability name, not id) has each of its subcaps resolved to its v7 counterpart through
    the ONE canonical rule (services/subcap_xref), then inverted — so a corpus story on a v7 subcap
    can be carried onto the drifted version's matching subcap(s). Pure (unit-tested without a DB).
    """
    from app.services import subcap_xref

    mapping, _unmapped = subcap_xref.resolve_map(target_subcaps, ref_index, crosswalk)
    inv: dict[str, list[str]] = {}
    for tgt_id, ref_id in mapping.items():
        inv.setdefault(ref_id, []).append(tgt_id)
    for ids in inv.values():
        ids.sort()
    return inv


async def _corpus_inherit_pass(conn: Any, schema: str, target_version: str) -> dict[str, int]:
    """Carry the canonical Jira corpus onto a DRIFTED version by inheritance from the reference.

    carry_forward's id rules (native exact/base id, then lexical NN) only place a corpus story on a
    target subcap that SHARES the v7 id. A version whose ids drifted (e.g. v5 — same capabilities,
    renamed ids) therefore inherits v7's enrichment (via subcap_xref) but NO delivery, leaving the
    Mission-control heatmap empty. This pass closes that gap: it resolves each target subcap to its
    v7 counterpart (the SAME rule enrichment uses), inverts the map, and carries every corpus story
    from its v7 subcap onto the target's matching subcap(s), recorded honestly as via='inherited_v7'
    (confirmed, so it feeds the analysis view, but distinguishable from native delivery). Additive
    and idempotent: ON CONFLICT DO NOTHING never disturbs a native carry. The reference version
    itself inherits nothing (it IS the corpus map)."""
    from app.services.enrichment_seed import reference_subcap_index

    ref_ver, ref_index = reference_subcap_index()
    if not ref_ver or target_version == ref_ver:
        return {"inherited_v7_links": 0, "inherited_v7_subcaps": 0}
    cur = [
        dict(r)
        for r in (
            await conn.execute(
                text(
                    f"SELECT s.subcap_id AS id, cap.name AS l2, s.description AS descr "
                    f"FROM {schema}.subcap s "
                    f"JOIN {schema}.capability cap ON cap.capability_id = s.capability_id"
                )
            )
        ).mappings()
    ]
    crosswalk = {
        str(a): str(b)
        for a, b in await conn.execute(
            text(
                "SELECT from_subcap, to_subcap FROM control.version_crosswalk "
                "WHERE from_version = :v AND to_version = :r AND to_subcap IS NOT NULL"
            ),
            {"v": target_version, "r": ref_ver},
        )
    }
    inv = _invert_to_reference(cur, ref_index, crosswalk)
    if not inv:
        return {"inherited_v7_links": 0, "inherited_v7_subcaps": 0}
    corpus = (
        await conn.execute(
            text(
                "SELECT story_key, sub_cap_id FROM control.story "
                "WHERE NOT is_synthetic AND sub_cap_id IS NOT NULL"
            )
        )
    ).all()
    links: list[dict[str, Any]] = []
    touched: set[str] = set()
    for story_key, sc in corpus:
        raw = str(sc).strip()
        base, _sv = normalize_id(raw)
        targets = inv.get(raw) or inv.get(base)  # the v7 id may be subvertical-suffixed
        if not targets:
            continue
        for tgt in targets:
            tbase, tsv = normalize_id(tgt)
            links.append(
                {
                    "story_key": str(story_key),
                    "source_version": ref_ver,
                    "mapped_in_source": raw,
                    "base_subcap": tbase,
                    "subvertical": tsv,
                    "target_version": target_version,
                    "carried_to_subcap": tgt,
                    "similarity": 1.0,
                    "status": "confirmed",
                    "via": "inherited_v7",
                }
            )
            touched.add(tgt)
    if links:
        await conn.execute(_CARRY, links)
    inserted = (
        await conn.execute(
            text(
                "SELECT count(*) FROM control.story_subcap_carry "
                "WHERE target_version = :tv AND via = 'inherited_v7'"
            ),
            {"tv": target_version},
        )
    ).scalar() or 0
    return {"inherited_v7_links": int(inserted), "inherited_v7_subcaps": len(touched)}
