"""R8 deterministic story synthesis — cohesive, grounded narratives from the raw Jira text.

Every real Jira story carries four rhetorical fields; this engine mines them into structured facets
and a cohesive paragraph, DETERMINISTICALLY (zero spend, fully grounded, invents nothing):

  * ``description``          -> the user-story WHY: role / goal / benefit (the "As a X…" shape).
  * ``ac_text``              -> WHAT it must do: the acceptance outcomes (the ``Then`` clauses).
  * ``solution_design_text`` -> HOW it was delivered: the solution approach (the config steps).
  * ``summary``              -> the headline.

The raw text is templated with ``[CLIENT_ROLE]`` (rendered in the story's own subvertical language,
config/subvertical_roles.yaml) and technical ``[OBJECT_NAME]``/``[FIELD_NAME]``/… placeholders (kept
readable, never leaked raw). Output is length-bounded and trust-labelled FACT (it only re-expresses
the story's own words). The live-Gemini deep-synthesis upgrade (``Gemini.synthesize_story``) reuses
THIS engine as its hermetic stub, so hermetic == deterministic exactly.

``synthesize_all(version)`` is the best-effort ``carry_forward`` step: an idempotent gap-fill
(``WHERE narrative IS NULL``) over the real corpus, chunked, so it runs once per corpus load.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text

from app import db
from app.services.sv_aliases import normalize_sv_code

_MAX_ACCEPT = 8  # acceptance points kept per story
_MAX_APPROACH = 6  # solution-approach steps kept per story
_POINT_CAP = 200  # per-point char cap
_NARRATIVE_CAP = 700  # narrative char cap

# action verbs that mark a real solution-design STEP (vs boilerplate) — used to rank SD sentences.
_ACTION = (
    "configure",
    "create",
    "add",
    "build",
    "implement",
    "integrate",
    "automate",
    "deploy",
    "enable",
    "update",
    "set",
    "define",
    "map",
    "generate",
    "trigger",
    "orchestrate",
    "validate",
    "deactivate",
    "calculate",
    "assign",
    "route",
)
_BRACKET_RE = re.compile(r"\[([A-Z][A-Z_ ]+)\]")
_ROLE_RE = re.compile(
    r"(?is)\bas\s+an?\s+(?P<role>.+?)\s*[,\n]\s*i\s+(?:want|need|would\s+like|wish|expect)\s+"
    r"(?:to\s+)?(?P<goal>.+?)(?:\s+so\s+that\s+(?P<benefit>.+?))?(?:[.\n]|$)"
)
_AC_SPLIT = re.compile(r"(?im)^\s*(?:AC\s*\d+|criteria\s*\d+|scenario\s*\d+)\s*[:.\)-]\s*")
_THEN_RE = re.compile(r"(?is)\bthen\b\s*(?P<then>.+)$")
_SENT_SPLIT = re.compile(r"(?<=[.;])\s+|\n+")

_cfg_cache: dict[str, Any] | None = None


def _config() -> dict[str, Any]:
    global _cfg_cache
    if _cfg_cache is None:
        here = Path(__file__).resolve()
        path = next(
            (
                p / "config" / "subvertical_roles.yaml"
                for p in here.parents
                if (p / "config").exists()
            ),
            None,
        )
        _cfg_cache = (yaml.safe_load(path.read_text()) if path and path.exists() else {}) or {}
    return _cfg_cache


@dataclass(frozen=True)
class StorySynthesis:
    """A story's synthesized narrative + the facets behind it (all grounded in its own text)."""

    narrative: str
    role: str | None
    goal: str | None
    benefit: str | None
    acceptance: tuple[str, ...]
    approach: tuple[str, ...]

    def facets(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "goal": self.goal,
            "benefit": self.benefit,
            "acceptance": list(self.acceptance),
            "approach": list(self.approach),
        }


def _role_phrase(sv_code: str | None) -> str:
    cfg = _config()
    roles = cfg.get("roles") or {}
    code = (normalize_sv_code(sv_code) or "").upper()
    return str(roles.get(code) or cfg.get("default") or "a financial-services stakeholder")


def _substitute(raw: str, sv_code: str | None) -> str:
    """Replace [CLIENT_ROLE] with the subvertical role and the technical [X_NAME] placeholders with
    readable generics, so no bracketed token ever leaks into a narrative."""
    if not raw or "[" not in raw:
        return raw
    role = _role_phrase(sv_code)
    ph = (
        (_config().get("placeholders") or {})
        if isinstance(_config().get("placeholders"), dict)
        else {}
    )

    def repl(m: re.Match[str]) -> str:
        token = m.group(1).strip().replace(" ", "_").upper()
        if token == "CLIENT_ROLE":
            return role
        if token in ph:
            return str(ph[token])
        if token.endswith("_NAME"):
            return "the " + token[:-5].replace("_", " ").lower()
        return token.replace("_", " ").lower()

    return _BRACKET_RE.sub(repl, raw)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" .;-\t,")


def _third_person(s: str) -> str:
    """Re-voice a first-person benefit clause ('I don't ...' -> 'they don't ...') so it reads in the
    narrative's third person."""
    repl = {"i": "they", "my": "their", "we": "they", "our": "their", "us": "them", "me": "them"}
    return re.sub(r"(?i)\b(i|my|we|our|us|me)\b", lambda m: repl[m.group(1).lower()], s)


