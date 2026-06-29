"""Productized-offering -> subcap semantic matcher (F6 deep-learning matching).

Grounds the GTM "Productized Offerings" catalogue (``backend/seed/offerings.json``: 7 activation
offerings + 21 data products, each with named Core Capabilities) into the four-pillar subcap
catalogue BY MEANING. Each offering's named capabilities are matched to the catalogue via HYBRID
retrieval (dense embedding cosine + lexical ts_rank, reranked by a combined score), the strongest
subcaps per offering are kept above a config gate floor and bounded, and the result REPLACES the
deterministic offering seed with doc-grounded, scored matches in ``cat_<v>.offering`` +
``offering_subcap``.

Trust-first: every match carries its score + the matching capability in ``mapping_rationale`` (the
basis a reviewer / the deep dive shows). Hermetic-safe — the dense half uses deterministic
token-hash embeddings (no spend), so the matcher is fully testable; live uses the one Gemini wrapper
(metered). Idempotent: re-running rebuilds the offering tables cleanly.
"""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app import db
from app.intelligence import gates, retrieval
from app.versioning import resolve_version

logger = logging.getLogger(__name__)

_SEED = Path(__file__).resolve().parents[2] / "seed" / "offerings.json"


@functools.lru_cache(maxsize=1)
def load_offerings() -> list[dict[str, Any]]:
    """The productized offerings (activation + data products) parsed from the GTM doc. Bundled with
    the app, cached for the process."""
    with _SEED.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return list(data.get("offerings", []))


async def match_offerings(version: str = "v7") -> dict[str, Any]:
    """Rebuild ``cat_<v>.offering`` + ``offering_subcap`` from the offerings doc via semantic
    matching. Each offering's name+summary and every named capability is hybrid-retrieved over the
    version's catalogue; the strongest subcaps above the gate floor are kept (bounded per offering),
    scored, and persisted. Returns a summary
    ``{version, offerings, matched_pairs, covered_subcaps, avg_subcaps}``."""
    offerings = load_offerings()
    v = await resolve_version(version)
    schema = f"cat_{v.version_id}"
    floor, top_k, max_per = gates.offerings_match_config()
    # F6: the version's subcap embeddings power the DENSE half; best-effort (hermetic = stub, no
    # spend). A failure degrades to lexical-only — the matcher still runs, just on word overlap.
    try:
        from app.services import embeddings as _emb

        await _emb.build_embeddings(v.version_id)
    except Exception as exc:  # noqa: BLE001 - degrade to lexical-only, never block the matcher
        logger.warning("offerings matcher: embeddings unavailable, lexical-only: %s", exc)

    engine = db.require_engine()
    matched_pairs = 0
    covered: set[str] = set()
    async with engine.begin() as conn:
        ids = {
            r[0] for r in (await conn.execute(text(f"SELECT subcap_id FROM {schema}.subcap"))).all()
        }
        # rebuild cleanly: the doc-grounded semantic matches REPLACE any prior (deterministic) seed
        await conn.execute(text(f"DELETE FROM {schema}.offering_subcap"))
        await conn.execute(text(f"DELETE FROM {schema}.offering"))
        for off in offerings:
            await conn.execute(
                text(
                    f"INSERT INTO {schema}.offering "
                    "(offering_id, name, category, status, description) "
                    "VALUES (:id, :name, :cat, 'active', :desc)"
                ),
                {
                    "id": off["id"],
                    "name": off["name"],
                    "cat": off.get("category") or off.get("family", ""),
                    "desc": (off.get("summary") or "")[:1000],
                },
            )
            # per-capability hybrid match; keep the STRONGEST score per subcap across the offering's
            # name + summary + every named capability (so a subcap matched by several capabilities
            # keeps its best evidence, and "extensive" coverage spans the whole offering).
            best: dict[str, tuple[float, str]] = {}
            queries: list[str] = [f"{off['name']} {off.get('summary', '')}"]
            queries += [str(c) for c in off.get("capabilities", [])]
            for q in queries:
                q = q.strip()
                if not q:
                    continue
                for m in await retrieval.retrieve(conn, schema, q, k=top_k, use_dense=True):
                    sid = str(m["subcap_id"])
                    score = float(m["score"])
                    if sid not in ids or score < floor:
                        continue
                    if sid not in best or score > best[sid][0]:
                        best[sid] = (score, q[:90])
            top = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)[:max_per]
            for sid, (score, cap) in top:
                await conn.execute(
                    text(
                        f"INSERT INTO {schema}.offering_subcap "
                        "(offering_id, subcap_id, mapping_rationale, maturity_lift, status) "
                        "VALUES (:o, :s, :r, :m, 'matched')"
                    ),
                    {
                        "o": off["id"],
                        "s": sid,
                        "r": f"semantic match · score {score:.3f} · capability: {cap}",
                        "m": f"{score:.3f}",
                    },
                )
                matched_pairs += 1
                covered.add(sid)
    n = len(offerings)
    return {
        "version": v.version_id,
        "offerings": n,
        "matched_pairs": matched_pairs,
        "covered_subcaps": len(covered),
        "avg_subcaps": round(matched_pairs / n, 1) if n else 0.0,
    }
