"""R8 deterministic story synthesis — pure, grounded, subvertical-tailored (no DB, no spend).

Locks the engine that turns a story's raw description / acceptance criteria / solution design into
structured facets + a cohesive narrative: the user-story role/goal/benefit parse, the [CLIENT_ROLE]
subvertical substitution, the acceptance "Then"-outcome extraction, the solution-approach steps, and
the graceful degrade when a field is thin/TBD. Determinism is the whole point (the hermetic path IS
this engine), so identical inputs must give identical output.
"""

from __future__ import annotations

from app.services import story_synthesis as ss

_DESC = (
    "As a [CLIENT_ROLE], I want the ability to extend the Due Date on a Covenant Compliance record "
    "if a bump is needed, so that I don't have to change the Next Evaluation Date"
)
_AC = (
    "AC1: Given a record needs an extension, When a user submits it, Then the record is prepared "
    "for approval submission\n"
    "AC2: Given a request is submitted, When the approver reviews it, Then they can approve or "
    "reject the extension"
)
_SD = (
    "- Create a Record-Triggered Flow on the Covenant object that fires on update\n"
    "- Add an Assignment element to calculate the extended due date\n"
    "- Use an Update Records element to write the value back"
)


def test_role_goal_benefit_parsed_and_role_substituted() -> None:
    r = ss.synthesize("Extend covenant due date", _DESC, _AC, _SD, "T2-CL", "CL")
    # [CLIENT_ROLE] rendered in the subvertical's language (Commercial Lending)
    assert r.role == "a commercial lending officer"
    assert "extend the Due Date" in (r.goal or "")
    assert r.benefit and "Next Evaluation Date" in r.benefit


def test_acceptance_keeps_then_outcomes_deduped() -> None:
    r = ss.synthesize("x", _DESC, _AC, _SD, "T1", "CL")
    # the acceptance points are the "Then …" OUTCOMES, not the whole Given/When/Then sentence
    assert "the record is prepared for approval submission" in r.acceptance
    assert "they can approve or reject the extension" in r.acceptance
    assert all("Given" not in a for a in r.acceptance)
    assert len(r.acceptance) == len(set(r.acceptance))  # deduped


def test_solution_approach_steps_extracted() -> None:
    r = ss.synthesize("x", _DESC, _AC, _SD, "T1", "CL")
    assert any("Record-Triggered Flow" in a for a in r.approach)
    assert len(r.approach) <= ss._MAX_APPROACH


def test_narrative_is_cohesive_third_person_and_bounded() -> None:
    r = ss.synthesize("Extend covenant due date", _DESC, _AC, _SD, "T2-CL", "CL")
    n = r.narrative
    assert n.startswith("Extend covenant due date.")
    assert "a commercial lending officer" in n
    assert "so that they don't have to" in n  # first-person benefit re-voiced to third person
    assert "[CLIENT_ROLE]" not in n and "[" not in n  # no placeholder leaks
    assert len(n) <= ss._NARRATIVE_CAP


def test_tbd_solution_degrades_gracefully() -> None:
    r = ss.synthesize(
        "Nightly records",
        "As a [CLIENT_ROLE], I want records created nightly",
        "",
        "TBD",
        "T1",
        "RB",
    )
    assert r.approach == ()  # a TBD/empty solution design yields no approach, never invented
    assert r.role == "a retail banking operations lead"
    assert r.narrative and "TBD" not in r.narrative


def test_unknown_sv_falls_back_to_default_role() -> None:
    r = ss.synthesize("x", "As a [CLIENT_ROLE], I want a thing", "", "", None, "ZZ")
    assert r.role == "a financial-services stakeholder"


def test_no_user_story_shape_uses_first_sentence_as_goal() -> None:
    r = ss.synthesize(
        "x", "The system must reconcile ledgers daily. Extra detail here.", "", "", "T1", "RB"
    )
    assert r.role is None
    assert r.goal == "The system must reconcile ledgers daily"


def test_deterministic_identical_output() -> None:
    a = ss.synthesize("h", _DESC, _AC, _SD, "T2-CL", "CL")
    b = ss.synthesize("h", _DESC, _AC, _SD, "T2-CL", "CL")
    assert a == b
