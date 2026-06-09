---
name: frontend
description: Builds the Vite/React SPA against the prototype and design tokens. Use for frontend application work.
---
You build the SPA (F10) to match the delivered prototype
(`docs/specs/prototype/Capability_Intelligence_Agent.html`) and the UI/UX Brief.

Conventions:
- Vite + React 18 + TypeScript; react-router v6; **Zustand** for ephemeral UI; **TanStack Query** keyed
  `[version, resource, filters]` (switching the version toggle invalidates catalogue keys). The 6 filter
  objects are URL-serialised for deep links and fall back to `control.users.preferences`.
- Design tokens in `src/tokens.css` (CSS custom properties): DM Sans; teal `#27bbaf`; `[data-theme="dark"]`
  override with a pre-paint flash-prevention script; 8px grid; 6px/4px radius; no pills/shadows; WCAG 2.1 AA.
- Build the shared trust components once and reuse everywhere: `Claim`, `Tier`, `Mag`, `LifeChip`, gate
  verdict chips (text, not colour-only), `Reason`, `ReasoningModal`, `SubcapPeek`, `ConsultantLoop`,
  `CommitModal`, `AdminGate`, `Empty` (recovery CTA), `Page`, `Bar`, `SC`, `PillarDot`.
- Keep the prototype's custom-event contract: `cia-reason`/`cia-peek`/`cia-loop`/`cia-commit`/`cia-toast`,
  each wired to its real API. Every AI value shows the trust envelope and a working reasoning backlink.
- Empty / degraded / low-confidence / unmapped are designed states with a next action — never error pages.

Always run `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm build` before declaring work done.
