# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Repository scaffold (Stage 0): monorepo layout, tooling configuration, and CI skeleton.
- `CLAUDE.md` rule sheet encoding the non-negotiable safeguards.
- Canonical specs committed under `docs/specs/` and indexed by `docs/SPEC.md`.
- Project safety hooks (`.claude/hooks/`) and subagent definitions (`.claude/agents/`).
- `config/{models.yaml,schedules.yaml,gates.yaml}` — model pins, schedules, and gate thresholds as data.
- ADR 0001 recording the approved stack, model pins, and source-of-truth decisions.
