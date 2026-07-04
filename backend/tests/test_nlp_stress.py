"""NLP stress suite — corpus-wide accuracy floors for the deterministic language engines.

Runs the R8 story-synthesis engine over the ENTIRE committed 14,406-row Jira corpus
(``seed/stories.json.gz``) and asserts the quality floors measured when the engine was hardened:
role-parse coverage, benefit extraction, acceptance/approach mining, zero placeholder leaks,
(near-)zero first-person and markup leaks, length bounds and determinism. Pure — no DB, no spend —
so a parsing regression can never land silently: the floor trips in CI on the REAL corpus, not on a
toy fixture. Also locks the new parse shapes unit-style (must/should/don't-want/can't/ability/
persona/interposed-clause/typos) and the matcher/rollup pure-NLP invariants.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

from app.services import story_synthesis as ss
from app.services.sv_rollups import _aggregate
from app.services.use_case_match import _tfidf, _tokens

_SEED = Path(__file__).resolve().parents[1] / "seed" / "stories.json.gz"

# a REAL pronoun use ("I <verb>", "my/we/our <word>") — "i.e." and names like "Phase I" excluded
_TRUE_FP = re.compile(r"\b(?:I\s+(?=[a-z])|my\s|we\s|our\s)", re.IGNORECASE)
_IE = re.compile(r"(?i)\bi\.?\s*e[.,]")
_BRACKET_LEAK = re.compile(r"\[[A-Z][A-Z_ ]+\]")
_MARKUP_LEAK = re.compile(r"h\d\.\s|\{code|\{noformat|\|\||<[a-z]+>|\*[^*\n]{2,40}\*")


def _corpus() -> list[dict[str, Any]]:
    with gzip.open(_SEED) as f:
        rows: list[dict[str, Any]] = json.load(f)
    assert len(rows) == 14406  # the canonical corpus — a silent seed change must be loud
    return rows


def test_corpus_accuracy_floors() -> None:
    """One pass over the full real corpus; every floor is the hardened engine's measured level
    with a small safety margin — a regression below any floor fails CI."""
    rows = _corpus()
    n_desc = n_act = n_sdt = 0
    role_ok = benefit_ok = acc_ok = app_ok = 0
    asa_total = asa_miss = 0
    fp = mk = br = length_viol = 0
    for r in rows:
        desc, act, sdt = r.get("desc") or "", r.get("act") or "", r.get("sdt") or ""
        syn = ss.synthesize(r.get("sum") or "", desc, act, sdt, r.get("tier"), r.get("sv"))
        assert syn.narrative, f"empty narrative for {r['k']}"
        if len(syn.narrative) > ss._NARRATIVE_CAP or any(
            len(p) > ss._POINT_CAP for p in (*syn.acceptance, *syn.approach)
        ):
            length_viol += 1
        if _BRACKET_LEAK.search(syn.narrative):
            br += 1
        if _MARKUP_LEAK.search(syn.narrative):
            mk += 1
        if _TRUE_FP.search(_IE.sub(" ", syn.narrative)):
            fp += 1
        if desc.strip():
            n_desc += 1
            role_ok += bool(syn.role)
            benefit_ok += bool(syn.benefit)
            if re.search(r"(?i)\bas\s+an?\b", desc):
                asa_total += 1
                asa_miss += not syn.role
        if act.strip():
            n_act += 1
            acc_ok += bool(syn.acceptance)
        if sdt.strip():
            n_sdt += 1
            app_ok += bool(syn.approach)

    assert length_viol == 0
    assert br == 0, f"{br} bracket-placeholder leaks"
    assert mk / len(rows) <= 0.005, f"markup leaks {mk}"
    assert fp / len(rows) <= 0.01, f"true first-person narratives {fp}"
    assert asa_miss / asa_total <= 0.05, f"role-parse miss on 'as a' descs {asa_miss}/{asa_total}"
    assert role_ok / n_desc >= 0.65, f"role extraction {role_ok}/{n_desc}"
    assert benefit_ok / n_desc >= 0.40, f"benefit extraction {benefit_ok}/{n_desc}"
    assert acc_ok / n_act >= 0.97, f"acceptance mining {acc_ok}/{n_act}"
    assert app_ok / n_sdt >= 0.96, f"approach mining {app_ok}/{n_sdt}"


def test_corpus_determinism_sample() -> None:
    rows = _corpus()[::97]  # ~150 evenly-spread stories
    for r in rows:
        args = (
            r.get("sum") or "",
            r.get("desc") or "",
            r.get("act") or "",
            r.get("sdt") or "",
            r.get("tier"),
            r.get("sv"),
        )
        assert ss.synthesize(*args) == ss.synthesize(*args)


def test_new_story_shapes_parse() -> None:
    """The corpus shapes the hardening added: no-comma, must/should, do-negation, can't,
    have-the-ability, am-able, interposed clause, missing subject, stretched typo, curly quotes."""
    cases = [
        (
            "As an agent I need lead information presented consistently",
            "agent",
            "lead information presented consistently",
        ),
        (
            "As an Abuzz Manager, I must be able to capture key metrics",
            "Abuzz Manager",
            "capture key metrics",
        ),
        (
            "As a user, I don't want the status to change, so that data stays clean",
            "user",
            "not the status to change",
        ),
        ("As a user, I can't delete tasks or files.", "user", "delete tasks or files"),
        (
            "As an agent, I have the ability to create tasks and events",
            "agent",
            "create tasks and events",
        ),
        (
            "As an Agent, if the policy is won, I must send it to the core system",
            "Agent",
            "send it to the core system",
        ),
        (
            "As a Commercial User would like to see all new loans",
            "Commercial User",
            "see all new loans",
        ),
        (
            "As a MC USer I neeed the logo displayed so I have continuity",
            "MC USer",
            "the logo displayed",
        ),
        ("As a user, I don’t want duplicates", "user", "not duplicates"),
    ]
    for desc, want_role, want_goal in cases:
        role, goal, _ = ss.parse_role_goal_benefit(desc)
        assert role == want_role, f"{desc!r}: role {role!r}"
        assert goal and want_goal in goal, f"{desc!r}: goal {goal!r}"


def test_persona_statement_and_negation_weave() -> None:
    p = ss.synthesize(
        "Einstein scoring",
        "As an agent, Einstein Lead Scoring is available to help me prioritize leads.",
        "",
        "",
        "T1",
        "IB",
    )
    assert p.role == "agent"
    assert "For an agent, Einstein Lead Scoring is available to help them" in p.narrative
    n = ss.synthesize(
        "No deletes",
        "As a user, I don't want records deleted, so that we keep history",
        "",
        "",
        "T1",
        "RB",
    )
    assert "A user doesn't want records deleted, so that they keep history" in n.narrative


def test_real_names_survive_and_templates_render() -> None:
    """[DAO]/[Case] are REAL names (kept verbatim, unbracketed); [OBJECT_NAME]/[CLIENT_ROLE] are
    templates (rendered readable); first-person summaries re-voice; a/an agreement repaired."""
    s = ss.synthesize(
        "Sync [DAO] to the [Case] object",
        "As an [CLIENT_ORG] user, I want [OBJECT_NAME] synced to [DAO]",
        "",
        "",
        "T1",
        "CL",
    )
    n = s.narrative
    assert "DAO" in n and "[DAO]" not in n
    assert "Case object" in n and "[Case]" not in n
    assert "the relevant object" in n and "[OBJECT_NAME]" not in n
    assert "a client organisation user" in n.lower() and "an client" not in n.lower()
    head = ss.synthesize("Track agents that we work with", "", "", "", "T1", "RB").narrative
    assert head.startswith("Track agents that they work with")


def test_markup_stripped_including_lost_newlines() -> None:
    s = ss.synthesize(
        "h2. Rollout *NEW*",
        "As a user, I want the flow live.* item one.* item two",
        "AC1: Given x, When y, Then the *Record-Triggered Flow* fires {code:java}x{code}",
        "- Configure *Page Layouts* per {color:red}spec{color}",
        "T1",
        "RB",
    )
    joined = " ".join((s.narrative, *s.acceptance, *s.approach))
    assert not _MARKUP_LEAK.search(joined), joined
    assert "Record-Triggered Flow" in joined and "Page Layouts" in joined


def test_matcher_tokens_drop_story_boilerplate() -> None:
    """The match doc now includes description + AC text; gherkin/user-story boilerplate must not
    become 'discriminating' terms that couple unrelated stories and use cases."""
    toks = _tokens(
        "Given the user, When they submit, Then I want to be able to see the triage dashboard"
    )
    for noise in ("given", "then", "want", "able", "ability", "user"):
        assert noise not in toks, f"boilerplate token {noise!r} survived"
    assert "triage" in toks and "dashboard" in toks
    # TF-IDF sanity: a term shared by ALL sibling docs carries no weight; discriminators do
    vecs, norms = _tfidf([_tokens("case triage dashboard"), _tokens("case escalation routing")])
    assert "case" not in vecs[0] and "triage" in vecs[0] and norms[0] > 0


def test_sv_rollup_aggregate_invariants() -> None:
    """Pure rollup NLP/aggregation: per-SV buckets + the all-SV canonical union, deduped, bounded
    narrative, deterministic rep ordering by composite."""
    rows = [
        {
            "entity": "SC1",
            "sv": "RB",
            "story_key": "A-1",
            "client_name": "Acme",
            "composite_score": 4.5,
            "narrative": "N1",
        },
        {
            "entity": "SC1",
            "sv": "RB",
            "story_key": "A-1",
            "client_name": "Acme",
            "composite_score": 4.5,
            "narrative": "N1",
        },  # duplicate row must dedup
        {
            "entity": "SC1",
            "sv": "CL",
            "story_key": "B-2",
            "client_name": "Bank",
            "composite_score": 3.0,
            "narrative": "N2",
        },
    ]
    out = _aggregate("v7", "subcap", rows)
    by_sv = {(o["entity_id"], o["subvertical"]): o for o in out}
    assert by_sv[("SC1", "RB")]["story_count"] == 1
    assert by_sv[("SC1", "")]["story_count"] == 2  # all-SV union, deduped
    assert by_sv[("SC1", "")]["client_count"] == 2
    assert json.loads(by_sv[("SC1", "")]["rep_story_keys"])[0] == "A-1"  # best composite first
    assert all(len(o["narrative"]) <= 900 for o in out)
