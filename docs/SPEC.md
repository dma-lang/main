# SPEC index — where each thing is defined

Canonical sources live in [`docs/specs/`](./specs/) (HTML is canonical; `docs/specs/text/*.txt` are
convenience extractions). The approved implementation plan is at
`/root/.claude/plans/indexed-enchanting-llama.md`. This file is a map, not a substitute — open the source.

## Source documents
| File | What it defines |
|---|---|
| `specs/PRD.html` | Product purpose, four pillars (851 subcaps), FR-1..22, decisions **D1–D21**, claim labels, source tiers T1–T5, ERS, scope (public sources only **D6**; no cross-pillar **D16**) |
| `specs/TRD.html` | Single-Cloud-Run architecture, state model, API conventions, hybrid retrieval, jobs |
| `specs/UIUX-Brief.html` | Design tokens, component inventory, trust chips, surfaces |
| `specs/AppFlow.html` | 6 propagating filter objects, journeys **J1–J11**, system flows, per-page state contracts |
| `specs/Backend-Schema.html` | Narrative of the relational model (two planes) |
| `specs/schema.sql` | **Canonical DDL / Alembic baseline** — enums, `control.*`, `cat_<version>` template, indexes, views |
| `specs/carry_forward_subcap_mappings.py` | The story carry-forward algorithm (adopted as the F5 core) |
| `specs/Implementation.html` | **Canonical build manual** — F1–F15, gates G1–G8, §14 sequence, §15 self-healing, §16 deploy/migration, §17 models, §18 trend/consultant loop, §19 acceptance, **per-surface specs** |
| `specs/Implementation-Steps-overview.html` | Supporting phase/effort overview (not canonical where it differs from `Implementation.html`) |
| `specs/Engineering-Handoff.html` | Surface-by-surface endpoint contracts + build order |
| `specs/prototype/Capability_Intelligence_Agent.html` | **UX source of truth** — `NAV`, `window.PAGES`, data globals, modals, custom events, localStorage |

## Foundations F1–F15
Defined in `specs/Implementation.html` §2; sequenced in §14. Plan summary: Part E (and the per-foundation
rows). Build order and each foundation's deliverables are in `CLAUDE.md` and the plan.

| F | Foundation | Primary code home (target) |
|---|---|---|
| F1 | Service skeleton & envs | `backend/app/main.py`, `settings.py` |
| F2 | Auth & identity | `backend/app/deps.py`, `routers/me.py` |
| F3 | Control-plane schema & migrations | `backend/alembic/`, `app/migrate.py` |
| F4 | Schema-mapping + automap + provisioning | `app/services/mapping_provision.py` |
| F5 | Story pipeline + carry-forward | `app/services/carry_forward.py` (adopts `specs/carry_forward_subcap_mappings.py`) |
| F6 | Embeddings + hybrid retrieval | `app/intelligence/{embeddings,retrieval}.py` |
| F7 | Evidence/ERS/reasoning/jobs + DLP | `app/intelligence/ers.py`, `app/jobs/` |
| F8 | Gates G1–G8 + suggestion lifecycle | `app/intelligence/gates.py` (params: `config/gates.yaml`) |
| F9 | API conventions + trust envelope | `app/models/`, `app/routers/` |
| F10 | Frontend shell + state + tokens | `frontend/src/` (tokens in `src/tokens.css`) |
| F11 | Observability, SLOs & cost | `app/intelligence/router.py` cost tags, dashboards |
| F12 | Exports (HMAC) + append-only audit | `app/services/exports.py` |
| F13 | Intelligence layer + learning loops | `app/intelligence/` |
| F14 | Resilience & self-healing | `app/resilience/` |
| F15 | Relationship model + discovery | `app/services/mapping_provision.py`, `app/intelligence/discover.py` |

## Gates, models, schedules
- Gates **G1–G8**: defined in `specs/Implementation.html` §8; deterministic code in `app/intelligence/gates.py`;
  thresholds in [`config/gates.yaml`](../config/gates.yaml).
- Model pins & cost levers: `specs/Implementation.html` §17; pins in [`config/models.yaml`](../config/models.yaml).
- Schedules/cadence: `specs/Implementation.html` §18; in [`config/schedules.yaml`](../config/schedules.yaml).

## Surfaces (30)
The 9 sidebar groups A–I plus access surfaces (Login, Onboarding, Schema mapping, Settings). Each surface's
purpose, components, sources/relations, lifecycle, build steps, **per-page frontend↔backend QA checks**, and
done-criteria are in `specs/Implementation.html`; its UX is in the prototype; its endpoint↔table wiring is in
the plan (Part D) and `specs/Engineering-Handoff.html`.

## Schema quick map
`schema.sql` defines the **`control.*`** plane (identity, versions, mappings, `relation_def`, stories +
`story_subcap_carry`, evidence/ERS/reasoning/gates/citations, suggestions, governance, intelligence, KG) and
the per-version **`cat_<version>`** template (pillar→category→capability→subcap hierarchy, dimensions, link
tables, value chain, `subcap_completeness` view). The Alembic baseline additionally adds the SOW pipeline
tables (`sow_document`, `sow_scope_item`, `sow_subcap_match`), `benchmark`, and the enums `catalogue_impact`,
`source_type`, `offering_tier`, `data_product_category` (see plan Part C / ADR 0001).
