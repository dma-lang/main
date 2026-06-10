// Diff viewer (Stage G · Versioning & QA) — exactly what changed between two catalogue versions.
// The A/B selectors are driven by the live /api/versions list; the per-subcap added/removed/modified
// diff has no backend endpoint yet, so the change region shows an honest Empty state with a recovery
// CTA rather than fabricated deltas. Ported from the prototype Diff.
import { useState } from 'react';

import { useVersions } from '../api/queries';
import { Dropdown, Empty, Page } from '../components/primitives';
import { go, toast } from '../lib/events';
import { Icon } from '../lib/icons';

export function Diff() {
  const versions = useVersions();
  const opts = (versions.data ?? []).map((v) => ({ v: v.version_id, l: v.label }));
  const first = opts[0]?.v ?? '';
  const second = opts[1]?.v ?? opts[0]?.v ?? '';
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const av = a || first;
  const bv = b || second;

  return (
    <Page
      eyebrow="G · Versioning & QA"
      title="Diff viewer"
      intro="Exactly what changed between two catalogue versions — added, removed and modified subcaps, with pillar and category deltas."
      actions={
        <div className="row gap8">
          <Dropdown value={av} options={opts} onChange={setA} />
          <Icon n="arrowR" s={14} style={{ color: 'var(--text-tertiary)' }} />
          <Dropdown value={bv} options={opts} onChange={setB} />
          <button
            className="btn ghost sm"
            onClick={() => toast('Generating narrative diff (Gemini Pro)…')}
          >
            <Icon n="sparkles" s={14} />
            Explain diff
          </button>
        </div>
      }
    >
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3,1fr)',
          gap: 12,
          marginBottom: 18,
        }}
      >
        <div className="kpi">
          <div className="kv" style={{ color: 'var(--interactive)' }}>
            —
          </div>
          <div className="kl">Subcaps added (FC subvertical)</div>
        </div>
        <div className="kpi">
          <div className="kv">—</div>
          <div className="kl">Subcaps removed</div>
        </div>
        <div className="kpi">
          <div className="kv" style={{ color: 'var(--z-blue)' }}>
            —
          </div>
          <div className="kl">Subcaps modified</div>
        </div>
      </div>
      <div className="card pad">
        <Empty
          icon="compare"
          title="Version diff pipeline pending"
          desc="The per-subcap added / removed / modified comparison between catalogue versions is not yet wired to a backend endpoint. Once the diff service lands, this region lists every change with its pillar and category delta."
          cta="Open version timeline"
          onCta={() => go('versions')}
        />
      </div>
      <div className="banner info mt16">
        <Icon n="branch" s={15} />
        v5 lineage is preserved via the{' '}
        <span className="mono" style={{ margin: '0 4px' }}>
          _R1_Source_Reference
        </span>{' '}
        crosswalk — each subcap keeps one identity across versions.
      </div>
    </Page>
  );
}
