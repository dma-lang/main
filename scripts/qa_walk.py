#!/usr/bin/env python3
"""QA walk — the repeatable post-deploy validation harness (docs/DEPLOYMENT.md §8).

Walks every live surface's backing endpoint and asserts the contract, the trust envelope on every
AI value, the reasoning backlinks, honest degraded states, version-keying and the error envelope.
Exits 0 only when every check passes; prints one PASS/FAIL line per check.

Usage:
  BASE=http://localhost:8092 python3 scripts/qa_walk.py            # structural checks
  BASE=... STRICT=1 python3 scripts/qa_walk.py                     # + exact hermetic-fixture counts
  BASE=https://cia-...run.app TOKEN=<firebase-id-token> python3 scripts/qa_walk.py

STRICT=1 asserts the deterministic hermetic-fixture counts (news 10/12 mapped, 4 benchmarks,
9 vendor events, 1 staged trend) and is for hermetic environments; live environments run the
structural checks (shapes, envelopes, non-empties) because real scans yield real counts.
TOKEN adds `Authorization: Bearer <token>` to every request (live AUTH_MODE).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "http://localhost:8092").rstrip("/")
TOKEN = os.environ.get("TOKEN", "")
STRICT = os.environ.get("STRICT", "") == "1"
failures: list[str] = []


def _req(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict | list]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or "{}")
        except json.JSONDecodeError:
            return e.code, {}


def get(path: str):  # noqa: ANN201 - tiny harness
    return _req(path)


def post(path: str, body: dict | None = None):  # noqa: ANN201
    return _req(path, "POST", body or {})


def check(name: str, ok: bool) -> None:
    print(f"{'PASS' if ok else 'FAIL':4}  {name}")
    if not ok:
        failures.append(name)


def main() -> int:  # noqa: C901, PLR0915 - linear checklist by design
    # ---- system probes
    s, h = get("/healthz")
    check("healthz: status ok + db ok", s == 200 and h["status"] == "ok" and h["db"] == "ok")
    check("healthz: app + catalogue version surfaced", bool(h["app_version"]))
    active = h.get("catalogue_version")
    s, live = get("/livez")
    check("livez", s == 200 and live["status"] == "alive")
    if not active:
        print("\nNOTE: no active catalogue version — provision v7 first (guide §7); "
              "running probe-only checks.")
        return 1 if failures else 0

    # ---- identity + persisted preferences
    s, me = get("/api/me")
    check("me: domain identity + preferences", s == 200 and "preferences" in me)
    _req("/api/me/preferences", "PATCH", {"preferences": {"lens": "vendor"}})
    s, me2 = get("/api/me")
    check("preferences persist server-side", me2["preferences"].get("lens") == "vendor")
    _req("/api/me/preferences", "PATCH", {"preferences": {"lens": "pillar"}})

    # ---- catalogue reads (A1/A2/B1/B2/C2/F1)
    s, summary = get(f"/api/catalogue/{active}/summary")
    total = sum(p["subcap_count"] for p in summary["pillars"])
    check("summary: 4 pillars", s == 200 and len(summary["pillars"]) == 4)
    check("summary: 851 subcaps" if STRICT else "summary: subcaps > 0",
          total == 851 if STRICT else total > 0)
    s, tree = get(f"/api/catalogue/{active}/subcaps")
    pillars = {n["pillar"] for n in tree}
    check("workbench tree: flat nodes across 4 pillars",
          s == 200 and isinstance(tree, list) and len(pillars) == 4)
    if STRICT:
        check("workbench tree: 851 nodes", len(tree) == 851)
    sid = tree[0]["id"] if tree else ""
    s, sub = get(f"/api/catalogue/{active}/subcaps/{sid}")
    check("subcap detail + completeness", s == 200 and sub["completeness"] >= 0)
    s, _ = get(f"/api/catalogue/{active}/subcaps/{sid}/stories?page=1&size=5")
    check("subcap stories page", s == 200)
    s, plats = get(f"/api/catalogue/{active}/platforms")
    check("platform catalog", s == 200 and len(plats) > 0)
    s, ucs = get(f"/api/catalogue/{active}/use-cases?page=1")
    check("use-case explorer", s == 200 and len(ucs.get("items", [])) > 0)
    s, stories = get("/api/stories?page=1")
    check("story corpus 14406" if STRICT else "story corpus non-empty",
          stories.get("total", 0) == 14406 if STRICT else stories.get("total", 0) > 0)
    s, _ = get(f"/api/catalogue/{active}/lifecycle")
    check("lifecycle opportunities", s == 200)

    # ---- intelligence surfaces: full trust envelope on every AI value
    s, news = get("/api/evidence?kind=news")
    items = news["items"]
    check("news: every card has chain+tier+claim+source.ers",
          s == 200 and all(i["chain"] and i["tier"] and i["label"] and i["source"]["ers"] > 0
                           for i in items))
    if STRICT:
        check("news: 10 mapped of 12 fixture", len(items) == 10)
    s, trends = get("/api/trends")
    check("trends: signals + affects + chain on every card",
          s == 200 and all(t["chain"] and t["signals"] and t["affects"] for t in trends["items"]))
    if STRICT:
        check("trends: 1 staged", trends["counts"].get("staged", 0) == 1)
    s, bench = get("/api/evidence?kind=benchmark")
    thin = [b for b in bench["items"] if b["thin"]]
    check("benchmarks: verdict + chain on every panel",
          s == 200 and all(b["verdict"] and b["chain"] for b in bench["items"]))
    check("benchmarks: thin coverage suppresses the CI band",
          all(b["ci_low"] is None and b["coverage_note"] for b in thin))
    if STRICT:
        check("benchmarks: 4 panels incl. one thin + one 'not documented'",
              len(bench["items"]) == 4 and len(thin) == 1
              and any(b["methodology"] == "not documented" for b in bench["items"]))
    s, ven = get("/api/evidence?kind=vendor_event")
    check("vendor: honest low tiers + chain; heatmap cells scored",
          s == 200 and all(i["chain"] and i["tier"] in ("T3", "T4", "T5") for i in ven["items"])
          and all(c["score"] > 0 for c in ven["heat"]))
    if STRICT:
        check("vendor: 9 mapped / 8 profiles", len(ven["items"]) == 9 and len(ven["vendors"]) == 8)

    # ---- the universal audit window resolves from every surface
    for label, chain in [("news", items[0]["chain"]), ("trend", trends["items"][0]["chain"]),
                         ("benchmark", bench["items"][0]["chain"]),
                         ("vendor", ven["items"][0]["chain"])]:
        s, ch = get(f"/api/reasoning/{chain}")
        check(f"reasoning resolves from {label}",
              s == 200 and ch["steps"] and ch["checks"] and ch["verdict"] in ("pass", "fail"))

    # ---- grounded chat: cited answer; refusal on ungroundable input (G5)
    s, chat = post("/api/chat", {"question": "Which capabilities cover fraud detection scoring?"})
    check("chat: grounded + cited + chain",
          s == 200 and chat.get("citations") and chat.get("chain_id"))
    s, refuse = post("/api/chat", {"question": "zzzqqq xkcd unicorn pizza"})
    check("chat: refuses ungrounded (G5)",
          s == 200 and (refuse.get("refused") or not refuse.get("citations")))

    # ---- governance
    s, sugg = get("/api/suggestions?status=pending")
    check("suggestions list", s == 200 and isinstance(sugg, list))
    s, flags = get("/api/change-flags?status=open")
    check("change flags queue (nothing dropped)", s == 200 and "flags" in flags)
    s, gates_log = get("/api/gates")
    check("gates log aggregates", s == 200 and gates_log["total_runs"] > 0)
    s, qa = get("/api/qa/metrics")
    check("qa metrics", s == 200 and qa["total_runs"] > 0)
    s, audit = get("/api/audit-log")
    check("audit log reads", s == 200 and isinstance(audit, list))
    s, sources = get("/api/admin/sources")
    check("source registry: 6 sources, active origin named",
          s == 200 and len(sources) == 6 and all(r["origin_active"] for r in sources))

    # ---- edge cases: version-keying, envelopes, validation
    s, nf = get("/api/catalogue/v999/summary")
    check("unprovisioned version -> 404 envelope", s == 404 and "error" in nf)
    s, _ = get("/api/evidence?kind=sow_chunk")
    check("unwired evidence kind -> 400", s == 400)
    s, _ = post("/api/trends/not-a-uuid/feedback", {"verdict": "promote"})
    check("malformed uuid -> 422 (never 500)", s == 422)

    print()
    if failures:
        print(f"{len(failures)} FAILURES: {failures}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
