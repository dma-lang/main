// Diff viewer (G2) — exactly what changed between two catalogue versions, wired to
// GET /api/diff/{a}/{b}: per-subcap added / removed / modified (with the changed fields named) +
// real KPI counts. A self-compare is an honest empty diff; an unprovisioned version (e.g. v5 until
// its legacy workbooks are ingested) renders the clear designed state, never a fabricated delta.
import { useState } from 'react';

import { useDiff, useVersions } from '../api/queries';
import { Dropdown, Empty, Page, PillarDot, SC } from '../components/primitives';
import { go, toast } from '../lib/events';
import { Icon } from '../lib/icons';

export function Diff() {
  const versions = useVersions();
  const opts = (versions.data ?? []).map((v) => ({ v: v.version_id, l: v.label }));
  // v5 stays offered (the prototype's pairing) so picking it surfaces the honest unprovisioned state.
  const haveV5 = opts.some((o) => o.v === 'v5');
  const selOpts = haveV5 ? opts : [...opts, { v: 'v5', l: 'v5 · legacy (not provisioned)' }];
  const first = opts[0]?.v ?? '';
  const second = opts[1]?.v ?? 'v5';
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const av = a || second; // prototype defaults: legacy → active
  const bv = b || first;
  const diff = useDiff(av, bv);
  const d = diff.data;

  const section = (
    title: string,
    color: string,
    rows: { id: string; name: string; pillar: string; changes?: string[] }[],
  ) => (
    <div className="card pad">
      <div className="between" style={{ marginBottom: 8 }}>
        <div className="h3">{title}</div>
        <span className="chip soft">{rows.length}</span>
      </div>
      {rows.length === 0 ? (
        <div className="muted" style={{ fontSize: 12 }}>
          None.
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 6, maxHeight: 420, overflowY: 'auto' }}>
          {rows.slice(0, 80).map((r) => (
            <div key={r.id} className="row gap8" style={{ fontSize: 12, alignItems: 'baseline' }}>
              <span className="pilldot" style={{ background: color, width: 7, height: 7, flex: 'none' }} />
              <PillarDot p={r.pillar} s={7} />
              <SC id={r.id} />
              <span style={{ color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.name}
              </span>
              {r.changes && (
                <span className="chip soft" style={{ marginLeft: 'auto', flex: 'none' }}>
                  {r.changes.join(' · ')}
                </span>
              )}
            </div>
          ))}
          {rows.length > 80 && (
            <div className="muted" style={{ fontSize: 11 }}>
              +{rows.length - 80} more
            </div>
          )}
        </div>
      )}
    </div>
  );

  return (
    <Page
      eyebrow="G · Versioning & QA"
      title="Diff viewer"
      intro="Exactly what changed between two catalogue versions — added, removed and modified subcaps, with the changed fields named."
      actions={
        <div className="row gap8">
          <Dropdown value={av} options={selOpts} onChange={setA} />
          <Icon n="arrowR" s={14} style={{ color: 'var(--text-tertiary)' }} />
          <Dropdown value={bv} options={selOpts} onChange={setB} />
          <button
            className="btn ghost sm"
            onClick={() => toast('Narrative diff lands with the synthesis budget (G8-gated)')}
          >
            <Icon n="sparkles" s={14} />
            Explain diff
          </button>
        </div>
      }
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 18 }}>
        {(
          [
            [d ? d.added.length : '—', 'Subcaps added', 'var(--interactive)'],
            [d ? d.removed.length : '—', 'Subcaps removed', 'var(--z-orange)'],
            [d ? d.modified.length : '—', 'Subcaps modified', 'var(--z-blue)'],
            [d ? d.unchanged : '—', 'Unchanged', 'var(--text-primary)'],
          ] as [string | number, string, string][]
        ).map(([v, l, c], i) => (
          <div key={i} className="kpi">
            <div className="kv" style={{ color: c }}>
              {v}
            </div>
            <div className="kl">{l}</div>
          </div>
        ))}
      </div>

      {diff.isLoading && (
        <div className="card pad muted" style={{ fontSize: 12 }}>
          Comparing {av} → {bv}…
        </div>
      )}
      {diff.isError && (
        <div className="card pad">
          <Empty
            icon="compare"
            title={`${av === 'v5' || bv === 'v5' ? 'v5 is not provisioned yet' : 'Comparison unavailable'}`}
            desc={
              av === 'v5' || bv === 'v5'
                ? 'The legacy v5 workbooks have not been ingested. Upload them in Settings → Catalogue ingestion (or run the onboarding wizard) and the v5 ↔ v7 diff lights up here, with renames resolved via the crosswalk.'
                : 'One of the selected versions could not be resolved. Pick two provisioned versions from the timeline.'
            }
            cta="Open version timeline"
            onCta={() => go('versions')}
          />
        </div>
      )}
      {d && d.added.length + d.removed.length + d.modified.length === 0 && (
        <div className="card pad">
          <Empty
            icon="compare"
            title="No differences"
            desc={`${d.a} and ${d.b} are identical across name, lifecycle, description and tier — ${d.unchanged} subcaps unchanged.`}
          />
        </div>
      )}
      {d && d.added.length + d.removed.length + d.modified.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 14 }}>
          {section(`Added in ${d.b}`, 'var(--interactive)', d.added)}
          {section(`Removed from ${d.a}`, 'var(--z-orange)', d.removed)}
          {section('Modified', 'var(--z-blue)', d.modified)}
        </div>
      )}

      <div className="banner info mt16">
        <Icon n="branch" s={15} />
        v5 lineage is preserved via the{' '}
        <span className="mono" style={{ margin: '0 4px' }}>
          _R1_Source_Reference
        </span>{' '}
        crosswalk — each subcap keeps one identity across versions; renames resolve through it once
        the legacy workbook is ingested.
      </div>
    </Page>
  );
}
