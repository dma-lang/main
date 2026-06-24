// Value chain atlas (A3) — the catalogue's REAL value chain, rendered as the prototype's
// left-to-right ORDERED PIPELINE. Stages come from the v7 VC-mapping sheet (cat_<v>.subcap_vcc),
// per subvertical, in chain order (stage_ord) — cascaded v7 -> v5 at provision. Stage labels are
// cleaned of "(SV-Specific: …)"-style noise and merged. When a subvertical is picked the page shows
// that one chain; when 'All SV' is picked it lists EVERY subvertical's chain (delivery-ranked). The
// stage NAME is the headline; the VCC code is only an internal id. Pillar pills are the header
// pillar. Click a stage to list its subcaps (peek / deep-dive).
import { useEffect, useState } from 'react';

import type { ValueChainCluster, ValueChainGroup } from '../api/client';
import { useValueChain } from '../api/queries';
import { Dropdown, Empty, Page, PillarDot } from '../components/primitives';
import { go, openPeek } from '../lib/events';
import { heatBg } from '../lib/helpers';
import { Icon } from '../lib/icons';
import { type Pillar, useUi } from '../state/store';

const PILLARS: Pillar[] = ['all', 'P1', 'P2', 'P3', 'P4'];

// subvertical code -> friendly name (matches the header; FC is Farm Credit, per the data).
const SV_NAME: Record<string, string> = {
  RB: 'Retail banking',
  CU: 'Credit unions',
  CL: 'Commercial lending',
  CIB: 'Corporate & investment banking',
  FC: 'Farm credit / ag lending',
  AM: 'Asset & wealth management',
  RIA: 'RIA / broker-dealer',
  IC: 'Insurance carriers',
  IB: 'Insurance brokerages',
};

// Radial view — wedge radius ∝ subcap count, in chain order.
function RadialWheel({ segs }: { segs: ValueChainCluster[] }) {
  const cx = 200;
  const cy = 200;
  const max = Math.max(1, ...segs.map((s) => s.count));
  const total = segs.reduce((a, s) => a + s.count, 0);
  return (
    <div className="card pad" style={{ display: 'flex', justifyContent: 'center' }}>
      <svg width="100%" height={400} viewBox="0 0 400 400" style={{ maxWidth: 440 }}>
        {segs.map((s, i) => {
          const a0 = (i / segs.length) * 2 * Math.PI - Math.PI / 2;
          const a1 = ((i + 1) / segs.length) * 2 * Math.PI - Math.PI / 2;
          const rr = 60 + (s.count / max) * 90;
          const x0 = cx + Math.cos(a0) * rr;
          const y0 = cy + Math.sin(a0) * rr;
          const x1 = cx + Math.cos(a1) * rr;
          const y1 = cy + Math.sin(a1) * rr;
          const mid = (a0 + a1) / 2;
          const lx = cx + Math.cos(mid) * (rr + 16);
          const ly = cy + Math.sin(mid) * (rr + 16);
          return (
            <g key={s.code}>
              <path
                d={`M${cx} ${cy} L${x0} ${y0} A${rr} ${rr} 0 0 1 ${x1} ${y1} Z`}
                fill={heatBg(s.count / max)}
                stroke="var(--surface-base)"
                strokeWidth="2"
              />
              <text x={lx} y={ly} fontSize="8" fontWeight="700" fill="var(--text-tertiary)" textAnchor="middle" dominantBaseline="middle">
                {s.name.length > 14 ? s.name.slice(0, 13) + '…' : s.name}
              </text>
            </g>
          );
        })}
        <circle cx={cx} cy={cy} r={50} fill="var(--surface-base)" stroke="var(--border-subtle)" />
        <text x={cx} y={cy - 4} fontSize="22" fontWeight="700" fill="var(--interactive)" textAnchor="middle">
          {total}
        </text>
        <text x={cx} y={cy + 12} fontSize="9" fill="var(--text-tertiary)" textAnchor="middle">
          subcaps mapped
        </text>
      </svg>
    </div>
  );
}

