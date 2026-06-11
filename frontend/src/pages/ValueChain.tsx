// Value chain atlas (A3) — DYNAMIC. Segments are DERIVED LIVE from the active catalogue version's
// own capability categories (GET /api/catalogue/{v}/value-chain): deduped (same segment, different
// spelling -> one) and smart-clustered (near-duplicate names merged, shown transparently). v5 and
// v7 each derive their own chain from their own data — nothing hardcoded. Click a segment to see
// its stages (the finer capabilities) and subcaps; chips deep-link/peek into the workbench.
import { useEffect, useState } from 'react';

import type { ValueChainCluster } from '../api/client';
import { useValueChain } from '../api/queries';
import { Empty, Page, PillarDot } from '../components/primitives';
import { go, openPeek } from '../lib/events';
import { heatBg } from '../lib/helpers';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

// Radial view — wedge radius ∝ subcap count, fed by the live clusters.
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
              <text
                x={lx}
                y={ly}
                fontSize="8.5"
                fontWeight="700"
                fill="var(--text-tertiary)"
                textAnchor="middle"
                dominantBaseline="middle"
              >
                {s.name.length > 16 ? s.name.slice(0, 15) + '…' : s.name}
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

const PILLARS = ['all', 'P1', 'P2', 'P3', 'P4'];
const PILLAR_LABEL: Record<string, string> = {
  P1: 'P1 · Strategy, governance & culture',
  P2: 'P2 · Customer experience & engagement',
  P3: 'P3 · Process automation & operations',
  P4: 'P4 · Data & AI enablement',
};

// The real VC mapping has no finer stage split (a cluster IS a stage), so the drilldown groups
// the stage's subcaps by pillar — with the member ids carried so filtering stays exact.
function groupByPillar(c: ValueChainCluster): { name: string; count: number; ids?: Set<string> }[] {
  const by = new Map<string, Set<string>>();
  for (const s of c.subcaps) {
    const k = s.pillar ?? s.id.slice(0, 2);
    if (!by.has(k)) by.set(k, new Set());
    by.get(k)!.add(s.id);
  }
  return [...by.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([pl, ids]) => ({ name: PILLAR_LABEL[pl] ?? pl, count: ids.size, ids }));
}

export function ValueChain() {
  const ui = useUi();
  const version = ui.version;
  const [pillar, setPillar] = useState('all');
  const [radial, setRadial] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  const res = useValueChain(version, pillar, ui.sv);
  const data = res.data;
  const clusters = data?.clusters ?? [];
  useEffect(() => setOpen(clusters[0]?.code ?? null), [version, pillar, ui.sv]); // eslint-disable-line react-hooks/exhaustive-deps

  const current = clusters.find((c) => c.code === open) ?? null;

  return (
    <Page
      eyebrow="A · Explore"
      title="Value chain atlas"
      intro={
        data?.source === 'catalogue_vc_mapping'
          ? 'The catalogue\'s own value chain — real, named stages per subvertical from the v7 VC-mapping sheet (cascaded to versions without their own, e.g. v5). Pick a subvertical in the header to see that industry\'s chain in order.'
          : 'Value-chain segments derived live from this catalogue version\'s own capability structure — used only when a version ships no VC mapping of its own.'
      }
      actions={
        <button
          className={'btn sm ' + (radial ? 'primary' : 'ghost')}
          onClick={() => setRadial((r) => !r)}
        >
          <Icon n="route" s={13} /> {radial ? 'Grid' : 'Radial'}
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
        {data && (
          <span className="muted" style={{ fontSize: 12 }}>
            {clusters.length} value-chain segments · {data.total_subcaps} subcaps
            {data.deduped > 0 && (
              <span className="chip teal" style={{ marginLeft: 8, fontSize: 10 }}>
                {data.deduped} duplicate/similar merged
              </span>
            )}
          </span>
        )}
      </div>

      {clusters.length === 0 ? (
        <Empty
          icon="route"
          title="No value chain yet"
          desc="Provision a catalogue version (upload its workbooks) and the value-chain segments derive automatically from its categories."
        />
      ) : radial ? (
        <RadialWheel segs={clusters} />
      ) : (
        <>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
              gap: 8,
              marginBottom: 16,
            }}
          >
            {clusters.map((c) => {
              const on = c.code === open;
              return (
                <div
                  key={c.code}
                  onClick={() => setOpen(c.code)}
                  className="card hov"
                  style={{
                    padding: '11px 12px 13px',
                    cursor: 'pointer',
                    borderColor: on ? 'var(--border-strong)' : 'var(--border-subtle)',
                    background: on ? 'var(--surface-overlay)' : 'var(--surface-base)',
                  }}
                >
                  <div className="row gap6" style={{ marginBottom: 5 }}>
                    <span className="mono" style={{ fontSize: 9.5, color: 'var(--z-slate)', fontWeight: 700 }}>
                      {c.code}
                    </span>
                    {c.pillar && <PillarDot p={c.pillar} s={7} />}
                  </div>
                  <div style={{ fontSize: 12.5, fontWeight: 600, minHeight: 32, lineHeight: 1.2 }}>
                    {c.name}
                  </div>
                  <div className="num" style={{ fontSize: 21, fontWeight: 700, color: 'var(--interactive)' }}>
                    {c.count}
                  </div>
                  <div className="muted" style={{ fontSize: 10 }}>
                    subcaps{c.merged_from.length ? ` · ${c.merged_from.length} merged` : ''}
                  </div>
                </div>
              );
            })}
          </div>

          {current && (
            <div className="card pad fade-in">
              <div className="between" style={{ marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
                <div className="row gap8">
                  <span className="chip soft mono">{current.code}</span>
                  <b style={{ fontSize: 15 }}>{current.name}</b>
                  {current.pillar && <span className="chip soft">{current.pillar}</span>}
                  <span className="muted" style={{ fontSize: 12 }}>{current.count} subcaps</span>
                </div>
              </div>
              {current.merged_from.length > 0 && (
                <div className="banner info" style={{ marginBottom: 12 }}>
                  <Icon n="branch" s={13} />
                  Merged duplicate/similar segments into this one:{' '}
                  {current.merged_from.join(' · ')}
                </div>
              )}
              <div style={{ display: 'grid', gap: 10 }}>
                {(
                  (current.stages as { name: string; count: number; ids?: Set<string> }[] | undefined) ??
                  groupByPillar(current)
                ).map((st) => (
                  <div key={st.name}>
                    <div className="row gap8" style={{ marginBottom: 6 }}>
                      <span className="eyebrow" style={{ margin: 0 }}>
                        {st.name}
                      </span>
                      <span className="muted" style={{ fontSize: 11 }}>
                        {st.count}
                      </span>
                    </div>
                    <div className="row wrap gap6">
                      {current.subcaps
                        .filter((s) => (st.ids ? st.ids.has(s.id) : s.stage === st.name))
                        .map((s) => (
                          <span
                            key={s.id}
                            className="chip soft mono"
                            style={{ cursor: 'pointer', fontSize: 10.5 }}
                            title={s.name}
                            onClick={() => openPeek(s.id)}
                            onDoubleClick={() => go('subcap/' + s.id)}
                          >
                            {s.id}
                          </span>
                        ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </Page>
  );
}