def _dedup(points: list[str], cap: int) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for p in points:
        p = _clean(p)[:_POINT_CAP]
        key = re.sub(r"[^a-z0-9 ]", "", p.lower())
        if len(p) < 6 or key in seen:
            continue
        seen.add(key)
        out.append(p)
        if len(out) >= cap:
            break
    return tuple(out)


def parse_role_goal_benefit(desc: str) -> tuple[str | None, str | None, str | None]:
    """Parse a user-story description into (role, goal, benefit); falls back to the first sentence
    as the goal when the 'As a … I want …' shape is absent."""
    if not desc:
        return None, None, None
    m = _ROLE_RE.search(desc)
    if m:
        return (
            _clean(m.group("role")) or None,
            _clean(m.group("goal")) or None,
            _clean(m.group("benefit") or "") or None,
        )
    first = _SENT_SPLIT.split(desc.strip(), maxsplit=1)[0]
    return None, _clean(first)[:_POINT_CAP] or None, None


def parse_acceptance(ac_text: str) -> tuple[str, ...]:
    """The acceptance OUTCOMES: split on AC1:/AC2:/scenario markers, else sentences; keep each AC's
    'Then …' outcome where present (that is the delivered behaviour), else the whole point."""
    if not ac_text:
        return ()
    chunks = _AC_SPLIT.split(ac_text)
    if len(chunks) <= 1:
        chunks = _SENT_SPLIT.split(ac_text)
    points: list[str] = []
    for c in chunks:
        c = c.strip()
        if not c:
            continue
        then = _THEN_RE.search(c)
        points.append(then.group("then") if then else c)
    return _dedup(points, _MAX_ACCEPT)


def parse_solution(sd_text: str) -> tuple[str, ...]:
    """The solution APPROACH: the config/build steps. Split on bullets/newlines/sentences, prefer
    lines that start with an action verb, drop URL-only references; empty/'TBD' -> no approach."""
    if not sd_text or _clean(sd_text).lower() in ("tbd", "n a", "na", "none", "to be defined"):
        return ()
    raw_lines = re.split(r"\n+|(?<=[.;])\s+", sd_text)
    action: list[str] = []
    other: list[str] = []
    for ln in raw_lines:
        ln = _clean(re.sub(r"https?://\S+", "", ln))
        if len(ln) < 6:
            continue
        first = ln.split(" ", 1)[0].lower().rstrip(":")
        (action if first in _ACTION else other).append(ln)
    return _dedup(action + other, _MAX_APPROACH)


def synthesize(
    summary: str,
    description: str,
    ac_text: str,
    solution_design_text: str,
    tier: str | None,
    sv_code: str | None,
) -> StorySynthesis:
    """Deterministically synthesize a story's facets + a cohesive narrative from its raw text."""
    desc = _substitute(description or "", sv_code)
    role, goal, benefit = parse_role_goal_benefit(desc)
    acceptance = parse_acceptance(_substitute(ac_text or "", sv_code))
    approach = parse_solution(_substitute(solution_design_text or "", sv_code))
    head = _clean(summary or "") or "This delivery"

    # weave a cohesive paragraph (omit any absent facet gracefully; never a bare concatenation)
    parts = [head.rstrip(".") + "."]
    if goal:
        who = role or _role_phrase(sv_code)
        benefit_clause = f", so that {_third_person(benefit)}" if benefit else ""
        parts.append(f"For {who}, this addresses {goal}{benefit_clause}.")
    if acceptance:
        parts.append("It is accepted when " + _join_lower(acceptance[:2]) + ".")
    if approach:
        parts.append("The approach: " + _join_lower(approach[:2]) + ".")
    narrative = _clean(" ".join(parts))[:_NARRATIVE_CAP]
    return StorySynthesis(narrative, role, goal, benefit, acceptance, approach)


def _join_lower(points: tuple[str, ...]) -> str:
    lowered = [p[0].lower() + p[1:] if p else p for p in points]
    if len(lowered) <= 1:
        return "".join(lowered)
    return ", and ".join(lowered)


def _chunks(seq: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


async def synthesize_all(version_id: str) -> dict[str, int]:
    """Idempotent gap-fill: synthesize a narrative + facets for every real story that lacks one, in
    chunks. Corpus-wide (narratives are per-story, version-independent), so it runs once — a second
    version's carry finds the narratives already set and does nothing. Best-effort + hermetic-safe.
    """
    engine = db.require_engine()
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT story_key, coalesce(summary, '') AS s, "
                        "coalesce(description, '') AS d, coalesce(ac_text, '') AS a, "
                        "coalesce(solution_design_text, '') AS sd, tier, story_sv_code "
                        "FROM control.story WHERE NOT is_synthetic AND narrative IS NULL"
                    )
                )
            )
            .mappings()
            .all()
        )
    updates = [
        {
            "k": r["story_key"],
            "n": res.narrative,
            "f": json.dumps(res.facets()),
        }
        for r in rows
        for res in (synthesize(r["s"], r["d"], r["a"], r["sd"], r["tier"], r["story_sv_code"]),)
    ]
    for chunk in _chunks(updates, 1000):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE control.story SET narrative = :n, facets = CAST(:f AS jsonb) "
                    "WHERE story_key = :k"
                ),
                chunk,
            )
    return {"synthesized": len(updates)}
