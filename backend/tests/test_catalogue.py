"""F4/F9: catalogue read endpoints over the seeded cat_v7. DB-backed, self-cleaning.

A module fixture provisions v7 once and drops it afterwards, so the suite stays order-independent.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db
from app.main import create_app
from app.services import provision

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
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS cat_v7 CASCADE"))
            await conn.execute(
                text(
                    "DELETE FROM control.ingest_run WHERE version_id = 'v7' "
                    "AND source = 'workbook_upload'"
                )
            )
            await conn.execute(
                text("DELETE FROM control.catalogue_version WHERE version_id = 'v7'")
            )
        await db.dispose_engine()

    asyncio.run(_setup())
    yield
    asyncio.run(_teardown())


@pytest.fixture
def client(provisioned: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@needs_db
def test_subcaps_tree(client: TestClient) -> None:
    r = client.get("/api/catalogue/v7/subcaps")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 851
    assert {"id", "name", "pillar", "cat_id", "cat_name", "cluster", "life"} <= set(body[0])


@needs_db
def test_heatmap_contract(client: TestClient) -> None:
    """Mission-control concentration heatmap: valid shape for every lens, a 6-band score axis, and
    every row's cells length 6. (Rows are empty until carry-forward seeds stories; the data path is
    exercised against the carried dev DB.) An unknown lens falls back to pillar."""
    for lens in ("pillar", "maturity", "subvertical", "vendor", "value-chain"):
        body = client.get(f"/api/catalogue/v7/heatmap?lens={lens}").json()
        assert body["lens"] == lens
        assert len(body["axis"]) == 6
        assert isinstance(body["rows"], list)
        for row in body["rows"]:
            assert len(row["cells"]) == 6
            assert row["total"] == sum(row["cells"]) or row["total"] >= max(row["cells"])
    # the lifecycle lens was removed; like any unknown lens it falls back to pillar
    assert client.get("/api/catalogue/v7/heatmap?lens=lifecycle").json()["lens"] == "pillar"
    assert client.get("/api/catalogue/v7/heatmap?lens=bogus").json()["lens"] == "pillar"


@needs_db
def test_subcap_timeline_contract(client: TestClient) -> None:
    """Project-subcap trace: a known subcap returns the timeline shape (events list with the trust
    envelope per event + a delivery story count); an unknown subcap 404s, never 500s."""
    sid = client.get("/api/catalogue/v7/subcaps").json()[0]["id"]
    body = client.get(f"/api/catalogue/v7/subcaps/{sid}/timeline").json()
    assert body["subcap_id"] == sid and body["name"]
    assert isinstance(body["events"], list) and isinstance(body["stories"], int)
    for ev in body["events"]:
        assert ev["kind"] in {"news", "vendor", "suggestion", "benchmark", "trend", "sow"}
        assert {"date", "title", "claim", "tier", "chain"} <= set(ev)
    assert client.get("/api/catalogue/v7/subcaps/NOPE.0.0/timeline").status_code == 404


@needs_db
def test_kg_layer_a_projection(client: TestClient) -> None:
    """Knowledge graph: a subcap with platforms projects a deterministic Layer-A neighbourhood —
    the centre node plus platform/offering/sibling edges, every edge a real link-table row. Unknown
    subcap 404s. Pending (Layer B) is a separate list, never mixed into the deterministic edges."""
    # find a subcap that actually has platforms so the projection is non-trivial
    sid = next(
        x["id"]
        for x in client.get("/api/catalogue/v7/subcaps").json()
        if client.get(f"/api/catalogue/v7/subcaps/{x['id']}").json()["n_platforms"] > 0
    )
    body = client.get(f"/api/catalogue/v7/kg?subcap={sid}").json()
    assert body["center"] == sid and body["name"]
    assert any(n["id"] == sid and n["kind"] == "subcap" for n in body["nodes"])
    assert body["stats"]["platforms"] > 0
    assert all(e["layer"] == "A_deterministic" for e in body["edges"])  # never proposed in Layer A
    assert all(e["layer"] == "B_proposed" for e in body["pending"])
    assert client.get("/api/catalogue/v7/kg?subcap=NOPE.0.0").status_code == 404


@needs_db
def test_whatif_cascade_preview(client: TestClient) -> None:
    """What-if: the read-only blast radius of a change to a subcap sums its offering / platform /
    story / use-case / sibling links; blast equals that sum and 404s on an unknown subcap."""
    sid = next(
        x["id"]
        for x in client.get("/api/catalogue/v7/subcaps").json()
        if client.get(f"/api/catalogue/v7/subcaps/{x['id']}").json()["n_platforms"] > 0
    )
    d = client.get(f"/api/catalogue/v7/whatif?subcap={sid}&action=retire").json()
    assert d["subcap"] == sid and d["action"] == "retire" and d["reversible"] is True
    assert (
        d["blast"]
        == len(d["offerings"])
        + len(d["platforms"])
        + len(d["siblings"])
        + d["stories"]
        + d["use_cases"]
    )
    assert d["platforms"] and "Retiring" in d["summary"]
    assert client.get("/api/catalogue/v7/whatif?subcap=NOPE.0.0").status_code == 404


@needs_db
def test_subcap_detail(client: TestClient) -> None:
    sid = client.get("/api/catalogue/v7/subcaps").json()[0]["id"]
    r = client.get(f"/api/catalogue/v7/subcaps/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == sid
    # Catalogue enrichment seeded by provisioning lights up the use-case / platform counts; the
    # story count stays 0 until carry-forward runs (also exercises the cross-schema
    # story_catalogue_link subquery, which must resolve to zero here).
    assert body["n_use_cases"] > 0
    assert body["n_platforms"] > 0
    assert body["n_stories"] == 0


@needs_db
def test_subcap_enrichment(client: TestClient) -> None:
    r = client.get("/api/catalogue/v7/subcaps/P1C1.1.1/enrichment")
    assert r.status_code == 200
    body = r.json()
    # Seeded from the comprehensive pillar workbooks.
    assert len(body["personas"]) > 0
    assert len(body["platforms"]) > 0
    assert len(body["use_cases"]) > 0
    assert [m["level"] for m in body["maturity"]] == ["M1", "M2", "M3", "M4", "M5"]
    assert {"l3_id", "name", "vendor"} <= set(body["platforms"][0])
    assert "offerings" in body  # productized offerings the subcap is mapped to (may be empty)


@needs_db
def test_subcap_connections(client: TestClient) -> None:
    r = client.get("/api/catalogue/v7/subcaps/P1C1.1.1/connections")
    assert r.status_code == 200
    sibs = r.json()["siblings"]
    assert len(sibs) > 0
    assert {"id", "name", "pillar", "shared_platforms"} <= set(sibs[0])
    assert all(s["id"] != "P1C1.1.1" for s in sibs)  # KG siblings exclude self


@needs_db
def test_value_chain_real_names_and_sv(client: TestClient) -> None:
    """A3 = the catalogue's REAL VC mapping (v7 sheet 21) as a per-subvertical ORDERED pipeline:
    actual stage NAMES (the VCC code is only an id), each with a 1..N position in chain order; FC
    is Farm Credit."""
    fc = client.get("/api/catalogue/v7/value-chain?sv=FC").json()
    assert fc["source"] == "catalogue_vc_mapping"
    assert fc["resolved_sv"] == "FC"
    assert len(fc["chains"]) == 1 and fc["chains"][0]["sv"] == "FC"  # one pinned chain
    assert len(fc["clusters"]) > 10  # backward-compat flat list = that chain's stages
    names = [c["name"] for c in fc["clusters"]]
    assert all(not n.startswith("VCC-") for n in names)  # names are names, never codes
    assert any("AG " in n or "FARM" in n.upper() or "FCA" in n for n in names)  # Farm Credit
    # stage labels are cleaned of "(SV-Specific: …)"-style noise (and merged on the clean name)
    assert all("SV-Specific" not in n and not n.endswith(")") for n in names)
    # the pipeline is ORDERED: positions ascend 1, 2, 3, …
    positions = [c["position"] for c in fc["clusters"]]
    assert positions == sorted(positions) and positions[0] == 1
    # a different subvertical has a different chain
    rb = client.get("/api/catalogue/v7/value-chain?sv=RB").json()
    assert rb["resolved_sv"] == "RB"
    assert [c["name"] for c in rb["clusters"]] != names
    # 'All SV' CONSOLIDATES the nine chains into ONE — the most-delivered subvertical's REAL named
    # stages, overlapping stages from the others folded in. No subvertical tag, every subcap there.
    # (The delivery-ranked canonical = RB and the user's P1C1.1.1 -> MARKET + BACK OFFICE example
    # are asserted in test_value_chain_inherit, where the corpus is carried forward.)
    allv = client.get("/api/catalogue/v7/value-chain").json()
    assert allv["sv"] == "all" and allv["resolved_sv"] == ""
    assert allv["source"] == "catalogue_vc_mapping"  # REAL stages, not a derived/L1 chain
    assert len(allv["chains"]) == 1 and allv["chains"][0]["sv"] == "all"
    assert allv["total_subcaps"] == 851  # every subcap consolidated, none dropped
    all_names = [c["name"] for c in allv["clusters"]]
    assert len(all_names) > 10 and all(not n.startswith("VCC-") for n in all_names)  # real names
    # every subcap is consolidated into at least one stage (none silently dropped)
    assert any(s["id"] == "P1C1.1.1" for c in allv["clusters"] for s in c["subcaps"])
    assert all("SV-Specific" not in n and not n.endswith(")") for n in all_names)
    assert not any(n.lower().startswith("indirect") and n != "Indirect linkages" for n in all_names)


@needs_db
def test_summary_changes_by_subvertical(client: TestClient) -> None:
    """The SV toggle must genuinely change the mission-control numbers: counts scope to the
    subcaps participating in that subvertical's value chain."""
    allv = client.get("/api/catalogue/v7/summary").json()
    fc = client.get("/api/catalogue/v7/summary?sv=FC").json()
    assert fc["total_subcaps"] < allv["total_subcaps"]
    assert sum(p["subcap_count"] for p in fc["pillars"]) == fc["total_subcaps"]
    # unknown SV scopes to zero rather than silently showing everything
    none = client.get("/api/catalogue/v7/summary?sv=ZZ").json()
    assert none["total_subcaps"] == 0
    # the workbench TREE must scope to the same SV membership, so its count matches the summary
    tree_all = client.get("/api/catalogue/v7/subcaps").json()
    tree_fc = client.get("/api/catalogue/v7/subcaps?sv=FC").json()
    assert len(tree_all) == allv["total_subcaps"]
    assert len(tree_fc) == fc["total_subcaps"]


