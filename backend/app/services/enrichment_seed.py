"""Cross-version enrichment fallback (read-time): serve a subcap's platforms / use cases /
maturity / personas / offerings from the GOVERNING version's reference seed when the version the
user is looking at has none of its own.

Why this exists: a version provisioned from a base-only workbook (e.g. an uploaded catalogue —
the upload path parses the subcaps but not the enrichment) leaves every deep dive empty. Rather
than force a re-provision, we map the subcap to the reference catalogue (the highest version that
ships an enrichment seed, i.e. v7) BY SUBCAP ID — the same identity the diff/crosswalk uses — and
return that enrichment, clearly tagged as inherited. The seed is bundled with the app, so this
always works regardless of what is provisioned. Deterministic, hermetic-safe, cached.
"""

from __future__ import annotations

import functools
import gzip
import json
from pathlib import Path
from typing import Any

_SEED_DIR = Path(__file__).resolve().parents[2] / "seed"


@functools.lru_cache(maxsize=1)
def _reference() -> tuple[str, dict[str, dict[str, list[dict[str, Any]]]]]:
    """The governing enrichment seed (highest version with a catalogue_<v>_enrichment.json.gz),
    indexed by subcap id into the API-ready shapes. Built once, cached for the process."""
    best: tuple[int, str] | None = None
    for f in _SEED_DIR.glob("catalogue_*_enrichment.json.gz"):
        vid = f.stem.replace(".json", "").split("_")[1]  # catalogue_<vid>_enrichment
        num = int("".join(ch for ch in vid if ch.isdigit()) or 0)
        if best is None or num > best[0]:
            best = (num, vid)
    if best is None:
        return "", {}
    ref_ver = best[1]
    path = _SEED_DIR / f"catalogue_{ref_ver}_enrichment.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        e: dict[str, list[dict[str, Any]]] = json.load(fh)

    vendors = {v["vendor_id"]: v.get("name") for v in e.get("vendors", [])}
    l3 = {p["l3_id"]: p for p in e.get("l3_platforms", [])}
    personas = {p["persona_id"]: p for p in e.get("personas", [])}
    offerings = {o["offering_id"]: o for o in e.get("offerings", [])}

    idx: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def bucket(sid: str) -> dict[str, list[dict[str, Any]]]:
        return idx.setdefault(
            sid,
            {"platforms": [], "use_cases": [], "maturity": [], "personas": [], "offerings": []},
        )

    for sp in e.get("subcap_platforms", []):
        p = l3.get(sp["l3_id"])
        if p:
            bucket(sp["subcap_id"])["platforms"].append(
                {
                    "l3_id": p["l3_id"],
                    "name": p.get("name"),
                    "vendor": vendors.get(p.get("vendor_id")),
                    "category": p.get("category"),
                }
            )
    for uc in e.get("use_cases", []):
        bucket(uc["subcap_id"])["use_cases"].append(
            {
                "use_case_id": uc["use_case_id"],
                "archetype": uc.get("archetype"),
                "name": uc.get("name"),
                "description": uc.get("description"),
            }
        )
    for md in e.get("maturity_descriptors", []):
        bucket(md["subcap_id"])["maturity"].append(
            {
                "level": md.get("level"),
                "descriptor": md.get("descriptor"),
                "features": md.get("features"),
            }
        )
    for sp in e.get("subcap_personas", []):
        pe = personas.get(sp["persona_id"])
        if pe:
            bucket(sp["subcap_id"])["personas"].append(
                {
                    "persona_id": pe["persona_id"],
                    "canonical_name": pe.get("canonical_name"),
                    "role_description": pe.get("role_description"),
                }
            )
    for os_ in e.get("offering_subcaps", []):
        o = offerings.get(os_["offering_id"])
        if o:
            bucket(os_["subcap_id"])["offerings"].append(
                {
                    "offering_id": o["offering_id"],
                    "name": o.get("name"),
                    "category": o.get("category"),
                }
            )
    return ref_ver, idx


def reference_version() -> str:
    """The version id whose seed backs the fallback (for the 'inherited from' trust tag)."""
    return _reference()[0]


def enrichment_for(subcap_id: str) -> dict[str, list[dict[str, Any]]]:
    """The reference enrichment for a subcap id (exact match), or empty buckets if the reference
    has nothing for it. Sorted for stable output."""
    _ref, idx = _reference()
    got = idx.get(subcap_id)
    if not got:
        return {"platforms": [], "use_cases": [], "maturity": [], "personas": [], "offerings": []}
    return {
        "platforms": sorted(got["platforms"], key=lambda r: str(r.get("name") or "")),
        "use_cases": sorted(got["use_cases"], key=lambda r: str(r.get("use_case_id") or "")),
        "maturity": sorted(got["maturity"], key=lambda r: str(r.get("level") or "")),
        "personas": sorted(got["personas"], key=lambda r: str(r.get("canonical_name") or "")),
        "offerings": sorted(got["offerings"], key=lambda r: str(r.get("name") or "")),
    }


def counts_for(subcap_id: str) -> dict[str, int]:
    e = enrichment_for(subcap_id)
    return {k: len(v) for k, v in e.items()}
