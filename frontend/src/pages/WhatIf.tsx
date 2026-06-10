// What-if simulator (Stage I · Sandbox) — a read-only sandbox to test a catalogue change before
// proposing it: pick one of 7 action kinds and a target subcap, simulate, and preview the cascade. The
// action editor is live (target picker from /api/catalogue subcaps); the cascade simulation has no
// backend endpoint yet, so the result region shows an honest Empty/banner rather than fabricated deltas.
// Ported from the prototype WhatIf.
import { useState } from 'react';

import { useSubcaps } from '../api/queries';
import { Dropdown, Empty, Page } from '../components/primitives';
import { go, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const KINDS = [
  { v: 'toggle', l: 'Workbook toggle (XLOOKUP cascade)' },
  { v: 'retire', l: 'Retire subcap' },
  { v: 'descriptor', l: 'Edit M-descriptor' },
  { v: 'platform', l: 'Remap L3 platform' },
  { v: 'relation', l: 'Add relation' },
  { v: 'merge', l: 'Merge subcaps' },
  { v: 'offering', l: 'Bundle into offering' },
];

export function WhatIf() {
  const ui = useUi();
  const subs = useSubcaps(ui.version);
  const [action, setAction] = useState('toggle');
  const [sub, setSub] = useState('');
  const [ran, setRan] = useState(false);

  const options = (subs.data ?? []).slice(0, 30).map((x) => ({
    v: x.id,
    l: x.id + ' · ' + x.name.slice(0, 20),
  }));
  const cur = sub || options[0]?.v || '';

  return (
    <Page
      eyebrow="I · Sandbox"
      title="What-if simulator"
      intro="A read-only sandbox: test a catalogue change safely before proposing it. Edit an action across 7 kinds, simulate, and preview the cascade — lifecycle and adoption deltas, transitions, affected-subcap count, KG orphans and a benchmark recompute."
    >
      <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: 18, alignItems: 'start' }}>
        <div className="card pad">
          <div className="h3" style={{ marginBottom: 12 }}>
            Action editor
          </div>
          <div className="eyebrow" style={{ marginBottom: 6 }}>
            Action kind
          </div>
          <Dropdown
            value={action}
            options={KINDS}
            onChange={(v) => {
              setAction(v);
              setRan(false);
            }}
          />
          <div className="eyebrow" style={{ margin: '14px 0 6px' }}>
            Target subcap
          </div>
          <Dropdown
            value={cur}
            icon="branch"
            options={options}
            onChange={(v) => {
              setSub(v);
              setRan(false);
            }}
          />
          <div className="card pad mt16" style={{ background: 'var(--surface-raised)', padding: '12px 14px' }}>
            <div className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>
              {action === 'toggle'
                ? 'Deactivating cascades to dependent rows across 9 tabs via the deterministic XLOOKUP chain.'
                : action === 'retire'
                  ? 'Retiring removes the subcap and orphans its KG edges.'
                  : 'This action is simulated read-only — nothing is written to the catalogue.'}
            </div>
          </div>
          <button
            className="btn primary sm"
            style={{ width: '100%', justifyContent: 'center', marginTop: 14 }}
            onClick={() => {
              setRan(true);
              toast('Simulation complete — read-only');
            }}
          >
            <Icon n="beaker" s={14} />
            Simulate
          </button>
        </div>
        <div>
          {!ran ? (
            <div className="card">
              <Empty
                icon="beaker"
                title="No simulation yet"
                desc="Pick an action and target, then simulate to preview the cascade. Nothing is committed."
              />
            </div>
          ) : (
            <div className="banner info">
              <Icon n="beaker" s={15} />
              The cascade simulation engine — affected-subcap count, KG orphans, adoption and lifecycle
              deltas, transitions and benchmark recompute — is not yet wired to a backend endpoint. Once
              it lands, the read-only preview for the simulated {action} on {cur || 'this subcap'} renders
              here, ready to promote to a gated change. Explore committed changes in the{' '}
              <a onClick={() => go('change-flags')} style={{ cursor: 'pointer' }}>
                change flags inbox
              </a>
              .
            </div>
          )}
        </div>
      </div>
    </Page>
  );
}
