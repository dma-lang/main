// Value chain atlas (A3) — the 8 universal MECE clusters (VCC-01..08) and the per-subvertical
// stage pipeline. Cluster cards + counts come from the committed prototype config
// (frontend/src/data/valueChain.ts); subcap NAMES in the expanded pipeline join LIVE from the
// active catalogue version so the chips deep-link and peek correctly. The backend value-chain
// endpoint (sheet-21 seed) is deferred — see the data file header.
import { useMemo, useState } from 'react';

import { useSubcaps } from '../api/queries';
import { Dropdown, Page, SC } from '../components/primitives';
import { VALUE_CHAIN, VC_STAGES } from '../data/valueChain';
import { openPeek } from '../lib/events';
import { heatBg } from '../lib/helpers';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

export function ValueChain() {
  const ui = useUi();
  const version = ui.version;
  const [expanded, setExpanded] = useState('VCC-03');
  const [radial, setRadial] = useState(false);
  const subs = useSubcaps(version);
  const nameOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of subs.data ?? []) m.set(s.id, s.name);
    return m;
  }, [subs.data]);

  const sv = ui.sv === 'all' ? 'CL' : ui.sv;
  const stages = VC_STAGES[expanded + '|' + sv] ?? VC_STAGES[expanded + '|CL'];
  const max = Math.max(...VALUE_CHAIN.map((c) => c.count));
  const expandedName = VALUE_CHAIN.find((c) => c.code === expanded)?.name ?? '';

  const svOptions = [
    { v: 'all', l: 'Subvertical: CL' },
    { v: 'CL', l: 'SV: Commercial lending' },
    { v: 'CIB', l: 'SV: Corporate & investment banking' },
    { v: 'WM', l: 'SV: Wealth management' },
    { v: 'RIA', l: 'SV: Registered investment advisor' },
  ];

  return (
    <Page
      eyebrow="A · Explore"
      title="Value chain atlas"
      intro="The 8 universal MECE value-chain clusters and where the catalogue sits in each, by subvertical — so a pillar lead can spot coverage and gaps at a glance."
      actions={
        <div className="row gap8">
          <Dropdown value={ui.sv} icon="filter" options={svOptions} onChange={ui.setSv} />
          <button
            className={'btn sm ' + (radial ? 'primary' : 'ghost')}
            onClick={() => setRadial((r) => !r)}
          >
            <Icon n="dot" s={13} /> Radial
          </button>
        </div>
      }
    >
      <div className="card pad">
        <div className="muted" style={{ fontSize: 12, marginBottom: 16 }}>
          8 clusters, left to right. Counts are subcaps mapped to each cluster for the selected
          subvertical.
        </div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: radial ? 'repeat(4,1fr)' : 'repeat(8,1fr)',
            gap: 8,
          }}
        >
          {VALUE_CHAIN.map((c) => {
            const on = expanded === c.code;
            return (
              <div
                key={c.code}
                onClick={() => setExpanded(c.code)}
                className="card hov"
                style={{
                  padding: '12px 12px 14px',
                  cursor: 'pointer',
                  borderColor: on ? 'var(--border-strong)' : 'var(--border-subtle)',
                  background: on ? 'var(--surface-overlay)' : 'var(--surface-base)',
                  position: 'relative',
                }}
              >
                <div className="mono" style={{ fontSize: 10, color: 'var(--z-slate)', fontWeight: 700 }}>
                  {c.code}
                </div>
                <div className="h3" style={{ fontSize: 12.5, margin: '6px 0', minHeight: 32, lineHeight: 1.2 }}>
                  {c.name}
                </div>
                <div className="num" style={{ fontSize: 22, fontWeight: 700, color: 'var(--interactive)' }}>
                  {c.count}
                </div>
                <div className="muted" style={{ fontSize: 10 }}>
                  subcaps
                </div>
                <div className="muted" style={{ fontSize: 10.5, marginTop: 6, lineHeight: 1.3, minHeight: 26 }}>
                  {c.blurb}
                </div>
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    right: 0,
                    bottom: 0,
                    height: 3,
                    background: heatBg(c.count / max),
                    borderRadius: '0 0 5px 5px',
                  }}
                />
              </div>
            );
          })}
        </div>
      </div>

      {stages && (
        <div className="card pad mt16 fade-in">
          <div className="between" style={{ marginBottom: 4 }}>
            <div className="h2">{expandedName} — expanded</div>
            <span className="chip soft">{sv === 'CL' ? 'Commercial lending' : sv} · tab 21</span>
          </div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 16 }}>
            Subvertical-specific stages from <span className="mono">21_VC_Mapping_PerSubcap</span>.
            Click a subcap → deep dive scoped to the subvertical.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 0 }}>
            {stages.map((st, i) => (
              <div key={i} style={{ position: 'relative', paddingRight: 14 }}>
                <div className="row gap8" style={{ marginBottom: 10 }}>
                  <div
                    style={{
                      width: 24,
                      height: 24,
                      borderRadius: '50%',
                      background: 'var(--surface-overlay)',
                      color: 'var(--interactive)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 11,
                      fontWeight: 700,
                    }}
                  >
                    {i + 1}
                  </div>
                  <div className="h3" style={{ fontSize: 12.5 }}>
                    {st.stage}
                  </div>
                </div>
                <div style={{ display: 'grid', gap: 6 }}>
                  {st.subs.map((id) => (
                    <div
                      key={id}
                      className="card hov"
                      style={{ padding: '8px 10px', cursor: 'pointer' }}
                      onClick={() => openPeek(id)}
                    >
                      <SC id={id} />
                      <div
                        style={{
                          fontSize: 11.5,
                          color: 'var(--text-secondary)',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {nameOf.get(id) ?? '—'}
                      </div>
                    </div>
                  ))}
                </div>
                {i < stages.length - 1 && (
                  <Icon
                    n="chevR"
                    s={16}
                    style={{ position: 'absolute', right: 0, top: 4, color: 'var(--text-disabled)' }}
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </Page>
  );
}
