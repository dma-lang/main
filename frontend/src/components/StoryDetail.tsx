// Shared story-detail renderer (R8) — ONE presentational component so every surface that shows a
// Jira story (the Story library, the Delivery drilldown, the Use-case drawer, the Trace delivery lane)
// renders the SAME rich detail: the resolved CLIENT NAME as a prominent chip (with story_key kept as
// the id and project_key secondary), the synthesized narrative paragraph, and default-COLLAPSED
// Acceptance-criteria + Solution-design sections. The collapsibles reuse the open/close pattern from
// DeliveryDrillPanel's StoryLine and the tokens.css classes (.card/.chip/.muted/.eyebrow). Absent
// fields degrade gracefully — a missing client, narrative, AC or SD renders nothing, never "null".
import { type ReactNode, useState } from 'react';

import type { StoryFacets } from '../api/client';
import { Icon } from '../lib/icons';

// The minimal story shape StoryDetail needs — StoryRow and StoryLibraryRow both satisfy it.
export interface StoryLike {
  story_key: string;
  project_key?: string | null;
  client_name?: string | null;
  narrative?: string | null;
  facets?: StoryFacets | null;
  ac_text?: string | null;
  solution_design_text?: string | null;
}

/**
 * The resolved client as a prominent chip. `client_name` is the client (e.g. "Academy Bank");
 * story_key stays the per-story id and project_key is secondary. Renders the story_key alone when no
 * client resolved — never a bare "null". `idFirst` leads with the mono story_key (dense table/list
 * rows); otherwise the client chip leads (detail headers).
 */
export function ClientChip({
  story,
  idFirst = false,
  size = 9.5,
}: {
  story: StoryLike;
  idFirst?: boolean;
  size?: number;
}) {
  const client = story.client_name?.trim() || null;
  const proj = story.project_key?.trim() || null;
  const id = (
    <span className="mono" style={{ fontSize: size + 1, color: 'var(--text-primary)', flex: 'none' }}>
      {story.story_key}
    </span>
  );
  const clientChip = client ? (
    <span
      className="chip teal"
      style={{ fontSize: size, flex: 'none' }}
      title={proj && proj !== client ? `Client · Jira project ${proj}` : 'Client'}
    >
      <Icon n="building" s={size + 2} />
      {client}
    </span>
  ) : null;
  // project_key is only shown as a separate secondary chip when it isn't already the client identity
  const projChip =
    proj && proj !== client ? (
      <span className="chip soft" style={{ fontSize: size - 0.5, flex: 'none' }} title="Jira project (client proxy)">
        {proj}
      </span>
    ) : null;
  // when no client resolved, surface the project as the (soft) client proxy so a client is still shown
  const proxyChip =
    !client && proj ? (
      <span className="chip soft" style={{ fontSize: size, flex: 'none' }} title="Jira project (client proxy — no resolved client)">
        <Icon n="building" s={size + 2} />
        {proj}
      </span>
    ) : null;
  return (
    <span className="row gap6" style={{ flex: 'none', flexWrap: 'wrap' }}>
      {idFirst ? (
        <>
          {id}
          {clientChip ?? proxyChip}
          {projChip}
        </>
      ) : (
        <>
          {clientChip ?? proxyChip}
          {id}
          {projChip}
        </>
      )}
    </span>
  );
}

// A default-collapsed section (Acceptance criteria / Solution design), styled like StoryLine's expand
// region. `points` is the preferred structured list; `raw` is the fallback text. Renders nothing when
// both are empty, so absent detail never leaves an empty header.
function Collapsible({
  icon,
  label,
  points,
  raw,
}: {
  icon: 'check' | 'gear';
  label: string;
  points: string[];
  raw?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const list = points.filter((p) => p && p.trim());
  const text = raw?.trim() || '';
  if (!list.length && !text) return null;
  const count = list.length;
  return (
    <div className="card" style={{ overflow: 'hidden', background: 'var(--surface-base)' }}>
      <div
        className="between"
        style={{ padding: '7px 10px', cursor: 'pointer' }}
        onClick={() => setOpen(!open)}
      >
        <span className="row gap6" style={{ minWidth: 0 }}>
          <Icon n={open ? 'chevD' : 'chevR'} s={12} style={{ color: 'var(--text-tertiary)' }} />
          <Icon n={icon} s={12} style={{ color: 'var(--text-tertiary)', flex: 'none' }} />
          <span className="eyebrow" style={{ fontSize: 9.5 }}>
            {label}
          </span>
        </span>
        {count > 0 && (
          <span className="muted num" style={{ fontSize: 10, flex: 'none' }}>
            {count}
          </span>
        )}
      </div>
      {open && (
        <div
          className="fade-in"
          style={{ padding: '8px 12px 10px', borderTop: '1px solid var(--border-subtle)' }}
        >
          {list.length ? (
            <ul style={{ margin: 0, paddingLeft: 16, display: 'grid', gap: 4 }}>
              {list.map((p, i) => (
                <li key={i} style={{ fontSize: 11.5, lineHeight: 1.45, color: 'var(--text-secondary)' }}>
                  {p}
                </li>
              ))}
            </ul>
          ) : (
            <div
              style={{ fontSize: 11.5, lineHeight: 1.5, color: 'var(--text-secondary)', whiteSpace: 'pre-line' }}
            >
              {text}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The full rich detail for one story: the client chip (unless the caller already renders it in a
 * header — pass `showClient={false}`), the narrative paragraph, then the collapsible Acceptance
 * criteria (facets.acceptance → ac_text) and Solution design (facets.approach → solution_design_text).
 * Dense and scannable; any absent part is skipped. `extra` slots caller-specific rows (e.g. sub-score
 * bars) above the collapsibles.
 */
export function StoryDetail({
  story,
  showClient = true,
  idFirst = true,
  extra,
}: {
  story: StoryLike;
  showClient?: boolean;
  idFirst?: boolean;
  extra?: ReactNode;
}) {
  const narrative = story.narrative?.trim() || '';
  const facets = story.facets ?? null;
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {showClient && (
        <div className="row wrap gap6">
          <ClientChip story={story} idFirst={idFirst} />
        </div>
      )}
      {narrative && (
        <p style={{ margin: 0, fontSize: 12, lineHeight: 1.5, color: 'var(--text-secondary)' }}>
          {narrative}
        </p>
      )}
      {extra}
      <Collapsible
        icon="check"
        label="Acceptance criteria"
        points={facets?.acceptance ?? []}
        raw={story.ac_text}
      />
      <Collapsible
        icon="gear"
        label="Solution design"
        points={facets?.approach ?? []}
        raw={story.solution_design_text}
      />
    </div>
  );
}
