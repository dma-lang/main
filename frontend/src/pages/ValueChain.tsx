// Value chain atlas (A3) — the catalogue's REAL value chain. Three views over the same delivery
// truth: PIPELINE (the ordered per-SV stages: icon + STAGE n, subcaps & delivered Jira stories,
// heat by delivery, with a per-stage drilldown), RADIAL (the top stages as an annular wheel sized
// by delivery, angle ∝ stories, with a legend), and ROLLUP (the 8 canonical MECE stages). Stages
// come from cat_<v>.subcap_vcc (cascaded v7→v5); story counts are the real Jira corpus for the
// active version (story_catalogue_link, Jira-only). Click a stage to drill its top subcaps.
import { useEffect, useMemo, useState } from 'react';

import type {
  ValueChainCluster,
  ValueChainGroup,
  ValueChainStageRollup,
  VcPillarTally,
} from '../api/client';
import { useValueChain } from '../api/queries';
import { Dropdown, Empty, Page, PillarDot, Seg } from '../components/primitives';
import { go, openPeek } from '../lib/events';
import { heatBg, PILLAR_COLORS } from '../lib/helpers';
import { Icon, type IconName } from '../lib/icons';
import { type Pillar, useUi } from '../state/store';

const PILLARS: Pillar[] = ['all', 'P1', 'P2', 'P3', 'P4'];

type View = 'chain' | 'radial' | 'rollup';

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

// the prototype's 12-colour wheel palette + the keyword→icon map for a stage (verbatim).
const PALETTE = [
  '#185f60', '#27bbaf', '#3d81f6', '#62d7b8', '#8094c0', '#fe9732',
  '#1c4a4d', '#139f94', '#5a6ea3', '#27bbaf', '#b5650f', '#0c7d72',
];
function stageIcon(s: string): IconName {
  const u = (s || '').toUpperCase();
  if (/MARKET|PROSPECT|ACQUI|LEAD/.test(u)) return 'trend';
  if (/KYC|ONBOARD|ACCOUNT|APPLICATION/.test(u)) return 'upload';
  if (/ORIGINAT|UNDERWRIT|QUOTE|FUND|CREDIT/.test(u)) return 'file';
  if (/SERVIC|ENGAGE|RELATIONSHIP|COVERAGE|ADVIC|CARE/.test(u)) return 'chat';
  if (/CROSS-SELL|WALLET|LOYALTY|RETENTION|RENEWAL|GROW/.test(u)) return 'sparkles';
  if (/RISK|COMPLIANCE|SURVEILL|FRAUD/.test(u)) return 'shield';
  if (/ANALYT|PORTFOLIO|PERFORMANCE|REPORT/.test(u)) return 'bars';
  if (/BACK OFFICE|OPS|RECON/.test(u)) return 'gear';
  if (/PLATFORM|TECHNOLOGY|DATA|GOVERN/.test(u)) return 'database';
  return 'route';
}
const svLabelOf = (sv: string) => (sv === 'all' ? 'All subverticals' : (SV_NAME[sv] ?? sv));
const storiesOf = (c: ValueChainCluster) => c.stories ?? 0;

// P1–P4 subcap tally as inline pills — used on a rollup detail card.
function PillarMix({ pillars }: { pillars?: VcPillarTally }) {
  if (!pillars) return null;
  const items: [string, number][] = [
    ['P1', pillars.P1],
    ['P2', pillars.P2],
    ['P3', pillars.P3],
    ['P4', pillars.P4],
  ];
  const shown = items.filter(([, n]) => n > 0);
  if (!shown.length) return null;
  return (
    <div className="row gap12" style={{ flexWrap: 'wrap' }}>
      {shown.map(([p, n]) => (
        <span key={p} className="row gap6" style={{ fontSize: 11.5 }}>
          <PillarDot p={p} s={7} />
          <span className="muted">{p}</span>
          <b className="num">{n}</b>
        </span>
      ))}
    </div>
  );
}