// One subvertical's ordered pipeline + its inline stage drilldown. Self-contained so the 'All SV'
// view can stack one section per subvertical, each with its own open stage.
function ChainSection({
  chain,
  radial,
  showHeader,
}: {
  chain: ValueChainGroup;
  radial: boolean;
  showHeader: boolean;
}) {
  const clusters = chain.clusters;
  const [open, setOpen] = useState<string | null>(clusters[0]?.code ?? null);
  // re-focus the first stage when the underlying chain changes (version / pillar / sv switch)
  useEffect(() => setOpen(clusters[0]?.code ?? null), [chain.sv, clusters.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const current = clusters.find((c) => c.code === open) ?? clusters[0] ?? null;

  return (
    <div style={{ marginBottom: showHeader ? 22 : 0 }}>
      {showHeader && (
        <div className="row gap8" style={{ marginBottom: 8, alignItems: 'baseline' }}>
          <Icon n="route" s={13} cls="" style={{ color: 'var(--interactive)' }} />
          <b style={{ fontSize: 14 }}>{SV_NAME[chain.sv] ?? chain.sv} value chain</b>
          <span className="muted" style={{ fontSize: 11.5 }}>
            {clusters.length} stages · {chain.total_subcaps} subcaps
          </span>
        </div>
      )}
      {radial ? (
        <RadialWheel segs={clusters} />
      ) : (
        <>
          {/* the ORDERED pipeline — left-to-right, stage NAME headline, ordinal not code */}
          <div className="card pad" style={{ marginBottom: 12, overflowX: 'auto' }}>
            <div className="row" style={{ gap: 0, alignItems: 'stretch', minWidth: 'min-content' }}>
              {clusters.map((c, i) => {
                const on = c.code === open;
                return (
                  <div key={c.code} className="row" style={{ gap: 0, alignItems: 'center' }}>
                    <button
                      onClick={() => setOpen(c.code)}
                      className="card hov"
                      style={{
                        width: 150,
                        minHeight: 96,
                        textAlign: 'left',
                        padding: '10px 12px',
                        cursor: 'pointer',
                        flex: 'none',
                        borderColor: on ? 'var(--interactive)' : 'var(--border-subtle)',
                        background: on ? 'var(--surface-overlay)' : 'var(--surface-base)',
                      }}
                    >
                      <div className="row gap6" style={{ marginBottom: 5 }}>
                        <span className="num" style={{ fontSize: 10, fontWeight: 700, color: 'var(--interactive)' }}>
                          {String(c.position ?? i + 1).padStart(2, '0')}
                        </span>
                        {c.pillar && <PillarDot p={c.pillar} s={6} />}
                      </div>
                      <div style={{ fontSize: 11.5, fontWeight: 600, lineHeight: 1.25, minHeight: 42 }}>
                        {c.name}
                      </div>
                      <div className="num" style={{ fontSize: 17, fontWeight: 700, color: 'var(--text-primary)' }}>
                        {c.count}
                        <span className="muted" style={{ fontSize: 9.5, fontWeight: 400 }}> subcaps</span>
                      </div>
                    </button>
                    {i < clusters.length - 1 && (
                      <Icon n="chevR" s={14} cls="" style={{ color: 'var(--text-tertiary)', flex: 'none', margin: '0 2px' }} />
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {current && (
            <div className="card pad fade-in">
              <div className="between" style={{ marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
                <div className="row gap8">
                  <span className="num chip teal" style={{ fontSize: 11 }}>
                    Stage {String(current.position ?? 1).padStart(2, '0')}
                  </span>
                  <b style={{ fontSize: 15 }}>{current.name}</b>
                  {current.pillar && <span className="chip soft">{current.pillar}</span>}
                  <span className="muted" style={{ fontSize: 12 }}>
                    {current.count} subcaps
                  </span>
                </div>
              </div>
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                Subcaps in this stage — click to peek, double-click to open the deep dive
              </div>
              <div className="row wrap gap6">
                {current.subcaps.map((s) => (
                  <span
                    key={s.id}
                    className="chip soft"
                    style={{ cursor: 'pointer', fontSize: 11 }}
                    title={s.id}
                    onClick={() => openPeek(s.id)}
                    onDoubleClick={() => go('subcap/' + s.id)}
                  >
                    {s.pillar && <PillarDot p={s.pillar} s={6} />}
                    {s.name}
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function ValueChain() {
  const ui = useUi();
  const version = ui.version;
  const pillar = ui.pillar; // header-linked
  const setPillar = ui.setPillar;
  const [radial, setRadial] = useState(false);

  const res = useValueChain(version, pillar, ui.sv);
  const data = res.data;
  // prefer the per-subvertical chains; fall back to wrapping the flat clusters (derived path)
  const chains: ValueChainGroup[] =
    data?.chains && data.chains.length > 0
      ? data.chains
      : data && data.clusters.length > 0
        ? [{ sv: data.resolved_sv || ui.sv || 'all', clusters: data.clusters, total_subcaps: data.total_subcaps }]
        : [];
  const multi = chains.length > 1;

  return (
    <Page
      eyebrow="A · Explore"
      title="Value chain atlas"
      intro="The catalogue's value chain — the real, named stages. 'All SV' consolidates every subvertical into one chain (overlapping stages merged), and pinning a subvertical shows just its own (a version without its own mapping inherits the reference's)."
      actions={
        <button className={'btn sm ' + (radial ? 'primary' : 'ghost')} onClick={() => setRadial((r) => !r)}>
          <Icon n="route" s={13} /> {radial ? 'Pipeline' : 'Radial'}
        </button>
      }
    >
      <div className="row wrap gap8" style={{ marginBottom: 14, alignItems: 'center' }}>
        <div className="pillseg">
          {PILLARS.map((p) => (
            <button key={p} className={pillar === p ? 'on' : ''} onClick={() => setPillar(p)}>
              {p === 'all' ? 'All pillars' : p}
            </button>
          ))}
        </div>
        {/* 'All SV' consolidates the whole catalogue; pick a subvertical for its real named chain */}
        {(data?.subverticals?.length ?? 0) > 0 && (
          <Dropdown
            label="All SV"
            value={ui.sv}
            options={[
              { v: 'all', l: 'All SV — consolidated' },
              ...(data?.subverticals ?? []).map((c) => ({ v: c, l: SV_NAME[c] ?? c })),
            ]}
            onChange={ui.setSv}
          />
        )}
        {data?.inherited_from && (
          <span className="chip teal" style={{ fontSize: 11 }}>
            <Icon n="route" s={11} /> inherited from {data.inherited_from}
          </span>
        )}
        {data && chains.length > 0 && (
          <span className="muted" style={{ fontSize: 12, marginLeft: 'auto' }}>
            {multi
              ? `${chains.length} subverticals · ${data.total_subcaps} subcaps`
              : `${chains[0].clusters.length} stages · ${data.total_subcaps} subcaps`}
          </span>
        )}
      </div>

      {chains.length === 0 ? (
        <Empty
          icon="route"
          title="No value chain yet"
          desc="Provision a catalogue version (upload its workbooks) and its value-chain stages appear here, in order, per subvertical."
        />
      ) : (
        chains.map((ch) => <ChainSection key={ch.sv} chain={ch} radial={radial} showHeader={multi} />)
      )}
    </Page>
  );
}
