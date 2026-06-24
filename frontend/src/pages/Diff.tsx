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
  // Default to PROVISIONED versions (oldest -> newest); with a single version that is an honest
  // self-compare. Picking v5 explicitly surfaces the not-provisioned designed state.
  const first = opts[0]?.v ?? '';
  const second = opts[1]?.v ?? first;
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const av = a || first;
  const bv = b || second;
  const diff = useDiff(av, bv);
  const d = diff.data;

  // Each change is a full-width CARD stacked VERTICALLY (not squeezed into a 3-column grid), so the
  // detailed explanation — exactly WHY a subcap is added / removed / renamed / modified — is legible.
  const section = (
    title: string,
    color: string,
    rows: { id: string; name: string; pillar: string; l2?: string | null; from_id?: string | null; changes?: string[]; explanation: string }[],
    note: string,
  ) => (
    <div className="card pad" style={{ marginBottom: 14 }}>
      <div className="between" style={{ marginBottom: 4 }}>
        <div className="row gap8">
          <span className="pilldot" style={{ background: color, width: 9, height: 9 }} />
          <div className="h3">{title}</div>
        </div>
        <span className="chip soft">{rows.length}</span>
      </div>
      <div className="muted" style={{ fontSize: 11.5, marginBottom: 10 }}>
        {note}
      </div>
      {rows.length === 0 ? (
        <div className="muted" style={{ fontSize: 12 }}>
          None.
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 8, maxHeight: 560, overflowY: 'auto' }}>
          {rows.slice(0, 120).map((r) => (
            <div
              key={r.id + (r.from_id ?? '')}
              className="card"
              style={{ padding: '10px 12px', borderLeft: `3px solid ${color}` }}
            >
              <div className="row gap8" style={{ alignItems: 'baseline', flexWrap: 'wrap' }}>
                <PillarDot p={r.pillar} s={7} />
                {r.from_id && (
                  <>
                    <span className="mono muted" style={{ fontSize: 11 }}>
                      {r.from_id}
                    </span>
                    <Icon n="arrowR" s={11} style={{ color: 'var(--text-tertiary)' }} />
                  </>
                )}
                <SC id={r.id} />
                <b style={{ fontSize: 12.5 }}>{r.name}</b>
                {r.l2 && (
                  <span className="chip soft" style={{ fontSize: 10 }} title="L2 capability">
                    {r.l2}
                  </span>
                )}
                {r.changes && r.changes.length > 0 && (
                  <span className="row wrap gap6" style={{ marginLeft: 'auto' }}>
                    {r.changes.map((c, i) => (
                      <span key={i} className="chip blue" style={{ fontSize: 10 }}>
                        {c}
                      </span>
                    ))}
                  </span>
                )}
              </div>
              <div className="muted" style={{ fontSize: 11.5, marginTop: 6, lineHeight: 1.5 }}>
                {r.explanation}
              </div>
            </div>
          ))}
          {rows.length > 120 && (
            <div className="muted" style={{ fontSize: 11 }}>
              +{rows.length - 120} more (showing the first 120)
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
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 12, marginBottom: 18 }}>
        {(
          [
            [d ? d.added.length : '—', 'Genuinely added', 'var(--interactive)'],
            [d ? d.removed.length : '—', 'Genuinely removed', 'var(--z-orange)'],
            [d ? d.modified.filter((m) => m.from_id).length : '—', 'Renamed / reassigned', 'var(--p4)'],
            [d ? d.modified.filter((m) => !m.from_id).length : '—', 'Modified (same id)', 'var(--z-blue)'],
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
        <div>
          {section(
            `Renamed / reassigned (${d.a} → ${d.b})`,
            'var(--p4)',
            d.modified.filter((m) => m.from_id),
            'Same subcap, new id — matched by subcap name, or by L2 capability name with a near description. Id governance never recycles ids, so a fresh id was minted; this is NOT a removal.',
          )}
          {section(
            `Removed from ${d.a}`,
            'var(--z-orange)',
            d.removed,
            'Genuinely gone — neither the subcap id NOR its L2 capability name survives in the newer version with a near description (deduped or dropped at source).',
          )}
          {section(
            `Added in ${d.b}`,
            'var(--interactive)',
            d.added,
            'Genuinely new — no id or L2-capability+description match in the older version.',
          )}
          {section(
            'Modified (same id, kept)',
            'var(--z-blue)',
            d.modified.filter((m) => !m.from_id),
            'The subcap kept its id; these are the fields that actually changed. A reworded description that keeps its meaning does not count — only a near-total rewrite does.',
          )}
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