// Radial view — an ANNULAR wheel of the top 12 stages by delivery: segment ANGLE ∝ stories (not a
// radial bar chart), a numbered legend, and a centre showing the total subcap placements + stage
// count. Matches the prototype VCRadial.
function RadialWheel({ segs: allSegs, svLabel }: { segs: ValueChainCluster[]; svLabel: string }) {
  const cx = 170;
  const cy = 170;
  const inner = 62;
  const outer = 150;
  const segs = useMemo(
    () => [...allSegs].sort((a, b) => storiesOf(b) - storiesOf(a)).slice(0, 12),
    [allSegs],
  );
  const more = allSegs.length - segs.length;
  const totalSubs = allSegs.reduce((a, s) => a + (s.count ?? 0), 0);
  const totalStories = allSegs.reduce((a, s) => a + storiesOf(s), 0);
  const [sel, setSel] = useState<string>(segs[0]?.code ?? '');
  useEffect(() => setSel(segs[0]?.code ?? ''), [segs]);

  const arc = (a0: number, a1: number, r0: number, r1: number) => {
    const x0 = cx + Math.cos(a0) * r0;
    const y0 = cy + Math.sin(a0) * r0;
    const x1 = cx + Math.cos(a1) * r0;
    const y1 = cy + Math.sin(a1) * r0;
    const x2 = cx + Math.cos(a1) * r1;
    const y2 = cy + Math.sin(a1) * r1;
    const x3 = cx + Math.cos(a0) * r1;
    const y3 = cy + Math.sin(a0) * r1;
    const big = a1 - a0 > Math.PI ? 1 : 0;
    return `M${x0} ${y0} A${r0} ${r0} 0 ${big} 1 ${x1} ${y1} L${x2} ${y2} A${r1} ${r1} 0 ${big} 0 ${x3} ${y3} Z`;
  };
  const cap = (s: string) => (s.length > 30 ? s.slice(0, 29) + '…' : s);

  const tot = segs.reduce((a, s) => a + storiesOf(s), 0) || 1;
  let acc = -Math.PI / 2;
  const arcs = segs.map((s, i) => {
    const frac = storiesOf(s) / tot;
    const a0 = acc;
    const a1 = acc + frac * 2 * Math.PI;
    acc = a1;
    return { s, i, a0, a1, frac };
  });

  return (
    <div className="card pad" style={{ marginBottom: 16 }}>
      <div className="between" style={{ marginBottom: 6 }}>
        <div className="h3">{svLabel} value chain · radial</div>
        <span className="chip soft">
          {allSegs.length} stages · {totalStories.toLocaleString()} stories
        </span>
      </div>
      <div className="muted" style={{ fontSize: 12, marginBottom: 14 }}>
        Ring shows the top {segs.length} stages by delivery{more > 0 ? ` (of ${allSegs.length})` : ''};
        segment angle = stories. Click a segment or a legend row to drill in.
      </div>
      <div style={{ display: 'flex', gap: 28, alignItems: 'center', flexWrap: 'wrap' }}>
        <svg width={340} height={340} viewBox="0 0 340 340" style={{ flex: 'none' }}>
          {arcs.map(({ s, i, a0, a1, frac }) => {
            const on = sel === s.code;
            const mid = (a0 + a1) / 2;
            const lr = (inner + outer) / 2;
            const lx = cx + Math.cos(mid) * lr;
            const ly = cy + Math.sin(mid) * lr;
            return (
              <g key={s.code} style={{ cursor: 'pointer' }} onClick={() => setSel(s.code)}>
                <path
                  d={arc(a0 + 0.008, a1 - 0.008, inner, on ? outer + 8 : outer)}
                  fill={PALETTE[i % PALETTE.length]}
                  opacity={on ? 1 : 0.88}
                  stroke="var(--surface-base)"
                  strokeWidth="2"
                />
                {frac > 0.06 && (
                  <text x={lx} y={ly} fontSize="11" fontWeight="700" fill="#fff" textAnchor="middle" dominantBaseline="middle">
                    {i + 1}
                  </text>
                )}
              </g>
            );
          })}
          <circle cx={cx} cy={cy} r={inner} fill="var(--surface-base)" stroke="var(--border-subtle)" />
          <text x={cx} y={cy - 10} fontSize="26" fontWeight="700" fill="var(--text-primary)" textAnchor="middle">
            {totalSubs}
          </text>
          <text x={cx} y={cy + 8} fontSize="9" fill="var(--text-tertiary)" textAnchor="middle">
            subcap placements
          </text>
          <text x={cx} y={cy + 24} fontSize="10" fontWeight="600" fill="var(--interactive)" textAnchor="middle">
            {allSegs.length} stages
          </text>
        </svg>
        <div style={{ flex: 1, minWidth: 260, display: 'grid', gap: 4, maxHeight: 300, overflowY: 'auto' }}>
          {segs.map((s, i) => {
            const on = sel === s.code;
            return (
              <div
                key={s.code}
                onClick={() => setSel(s.code)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '7px 10px',
                  borderRadius: 7,
                  cursor: 'pointer',
                  background: on ? 'var(--surface-overlay)' : 'transparent',
                  border: '1px solid ' + (on ? 'var(--border-medium)' : 'transparent'),
                }}
              >
                <span
                  style={{
                    width: 18,
                    height: 18,
                    borderRadius: 5,
                    background: PALETTE[i % PALETTE.length],
                    color: '#fff',
                    fontSize: 10,
                    fontWeight: 700,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flex: 'none',
                  }}
                >
                  {i + 1}
                </span>
                <span
                  style={{ flex: 1, minWidth: 0, fontSize: 12, fontWeight: on ? 700 : 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  title={s.name}
                >
                  {cap(s.name)}
                </span>
                <span className="num muted" style={{ fontSize: 11, flex: 'none' }}>
                  {s.count} subcaps
                </span>
                <span className="num" style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--interactive)', flex: 'none', minWidth: 46, textAlign: 'right' }}>
                  {storiesOf(s).toLocaleString()}
                </span>
              </div>
            );
          })}
          {more > 0 && (
            <div className="muted" style={{ fontSize: 11, padding: '6px 10px' }}>
              +{more} more stages — switch to Pipeline view to see all.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// One subvertical's ordered pipeline + its inline stage drilldown (icon badge + STAGE n cards,
// subcaps & stories dual metrics, delivery heat as a top border, chevrons between; the drilldown
// shows the pillar mix as bars and the top delivered subcaps as a 2-column card grid).
function ChainSection({ chain }: { chain: ValueChainGroup }) {
  const clusters = chain.clusters;
  const svLabel = svLabelOf(chain.sv);
  const [open, setOpen] = useState<string | null>(clusters[0]?.code ?? null);
  useEffect(() => setOpen(clusters[0]?.code ?? null), [chain.sv, clusters.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const current = clusters.find((c) => c.code === open) ?? clusters[0] ?? null;
  const maxStories = Math.max(1, ...clusters.map(storiesOf));
  const totalSubs = clusters.reduce((a, c) => a + (c.count ?? 0), 0);
  const drill =
    current?.top && current.top.length
      ? current.top
      : (current?.subcaps ?? []).map((s) => ({ id: s.id, name: s.name, n: 0, pillar: s.pillar }));

  return (
    <div style={{ marginBottom: 16 }}>
      <div className="card pad" style={{ marginBottom: 16, overflowX: 'auto' }}>
        <div className="between" style={{ marginBottom: 14 }}>
          <div className="h3">
            {svLabel} value chain · {clusters.length} stages
          </div>
          <span className="chip soft">
            <Icon n="route" s={12} /> {totalSubs} subcaps · complete
          </span>
        </div>
        <div style={{ display: 'flex', gap: 0, minWidth: 'min-content' }}>
          {clusters.map((c, i) => {
            const on = c.code === open;
            const ratio = storiesOf(c) / maxStories;
            return (
              <div
                key={c.code}
                style={{ flex: '1 1 0', minWidth: 150, position: 'relative', paddingRight: i < clusters.length - 1 ? 20 : 0 }}
              >
                <div
                  onClick={() => setOpen(c.code)}
                  className="card hov"
                  style={{
                    padding: '13px 14px',
                    cursor: 'pointer',
                    height: '100%',
                    borderColor: on ? 'var(--border-strong)' : 'var(--border-subtle)',
                    background: on ? 'var(--surface-overlay)' : 'var(--surface-base)',
                    borderTop: '3px solid ' + heatBg(0.35 + ratio * 0.65),
                  }}
                >
                  <div className="row gap8" style={{ marginBottom: 8 }}>
                    <div
                      style={{
                        width: 30,
                        height: 30,
                        borderRadius: 8,
                        background: 'var(--surface-overlay)',
                        color: 'var(--interactive)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flex: 'none',
                      }}
                    >
                      <Icon n={stageIcon(c.name)} s={15} />
                    </div>
                    <span className="mono" style={{ fontSize: 9, color: 'var(--z-slate)', fontWeight: 700 }}>
                      STAGE {i + 1}
                    </span>
                  </div>
                  <div className="h3" style={{ fontSize: 11.5, lineHeight: 1.25, minHeight: 42, textTransform: 'none' }}>
                    {c.name}
                  </div>
                  <div className="row gap12" style={{ marginTop: 8 }}>
                    <div>
                      <div className="num" style={{ fontSize: 17, fontWeight: 700, color: 'var(--interactive)' }}>
                        {c.count}
                      </div>
                      <div className="muted" style={{ fontSize: 9 }}>
                        subcaps
                      </div>
                    </div>
                    <div>
                      <div className="num" style={{ fontSize: 17, fontWeight: 700 }}>
                        {storiesOf(c).toLocaleString()}
                      </div>
                      <div className="muted" style={{ fontSize: 9 }}>
                        stories
                      </div>
                    </div>
                  </div>
                </div>
                {i < clusters.length - 1 && (
                  <div style={{ position: 'absolute', right: 4, top: '42%', color: 'var(--text-disabled)', zIndex: 1 }}>
                    <Icon n="chevR" s={16} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {current && (
        <div className="card pad fade-in">
          <div className="between" style={{ marginBottom: 4 }}>
            <div className="row gap10">
              <div
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: 9,
                  background: 'var(--surface-overlay)',
                  color: 'var(--interactive)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Icon n={stageIcon(current.name)} s={17} />
              </div>
              <div>
                <div className="h2" style={{ fontSize: 16 }}>
                  {current.name}
                </div>
                <div className="muted" style={{ fontSize: 11 }}>
                  {svLabel} · value-chain stage
                </div>
              </div>
            </div>
            <span className="chip soft">
              {current.count} subcaps · {storiesOf(current).toLocaleString()} stories
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 20, marginTop: 14, alignItems: 'start' }}>
            <div>
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                Pillar mix
              </div>
              {(['P1', 'P2', 'P3', 'P4'] as const).map((pk) => {
                const v = current.pillars?.[pk] ?? 0;
                const mx = Math.max(
                  1,
                  current.pillars?.P1 ?? 0,
                  current.pillars?.P2 ?? 0,
                  current.pillars?.P3 ?? 0,
                  current.pillars?.P4 ?? 0,
                );
                return v ? (
                  <div key={pk} className="row gap8" style={{ marginBottom: 6 }}>
                    <span className="row gap6" style={{ minWidth: 96 }}>
                      <PillarDot p={pk} s={7} />
                      <span className="muted" style={{ fontSize: 11 }}>
                        {pk}
                      </span>
                    </span>
                    <div style={{ flex: 1 }}>
                      <div className="bartrack">
                        <div className="barfill" style={{ width: `${(v / mx) * 100}%`, background: PILLAR_COLORS[pk] }} />
                      </div>
                    </div>
                    <b className="num" style={{ fontSize: 11 }}>
                      {v}
                    </b>
                  </div>
                ) : null;
              })}
              <div className="card" style={{ padding: '10px 12px', background: 'var(--surface-overlay)', marginTop: 16 }}>
                <div className="muted" style={{ fontSize: 11, lineHeight: 1.5 }}>
                  Stage name is verbatim from the v7 <span className="mono">21_VC_Mapping_PerSubcap</span> mapping
                  {chain.sv !== 'all' ? ` for ${svLabel}` : ''}.
                </div>
              </div>
            </div>
            <div>
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                Subcaps at this stage · top by delivery
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                {drill.map((s) => (
                  <div
                    key={s.id}
                    className="card hov"
                    style={{ padding: '9px 11px', cursor: 'pointer' }}
                    onClick={() => openPeek(s.id)}
                    onDoubleClick={() => go('subcap/' + s.id)}
                  >
                    <div className="row gap6" style={{ marginBottom: 4 }}>
                      {s.pillar && <PillarDot p={s.pillar} s={6} />}
                      <span className="mono sclink" style={{ fontSize: 10 }}>
                        {s.id}
                      </span>
                      <b className="num" style={{ fontSize: 10.5, marginLeft: 'auto', color: 'var(--interactive)' }}>
                        {s.n}
                      </b>
                    </div>
                    <div style={{ fontSize: 11.5, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {s.name}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Rollup view — the 8 canonical MECE stages as a delivery column chart + a selected-stage detail.
const CONF_BANDS: [keyof ValueChainStageRollup['confidence'], string][] = [
  ['HIGH', 'var(--state-success-text)'],
  ['MEDIUM', 'var(--z-slate)'],
  ['LOW', 'var(--state-warn-text)'],
];

function OverviewRollup({ rollup }: { rollup: ValueChainStageRollup[] }) {
  const [sel, setSel] = useState<string>(rollup[0]?.code ?? '');
  const cur = rollup.find((s) => s.code === sel) ?? rollup[0] ?? null;
  const max = Math.max(1, ...rollup.map((s) => s.stories));
  const perSub = cur && cur.subcaps ? Math.round(cur.stories / cur.subcaps) : 0;
  const conf = cur?.confidence ?? { HIGH: 0, MEDIUM: 0, LOW: 0 };
  const confTotal = conf.HIGH + conf.MEDIUM + conf.LOW;

  return (
    <>
      <div className="card pad" style={{ marginBottom: 16, overflowX: 'auto' }}>
        <div className="between" style={{ marginBottom: 14 }}>
          <div className="h3">Canonical value chain · 8 stages</div>
          <span className="muted" style={{ fontSize: 12 }}>bar height ∝ delivered stories · click a stage</span>
        </div>
        <div className="row" style={{ gap: 8, alignItems: 'flex-end', minWidth: 'min-content' }}>
          {rollup.map((s) => {
            const on = cur?.code === s.code;
            const ratio = s.stories / max;
            return (
              <button
                key={s.code}
                onClick={() => setSel(s.code)}
                className="card hov"
                title={`${s.name} · ${s.stories.toLocaleString()} stories · ${s.projects} projects`}
                style={{
                  flex: '1 1 0',
                  minWidth: 100,
                  padding: '10px 8px',
                  cursor: 'pointer',
                  textAlign: 'center',
                  borderColor: on ? 'var(--interactive)' : 'var(--border-subtle)',
                  background: on ? 'var(--surface-overlay)' : 'var(--surface-base)',
                }}
              >
                <div className="num" style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--interactive)' }}>{s.code}</div>
                <div style={{ fontSize: 11, fontWeight: 600, lineHeight: 1.2, minHeight: 40, margin: '4px 0' }}>{s.name}</div>
                <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'center', height: 60 }}>
                  <div
                    style={{
                      width: 28,
                      height: Math.max(3, Math.round(ratio * 60)),
                      borderRadius: 3,
                      background: on ? 'var(--interactive)' : heatBg(0.25 + ratio * 0.75),
                    }}
                  />
                </div>
                <div className="num" style={{ fontSize: 16, fontWeight: 700, marginTop: 6 }}>
                  {s.subcaps}
                  <span className="muted" style={{ fontSize: 9, fontWeight: 400 }}> subcaps</span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {cur && (
        <div className="card pad fade-in">
          <div className="row gap8" style={{ marginBottom: 4, alignItems: 'baseline' }}>
            <b style={{ fontSize: 16 }}>{cur.name}</b>
            <span className="muted num" style={{ fontSize: 11.5 }}>{cur.code}</span>
          </div>
          {cur.blurb && <div className="muted" style={{ fontSize: 12.5, marginBottom: 14 }}>{cur.blurb}</div>}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
            {[
              ['subcaps', cur.subcaps.toLocaleString()],
              ['stories', cur.stories.toLocaleString()],
              ['projects', cur.projects.toLocaleString()],
              ['stories / subcap', perSub.toLocaleString()],
            ].map(([label, val]) => (
              <div key={label} className="card" style={{ padding: '12px 14px' }}>
                <div className="num" style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-primary)' }}>{val}</div>
                <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>{label}</div>
              </div>
            ))}
          </div>

          <div className="between" style={{ marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
            <div className="eyebrow">Top delivered subcaps</div>
            <PillarMix pillars={cur.pillars} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
            {cur.top.map((s) => (
              <button
                key={s.id}
                className="card hov"
                onClick={() => openPeek(s.id)}
                style={{ padding: '9px 12px', cursor: 'pointer', textAlign: 'left' }}
              >
                <div className="row gap6" style={{ marginBottom: 3 }}>
                  {s.pillar && <PillarDot p={s.pillar} s={6} />}
                  <span style={{ fontSize: 12, fontWeight: 600 }}>{s.name}</span>
                </div>
                <div className="between">
                  <span className="muted num" style={{ fontSize: 10.5 }}>{s.id}</span>
                  <span className="num" style={{ fontSize: 12, fontWeight: 700, color: 'var(--interactive)' }}>
                    {s.n.toLocaleString()}
                    <span className="muted" style={{ fontSize: 9, fontWeight: 400 }}> stories</span>
                  </span>
                </div>
              </button>
            ))}
          </div>

          {confTotal > 0 && (
            <div style={{ marginTop: 16 }}>
              <div className="eyebrow" style={{ marginBottom: 8 }}>Delivery confidence</div>
              <div className="row" style={{ height: 12, borderRadius: 6, overflow: 'hidden', gap: 0 }}>
                {CONF_BANDS.map(([label, color]) =>
                  conf[label] > 0 ? (
                    <div
                      key={label}
                      title={`${label}: ${conf[label].toLocaleString()} stories`}
                      style={{ width: `${(conf[label] / confTotal) * 100}%`, background: color }}
                    />
                  ) : null,
                )}
              </div>
              <div className="row gap12" style={{ marginTop: 8, flexWrap: 'wrap' }}>
                {CONF_BANDS.map(([label, color]) => (
                  <span key={label} className="row gap6" style={{ fontSize: 11 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
                    <span className="muted">{label}</span>
                    <b className="num">{conf[label].toLocaleString()}</b>
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}

export function ValueChain() {
  const ui = useUi();
  const version = ui.version;
  const pillar = ui.pillar; // header-linked
  const setPillar = ui.setPillar;
  const [view, setView] = useState<View>('chain');

  const res = useValueChain(version, pillar, ui.sv);
  const data = res.data;
  const chains: ValueChainGroup[] =
    data?.chains && data.chains.length > 0
      ? data.chains
      : data && data.clusters.length > 0
        ? [{ sv: data.resolved_sv || ui.sv || 'all', clusters: data.clusters, total_subcaps: data.total_subcaps }]
        : [];
  const multi = chains.length > 1;
  const rollup = data?.rollup ?? [];

  return (
    <Page
      eyebrow="A · Explore"
      title="Value chain atlas"
      intro="The catalogue's value chain — the real, named stages, ranked by the Jira stories that deliver them. Pipeline and Radial show the ordered per-subvertical chain; Rollup consolidates everything into the 8 canonical stages (Acquire & onboard … Govern & enable). 'All SV' merges every subvertical; pinning one shows just its own (a version without its own mapping inherits the reference's)."
      actions={
        <div className="row gap8">
          {(data?.subverticals?.length ?? 0) > 0 && (
            <Dropdown
              label="All SV"
              value={ui.sv}
              icon="building"
              options={[
                { v: 'all', l: 'All SV — consolidated' },
                ...(data?.subverticals ?? []).map((c) => ({ v: c, l: SV_NAME[c] ?? c })),
              ]}
              onChange={ui.setSv}
            />
          )}
          <Seg
            options={[
              { v: 'chain', l: 'Pipeline' },
              { v: 'radial', l: 'Radial' },
              { v: 'rollup', l: 'Rollup' },
            ]}
            value={view}
            onChange={(v) => setView(v as View)}
          />
        </div>
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

      {view === 'rollup' ? (
        rollup.length > 0 ? (
          <OverviewRollup rollup={rollup} />
        ) : (
          <Empty
            icon="route"
            title="No rollup for this view"
            desc="The 8-stage rollup needs the catalogue's value-chain mapping. Pick a provisioned version (or 'All SV') to see it."
          />
        )
      ) : chains.length === 0 ? (
        <Empty
          icon="route"
          title="No value chain yet"
          desc="Provision a catalogue version (upload its workbooks) and its value-chain stages appear here, in order, per subvertical."
        />
      ) : view === 'radial' ? (
        chains.map((ch) => <RadialWheel key={ch.sv} segs={ch.clusters} svLabel={svLabelOf(ch.sv)} />)
      ) : (
        chains.map((ch) => <ChainSection key={ch.sv} chain={ch} />)
      )}
    </Page>
  );
}
