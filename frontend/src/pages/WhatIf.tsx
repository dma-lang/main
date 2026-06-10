// What-if simulator (Stage I · Sandbox) — a read-only sandbox to test a catalogue change before
// proposing it: pick one of 7 action kinds and a target subcap, simulate, and preview the cascade. The
// action editor is live (target picker from /api/catalogue subcaps); the cascade simulation has no
// backend endpoint yet, so the result region shows an honest Empty/banner rather than fabricated deltas.
// Ported from the prototype WhatIf.
import { useState } from 'react';

import { useSubcaps, useWhatIf } from '../api/queries';
import { Dropdown, Empty, Page, SC } from '../components/primitives';
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
  const wi = useWhatIf(ui.version, cur, action, ran);
  const d = wi.data;

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
          ) : wi.isLoading ? (
            <div className="card pad muted" style={{ fontSize: 12 }}>
              Computing the cascade…
            </div>
          ) : d ? (
            <div className="fade-in" style={{ display: 'grid', gap: 14 }}>
              <div className="card pad">
                <div className="row gap8" style={{ marginBottom: 8 }}>
                  <span className="chip soft">read-only preview</span>
                  <span className="chip teal">reversible</span>
                  <span className="muted mono" style={{ fontSize: 11, marginLeft: 'auto' }}>
                    {d.subcap}
                  </span>
                </div>
                <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                  {d.summary}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 8, marginTop: 14 }}>
                  {(
                    [
                      [d.blast, 'rows in blast radius'],
                      [d.platforms.length, 'platforms'],
                      [d.offerings.length, 'offerings'],
                      [d.stories.toLocaleString(), 'stories'],
                      [d.siblings.length, 'KG siblings'],
                    ] as [string | number, string][]
                  ).map((k, i) => (
                    <div key={i} className="card" style={{ padding: '10px 6px', textAlign: 'center' }}>
                      <div className="num" style={{ fontSize: 18, fontWeight: 700, color: i === 0 ? 'var(--z-orange)' : 'var(--interactive)' }}>
                        {k[0]}
                      </div>
                      <div className="muted" style={{ fontSize: 9.5 }}>{k[1]}</div>
                    </div>
                  ))}
                </div>
              </div>
              {(d.offerings.length > 0 || d.siblings.length > 0) && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                  <div className="card pad">
                    <div className="eyebrow" style={{ marginBottom: 8 }}>Offerings affected</div>
                    {d.offerings.length ? (
                      d.offerings.map((o) => (
                        <div key={o.id} style={{ fontSize: 12, marginBottom: 4 }}>
                          <Icon n="package" s={12} /> {o.name}
                        </div>
                      ))
                    ) : (
                      <div className="muted" style={{ fontSize: 12 }}>None — this subcap is in no offering.</div>
                    )}
                  </div>
                  <div className="card pad">
                    <div className="eyebrow" style={{ marginBottom: 8 }}>Shared-platform siblings (KG ripple)</div>
                    <div className="row wrap gap6">
                      {d.siblings.slice(0, 10).map((sb) => (
                        <SC key={sb.id} id={sb.id} />
                      ))}
                      {!d.siblings.length && <span className="muted" style={{ fontSize: 12 }}>None</span>}
                    </div>
                  </div>
                </div>
              )}
              <div className="card pad" style={{ background: 'var(--surface-raised)' }}>
                <div className="between">
                  <div className="muted" style={{ fontSize: 12, maxWidth: 380 }}>
                    Promote this scenario to a gated suggestion — it runs the consultant loop (G1–G8)
                    and lands in AI suggestions; nothing commits ungated.
                  </div>
                  <button
                    className="btn primary sm"
                    onClick={() => {
                      toast('Scenario captured — open its subcap to stage a gated change');
                      go('subcap/' + d.subcap);
                    }}
                  >
                    Open subcap to promote <Icon n="arrowR" s={14} />
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="card pad muted" style={{ fontSize: 12 }}>
              Could not compute the cascade.{' '}
              <a onClick={() => go('change-flags')} style={{ cursor: 'pointer' }}>
                Change flags
              </a>
            </div>
          )}
        </div>
      </div>
    </Page>
  );
}