@needs_db
def test_summary(client: TestClient) -> None:
    r = client.get("/api/catalogue/v7/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["total_subcaps"] == 851
    assert len(body["pillars"]) == 4
    # COMPLETENESS = (total subcaps - decayed subcaps) / total subcaps, exactly (user definition).
    for p in body["pillars"]:
        if p["subcap_count"]:
            expected = (p["subcap_count"] - p["decay"]) / p["subcap_count"]
            assert abs(p["completeness"] - expected) < 1e-6


@needs_db
def test_platforms_and_vendors(client: TestClient) -> None:
    plats = client.get("/api/catalogue/v7/platforms").json()
    assert len(plats) > 0
    top = plats[0]
    assert top["subcap_count"] > 0
    assert {"l3_id", "name", "vendor", "p1", "p2", "p3", "p4", "stories"} <= set(top)
    detail = client.get(f"/api/catalogue/v7/platforms/{top['l3_id']}").json()
    assert detail["l3_id"] == top["l3_id"]
    assert len(detail["subcaps"]) == top["subcap_count"]
    vendors = client.get("/api/catalogue/v7/vendors").json()
    assert len(vendors) > 0 and vendors[0]["subcap_count"] > 0


@needs_db
def test_use_cases(client: TestClient) -> None:
    r = client.get("/api/catalogue/v7/use-cases?size=5")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] > 0
    assert len(body["items"]) == 5
    assert len(body["archetypes"]) > 0
    it = body["items"][0]
    # the parse is complete: readable title + the use case's OWN maturity/new flag + L1 id, and the
    # delivery number is the story->use-case MATCH (not the subcap total), with subcap for context.
    assert {
        "use_case_id",
        "archetype",
        "name",
        "subcap_id",
        "pillar",
        "category",
        "category_id",
        "is_new",
        "n_stories",
        "subcap_stories",
    } <= set(it)
    assert it["n_stories"] <= it["subcap_stories"]  # matched <= the subcap's whole delivery
    # the L1-capability grouping facet (matched-story totals per category)
    assert body["categories"] and {"category_id", "category", "use_cases", "n_stories"} <= set(
        body["categories"][0]
    )
    # pillar filter narrows the set
    p4 = client.get("/api/catalogue/v7/use-cases?pillar=P4&size=1").json()
    assert 0 < p4["total"] < body["total"]
    assert all(left == "P4" for left in [i["pillar"] for i in p4["items"]])

    # the matched-stories drawer endpoint resolves to the StoryPage shape and reconciles with the
    # use case's count (this fixture provisions without carry, so the match set is 0 here; the
    # non-zero matched-delivery path is covered in test_use_case_match).
    uc_id = it["use_case_id"]
    st = client.get(f"/api/catalogue/v7/use-cases/{uc_id}/stories").json()
    assert {"total", "page", "size", "items"} <= set(st)
    assert st["total"] == it["n_stories"]


