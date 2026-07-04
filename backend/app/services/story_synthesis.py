"""R8 deterministic story synthesis — cohesive, grounded narratives from the raw Jira text.

Every real Jira story carries four rhetorical fields; this engine mines them into structured facets
and a cohesive paragraph, DETERMINISTICALLY (zero spend, fully grounded, invents nothing):

  * ``description``          -> the user-story WHY: role / goal / benefit (the "As a X…" shape).
  * ``ac_text``              -> WHAT it must do: the acceptance outcomes (the ``Then`` clauses).
  * ``solution_design_text`` -> HOW it was delivered: the solution approach (the config steps).
  * ``summary``              -> the headline.

The raw text is Jira-wiki/HTML markup-stripped, then bracket tokens are resolved: ``[CLIENT_ROLE]``
renders in the story's own subvertical language (config/subvertical_roles.yaml), multi-word ALL-CAPS
templates (``[OBJECT_NAME]``, ``[INSERT SPECIFIC ENDPOINT]``) become readable generics, and REAL
bracketed names (``[DAO]``, ``[Case]``, ``[i2c_SYSTEM_API]``) are kept verbatim, unbracketed — a
placeholder never leaks and a system name is never mangled. The narrative is woven third-person and
GRAMMATICAL for the full corpus shape range ("I want", "I don't want", "I must be able to", no-comma
variants, …); the stress suite (tests/test_nlp_stress.py) asserts the corpus-wide accuracy floors.
Output is length-bounded and trust-labelled FACT (it only re-expresses the story's own words). The
live-Gemini deep-synthesis upgrade (``Gemini.synthesize_story``) reuses THIS engine as its hermetic
stub, so hermetic == deterministic exactly.

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

# Jira-wiki / light-HTML markup, stripped BEFORE any parsing so neither the facets nor the
# narrative ever carry ``h2.`` headings, ``{code}`` fences, ``*bold*`` stars or table pipes.
# Order matters: mentions/links resolve before the table-pipe pass eats their ``|``.
_MARKUP_RES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?im)^h[1-6]\.\s*"), ""),  # h2. headings
    (re.compile(r"\{(?:code|noformat|quote|panel|color)[^}\n]*\}"), " "),  # {code:java} fences
    (re.compile(r"\[~[^\]\n]+\]"), " "),  # [~user] mentions
    (re.compile(r"\[([^\]|\n]{1,80})\|[^\]\n]+\]"), r"\1"),  # [text|url] links -> text
    (re.compile(r"(?m)^\s*[*#-]+\s+"), ""),  # bullet markers
    (re.compile(r"\*([^*\n]{1,80})\*"), r"\1"),  # *bold* -> bold
    (re.compile(r"(?<=[.;:!?])\s*\*+\s+"), " "),  # bullet glued after a sentence (lost newline)
    (re.compile(r"\s\*+\s"), " "),  # stray unpaired star
    (re.compile(r"(?i)(?<=[.;:])\s*h[1-6]\.\s+"), " "),  # heading glued mid-line (lost newline)
    (re.compile(r"</?[A-Za-z][^>\n]{0,40}>"), " "),  # html/xml tags
    (re.compile(r"\|+"), " "),  # table pipes
    (re.compile(r"&(?:nbsp|amp|quot|#\d+);"), " "),
)

# TEMPLATE placeholders are multi-word ALL-CAPS ([CLIENT_ROLE], [OBJECT_NAME], [INSERT SPECIFIC
# ENDPOINT]); a single ALL-CAPS token ([DAO], [SFMCI]) is a real acronym and is kept verbatim.
_PLACEHOLDER_RE = re.compile(r"\[([A-Z][A-Z0-9_&%/=> -]{1,50})\]")
_LEFTOVER_BRACKET_RE = re.compile(r"\[([^\[\]\n]{1,60})\]")

# The user-story shape, tolerant to the real corpus: optional/doubled articles (the raw template
# yields "As a a commercial lending officer" after role substitution), optional comma, the full
# modal range (want/need/must/should/would like/wish/expect/require + do-negation + "no longer"),
# and the ability boilerplate ("to be able to", "the ability to") folded out of the goal.
_STORY_RE = re.compile(
    r"(?is)\bas\s+(?:(?:an?|the)\s+)*(?P<role>[^,\n]{2,110}?)\s*,?\s*"
    r"(?:(?:if|when|whenever|once|after|before)\s[^,\n]{2,60},\s*)?"  # ", if the policy is won, I"
    r"(?:(?:i|we)(?:\s+(?:also|only|just|still))?\s+)?"  # subject may be missing ("As a X would…")
    r"(?P<neg>(?:do\s+not|don['’]?t|no\s+longer)\s+)?"
    r"(?P<aux>wan+t|nee+d|must(?:\s+not)?|should(?:\s+not)?|would\s+like|['’]?d\s+like|wish|expect"
    r"|require|can(?:\s*not|['’]t)?|have|has|am|are)\s+"
    r"(?P<to>to\s+)?(?P<abil>(?:be\s+able\s+to|able\s+to|have\s+(?:the\s+)?ability\s+to"
    r"|the\s+ability\s+to|have\s+the\s+option\s+to)\s+)?"
    r"(?P<pred>.+?)"
    r"(?:\s*[,;]?\s+(?:so\s+that|in\s+order\s+(?:to|that)|so\s+as\s+to"
    r"|so(?=\s+(?:i|we|you|they|it|the|my|our|us)\b))\s+(?P<benefit>.+?))?"
    r"\s*(?:\.\s|\.$|\n|$)"
)
# Persona-context statements without an "I" clause — "As an agent, Einstein Lead Scoring is
# available to …". The role still frames the sentence; the statement is kept verbatim (re-voiced).
_PERSONA_RE = re.compile(
    r"(?is)^\s*as\s+(?:(?:an?|the)\s+)*(?P<role>[^,\n]{2,60}),\s+(?P<stmt>[^\n]{12,}?)(?:[.\n]|$)"
)
_AC_SPLIT = re.compile(r"(?im)^\s*(?:AC\s*\d+|criteria\s*\d+|scenario\s*\d+)\s*[:.\)-]\s*")
_THEN_RE = re.compile(r"(?is)\bthen\b\s*(?P<then>.+)$")
_SENT_SPLIT = re.compile(r"(?<=[.;!?])\s+|\n+")
_ARTICLE_DOUBLE_RE = re.compile(r"(?i)\b(?:a|an|the)\s+((?:a|an|the)\b)")
_JUNK_TEXT = frozenset(("tbd", "n a", "na", "none", "to be defined", "see", "ac", "n/a", "-"))

# third-singular conjugation for the weave subject ("A lending officer WANTS to …"); modals
# (must/should/can, negated or not) are their own third-person form already.
_THIRD_SING = {
    "want": "wants",
    "need": "needs",
    "wish": "wishes",
    "expect": "expects",
    "require": "requires",
    "have": "has",
}
_TO_AUX = frozenset(("want", "need", "wish", "expect", "require", "would like"))
# a head/summary that is itself story-voiced ("As a X, I want…", "Track agents we work with") is
# re-voiced to third person; a plain feature title ("Phase I rollout") is left untouched.
_FIRST_PERSON_HEAD_RE = re.compile(
    r"(?i)\b(?:i\s+(?:want|need|must|should|can|am|have|would|wish|expect|don['’]?t)|i['’]m"
    r"|we\b|my\b|our\b|me\b)"
)

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


def _strip_markup(raw: str) -> str:
    """Drop Jira-wiki/HTML markup so no heading token, code fence, bold star or table pipe ever
    reaches a facet or the narrative."""
    if not raw:
        return raw
    for pat, repl in _MARKUP_RES:
        raw = pat.sub(repl, raw)
    return raw


def _substitute(raw: str, sv_code: str | None) -> str:
    """Resolve bracket tokens so none ever leaks raw: [CLIENT_ROLE] -> the subvertical role;
    known/multi-word ALL-CAPS templates -> readable generics; a single ALL-CAPS acronym ([DAO]) or
    any other bracketed name ([Case], [i2c_SYSTEM_API]) -> its own text, unbracketed (a REAL name,
    never mangled)."""
    if not raw or "[" not in raw:
        return raw
    role = _role_phrase(sv_code)
    ph_raw = _config().get("placeholders")
    ph: dict[str, Any] = ph_raw if isinstance(ph_raw, dict) else {}

    def repl(m: re.Match[str]) -> str:
        tok = m.group(1).strip()
        key = tok.replace(" ", "_").upper().strip("_")
        if key == "CLIENT_ROLE":
            return role
        if key in ph:
            return str(ph[key])
        if "_" not in tok and " " not in tok:
            return tok  # single ALL-CAPS acronym — a real system name, kept verbatim
        if key.endswith("_NAME"):
            return "the " + key[:-5].replace("_", " ").lower()
        return key.replace("_", " ").lower()

    out = _PLACEHOLDER_RE.sub(repl, raw)
    out = _LEFTOVER_BRACKET_RE.sub(lambda m: m.group(1), out)
    # substitution can break article agreement ("an [CLIENT_ORG] user" -> "an client organisation
    # user") — repair a/an conservatively: lowercase-led words only (an acronym like "an FTE" is
    # never touched) and no u-/one-/European-type words whose sound contradicts their letter.
    out = re.sub(r"\ban(?=\s+[bcdfghj-np-tv-z][a-z])", "a", out)
    return re.sub(r"\ba(?=\s+(?!one\b|once\b|european\b)[aeio][a-z])", "an", out)


def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" .;-\t,")
    # collapse a doubled article (the raw template yields "As a a <role>" after substitution)
    return _ARTICLE_DOUBLE_RE.sub(r"\1", s)


def _is_junk(s: str) -> bool:
    return _clean(s).lower() in _JUNK_TEXT


def _third_person(s: str) -> str:
    """Re-voice a first-person clause ('I don't …' -> 'they don't …', 'I'm'/'I’m' -> 'they're',
    'I am' -> 'they are') so every woven clause reads in the narrative's third person. A bare 'I'
    glued to punctuation ('I-9', 'Phase I.') is left alone — that is a name, not a pronoun."""
    repl = {
        "i'm": "they're",
        "i've": "they've",
        "i'll": "they'll",
        "i'd": "they'd",
        "i am": "they are",
        "i was": "they were",
        "i": "they",
        "my": "their",
        "myself": "themselves",
        "mine": "theirs",
        "we're": "they're",
        "we've": "they've",
        "we": "they",
        "our": "their",
        "ours": "theirs",
        "us": "them",
        "me": "them",
    }
    out = re.sub(
        r"(?i)\b(i[’']m|i[’']ve|i[’']ll|i[’']d|i\s+am|i\s+was|we[’']re|we[’']ve"
        r"|i(?![’'\-.\w])|my|myself|mine|we|our|ours|us|me)\b",
        lambda m: repl[re.sub(r"[’']", "'", re.sub(r"\s+", " ", m.group(1).lower()))],
        s,
    )
    # a source artefact like "when I i want" re-voices to "they they" — collapse it
    return re.sub(r"(?i)\b(they|their)\s+\1\b", r"\1", out)


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


def _parse_story(desc: str) -> dict[str, str | None]:
    """The full user-story parse: role (article-less), the modal chain (neg + aux + whether an
    infinitive 'to' follows + whether ability boilerplate was folded out), the goal predicate and
    the benefit. Falls back to the persona-context shape ("As an agent, Einstein Scoring is
    available…") with the statement in ``stmt``. Empty dict values mean the shape is absent."""
    none: dict[str, str | None] = dict.fromkeys(
        ("role", "neg", "aux", "to", "abil", "pred", "benefit", "stmt")
    )
    m = _STORY_RE.search(desc)
    if m and m.group("aux").strip().lower() in ("am", "are") and not m.group("abil"):
        # "I am creating …" carries no modal to conjugate — keep the role and re-voice the clause
        # as a statement instead of forcing a broken verb chain.
        return {
            **none,
            "role": _clean(m.group("role")) or None,
            "stmt": _clean(f"I {m.group('aux')} {m.group('pred')}") or None,
        }
    if m:
        return {
            **none,
            "role": _clean(m.group("role")) or None,
            "neg": re.sub(r"[’']", "'", (m.group("neg") or "").strip().lower()) or None,
            # normalise apostrophes AND the corpus's stretched typos ("neeed" -> "need")
            "aux": re.sub(
                r"^(?:wan+t|nee+d)$",
                lambda mm: "want" if mm.group(0).startswith("wan") else "need",
                re.sub(r"[’']", "'", re.sub(r"\s+", " ", m.group("aux").strip().lower())),
            ),
            "to": "to" if (m.group("to") or m.group("abil")) else None,
            "abil": "abil" if m.group("abil") else None,
            "pred": _clean(m.group("pred")) or None,
            "benefit": _clean(m.group("benefit") or "") or None,
        }
    pm = _PERSONA_RE.search(desc)
    if pm:
        return {
            **none,
            "role": _clean(pm.group("role")) or None,
            "stmt": _clean(pm.group("stmt")) or None,
        }
    return none


def parse_role_goal_benefit(desc: str) -> tuple[str | None, str | None, str | None]:
    """Parse a user-story description into (role, goal, benefit); falls back to the first sentence
    as the goal when the 'As a … I want …' shape is absent."""
    if not desc:
        return None, None, None
    p = _parse_story(desc)
    if p["pred"]:
        goal = p["pred"]
        if p["neg"]:
            goal = f"not {goal}"
        return p["role"], goal, p["benefit"]
    if p["stmt"]:
        return p["role"], p["stmt"][:_POINT_CAP], None
    first = _SENT_SPLIT.split(desc.strip(), maxsplit=1)[0]
    return None, _clean(first)[:_POINT_CAP] or None, None


def parse_acceptance(ac_text: str) -> tuple[str, ...]:
    """The acceptance OUTCOMES: split on AC1:/AC2:/scenario markers, else sentences; keep each AC's
    'Then …' outcome where present (that is the delivered behaviour), else the whole point. A
    TBD/N-A field yields no points, never a junk bullet."""
    if not ac_text or _is_junk(ac_text):
        return ()
    chunks = _AC_SPLIT.split(ac_text)
    if len(chunks) <= 1:
        chunks = _SENT_SPLIT.split(ac_text)
    points: list[str] = []
    for c in chunks:
        c = c.strip()
        if not c or _is_junk(c):
            continue
        then = _THEN_RE.search(c)
        points.append(then.group("then") if then else c)
    return _dedup(points, _MAX_ACCEPT)


def parse_solution(sd_text: str) -> tuple[str, ...]:
    """The solution APPROACH: the config/build steps. Split on bullets/newlines/sentences, prefer
    lines that start with an action verb, drop URL-only references; empty/'TBD' -> no approach."""
    if not sd_text or _is_junk(sd_text):
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


def _subject(role: str, sv_code: str | None) -> str:
    """The weave subject with its article restored ('commercial lending officer' -> 'A commercial
    lending officer'); a role already carrying a determiner keeps it."""
    if re.match(r"(?i)^(a|an|the|any|every|each)\b", role):
        return role[0].upper() + role[1:]
    # 'u'-led roles are /ju:/ in this corpus (user, university-…) — they take "A", not "An"
    art = "An" if role[0].lower() in "aeio" else "A"
    return f"{art} {role}"


def _verb_phrase(neg: str | None, aux: str, to: str | None, abil: str | None) -> str:
    """Third-singular verb chain for the weave: 'want'+to -> 'wants to', do-negation -> 'doesn't
    want to', modals (must/should/can/can't) stay bare, 'no longer' keeps the conjugated verb, and
    'have the ability to' re-expresses as 'can' (the story's own meaning, one word)."""
    aux = re.sub(r"^'?d like$", "would like", aux)
    aux = re.sub(r"^can\s*not$", "cannot", aux)
    if aux in ("have", "has", "am", "are") and abil:
        return "can"  # "I have the ability to / am able to create …" -> "… can create …"
    lead = aux.split()[0]
    if neg in ("don't", "dont", "do not"):
        verb = f"does not {aux}" if neg == "do not" else f"doesn't {aux}"
    elif neg == "no longer":
        verb = f"no longer {_THIRD_SING.get(aux, aux)}"
    else:
        verb = _THIRD_SING.get(aux, aux)
    needs_to = to is not None and (aux in _TO_AUX or lead in _TO_AUX)
    return verb + (" to" if needs_to else "")


def _lower_first(s: str) -> str:
    return s[0].lower() + s[1:] if s else s


def synthesize(
    summary: str,
    description: str,
    ac_text: str,
    solution_design_text: str,
    tier: str | None,
    sv_code: str | None,
) -> StorySynthesis:
    """Deterministically synthesize a story's facets + a cohesive narrative from its raw text."""
    head_raw = _substitute(_strip_markup(summary or ""), sv_code)
    desc = _substitute(_strip_markup(description or ""), sv_code)
    p = _parse_story(desc)
    role, goal, benefit = parse_role_goal_benefit(desc)
    acceptance = parse_acceptance(_substitute(_strip_markup(ac_text or ""), sv_code))
    approach = parse_solution(_substitute(_strip_markup(solution_design_text or ""), sv_code))
    head = _clean(head_raw) or "This delivery"
    if _FIRST_PERSON_HEAD_RE.search(head):
        head = _third_person(head)  # a story-voiced summary re-voices; a plain title never matches

    # weave a cohesive, third-person, GRAMMATICAL paragraph (omit any absent facet gracefully)
    parts = [head.rstrip(".") + "."]
    if p["pred"] and p["aux"]:
        who = _subject(p["role"] or _role_phrase(sv_code), sv_code)
        verb = _verb_phrase(p["neg"], p["aux"], p["to"], p["abil"])
        sent = f"{who} {verb} {_third_person(p['pred'])}"
        if benefit:
            sent += f", so that {_third_person(benefit)}"
        parts.append(_clean(sent) + ".")
    elif p["stmt"] and p["role"]:
        # persona-context statement ("As an agent, Einstein Scoring is available…") — the role
        # frames the statement, verbatim and re-voiced.
        who = _subject(p["role"], sv_code)
        parts.append(_clean(f"For {_lower_first(who)}, {_third_person(p['stmt'])}") + ".")
    elif goal:
        # no user-story shape: the description's own first sentence, re-voiced — never a fabricated
        # "For <role>" attribution and never the raw "As a …, I …" text swallowed whole.
        stated = _clean(_third_person(goal))
        if stated and stated.lower()[:60] != head.lower()[:60]:
            parts.append(stated.rstrip(".") + ".")
    if acceptance:
        woven = tuple(_third_person(a) for a in acceptance[:2])
        parts.append("It is accepted when " + _join_lower(woven) + ".")
    if approach:
        woven = tuple(_third_person(a) for a in approach[:2])
        parts.append("The approach: " + _join_lower(woven) + ".")
    narrative = _clean(" ".join(parts))[:_NARRATIVE_CAP]
    return StorySynthesis(narrative, role, goal, benefit, acceptance, approach)


def _join_lower(points: tuple[str, ...]) -> str:
    lowered = [_lower_first(p) for p in points]
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