@needs_db
def test_unknown_version_404(client: TestClient) -> None:
    r = client.get("/api/catalogue/v999/subcaps")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


@needs_db
def test_applied_mapping_registry(client: TestClient) -> None:
    """Schema-mapping studio (F4): provisioning registers the mapping it ACTUALLY applied — every
    field row traces to a load statement, relations to the FKs/link tables it created. An
    unprovisioned version is a clear 404."""
    body = client.get("/api/admin/mapping/v7").json()
    assert len(body["fields"]) == 16 and len(body["relations"]) == 7
    f = {x["source_field"]: x for x in body["fields"]}
    assert f["subcaps.id"]["canonical_entity"] == "subcap"
    assert all(x["status"] == "confirmed" and x["confidence"] == 1.0 for x in body["fields"])
    rels = {(r["from_entity"], r["rel_type"], r["to_entity"]) for r in body["relations"]}
    assert ("subcap", "uses_platform", "l3_platform") in rels
    assert ("category", "belongs_to", "pillar") in rels
    assert client.get("/api/admin/mapping/v5").status_code == 404


def _mini_book(sheets: dict[str, list[list[Any]]]) -> bytes:
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    default = wb.active
    if default is not None:
        wb.remove(default)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@needs_db
def test_catalogue_zip_upload(client: TestClient) -> None:
    """FR-1: a pillar-wise ZIP of real .xlsx workbooks parses into the version's seed — subcaps
    counted, embedded synthetic stories extracted (labelled, never the analysis corpus), id
    collisions reconciled against the governing register or surfaced as human conflicts. Targets
    a scratch version so the committed v7/v5 seeds are never touched. Bad payloads are clean
    400s, never 500s."""
    import io
    import zipfile

    from app.services.provision import _SEED_DIR

    hdr = ["Sub-Cap ID", "Sub-Capability", "Description", "Tier", "Category ID", "Category Name"]
    story_hdr = ["Story_Key", "Source_Type", "Sub_Cap_ID", "Story_Summary", "Match_Confidence"]
    books = {
        "Pillar 1 Test.xlsx": _mini_book(
            {
                "Capability Map": [
                    hdr,
                    ["P1C9.1", "Test Vision", "", "Core", "P1C9", "Test Strategy"],
                    ["P1C9.2", "Test Operating Model", "", "Core", "P1C9", "Test Strategy"],
                ],
                # an embedded story tab: the jira row must be skipped, the rest are synthetic
                "3_User_Stories_Catalogue": [
                    story_hdr,
                    ["TESTJIRA-1", "jira_completed", "P1C9.1", "real — not re-ingested", "HIGH"],
                    ["GEN-TEST-1", "gen_stories_v1", "P1C9.1", "made up", "MEDIUM"],
                    ["PUB-TEST-1", "use_case_derived_public_validated", "P1C9.2", "derived", ""],
                ],
            }
        ),
        # an id collision the v7 register CAN place: 'AI Claims Estimation' is governed as
        # P2C3.2.IC2 (the real v5 case) — reconciled, never re-minted
        "Pillar 2 Test.xlsx": _mini_book(
            {
                "Capability Map": [
                    hdr,
                    ["P2C9.1", "Test Journeys", "", "Core", "P2C9", "Test Experience"],
                    ["P2C9.1", "AI Claims Estimation", "", "Core", "P2C9", "Test Experience"],
                ]
            }
        ),
        # an id collision nothing can place: a human conflict, kept out of the seed
        "Pillar 3 Test.xlsx": _mini_book(
            {
                "Capability Map": [
                    hdr,
                    ["P3C9.1", "Test Automation", "", "Core", "P3C9", "Test Ops"],
                    ["P3C9.1", "Zz Unplaceable Test Subcap", "", "Core", "P3C9", "Test Ops"],
                ]
            }
        ),
        "Pillar 4 Test.xlsx": _mini_book(
            {
                "Capability Map": [
                    hdr,
                    ["P4C9.1", "Test Data Foundation", "", "Core", "P4C9", "Test Data"],
                ]
            }
        ),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n, b in books.items():
            zf.writestr(f"Version 9/{n}", b)
        zf.writestr("Version 9/notes.txt", b"ignored")

    scratch = "v9scratch"
    cat_seed = _SEED_DIR / f"catalogue_{scratch}.json.gz"
    syn_seed = _SEED_DIR / f"stories_synthetic_{scratch}.json.gz"
    try:
        out = client.post(
            f"/api/admin/catalogue/upload/{scratch}",
            files={"file": ("Version_9.zip", buf.getvalue(), "application/zip")},
        ).json()
        assert out["recorded"] is True and len(out["workbooks"]) == 4
        assert out["pillars_recognised"] == ["P1", "P2", "P3", "P4"]
        # 2 (P1) + 2 (P2: collider reconciled, both kept) + 1 (P3: collider conflicted) + 1 (P4)
        assert out["subcaps_parsed"] == 6
        assert out["synthetic_stories_found"] == 2  # the jira_completed row is never re-ingested
        assert out["id_reconciliations"] == [
            {
                "source_id": "P2C9.1",
                "assigned_id": "P2C3.2.IC2",
                "name": "AI Claims Estimation",
                "via": "register",
            }
        ]
        assert [c["source_id"] for c in out["id_conflicts"]] == ["P3C9.1"]
        # the detected schema is in the manifest, so the onboarding review step has real content
        assert len(out["workbooks_detail"]) == 4
        p1 = next(d for d in out["workbooks_detail"] if d["file"] == "Pillar 1 Test.xlsx")
        assert p1["subcaps_parsed"] == 2
        assert {c["source"]: c["field"] for c in p1["columns"]}["Sub-Cap ID"] == "id"
        assert cat_seed.exists() and syn_seed.exists()  # the upload IS the version's source
    finally:
        cat_seed.unlink(missing_ok=True)
        syn_seed.unlink(missing_ok=True)

    bad = client.post(
        f"/api/admin/catalogue/upload/{scratch}",
        files={"file": ("x.zip", b"not a zip", "application/zip")},
    )
    assert bad.status_code == 400
    # a zip whose pillar workbook is not a real .xlsx is a clean, named 400 — never a 500
    fake = io.BytesIO()
    with zipfile.ZipFile(fake, "w") as zf:
        zf.writestr("Pillar 1 Broken.xlsx", b"x")
    broken = client.post(
        f"/api/admin/catalogue/upload/{scratch}",
        files={"file": ("broken.zip", fake.getvalue(), "application/zip")},
    )
    assert broken.status_code == 400
    assert "not a readable" in broken.json()["error"]["message"]
    assert not cat_seed.exists()  # a failed parse never writes a seed
    wrong = client.post(
        f"/api/admin/catalogue/upload/{scratch}",
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert wrong.status_code == 400
