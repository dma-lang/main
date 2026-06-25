// Value chain atlas (A3) — the catalogue's REAL value chain. Three views over the same delivery
// truth: PIPELINE (the ordered per-SV stages, heat by delivered Jira stories), RADIAL (the same
// stages as a wheel sized by delivery), and ROLLUP (the 8 canonical MECE stages — Acquire & onboard
// … Govern & enable — each with stories, projects, a pillar mix and the top delivered subcaps).
// Stages come from cat_<v>.subcap_vcc (cascaded v7→v5); story/project counts are the real Jira corpus
// for the active version (story_catalogue_link, Jira-only). Click a stage to drill its top subcaps.
import { useEffect, useState } from 'react';

import type {
  ValueChainCluster,
  ValueChainGroup,
  ValueChainStageRollup,
  VcPillarTally,
} from '../api/client';
import { useValueChain } from '../api/queries';
import { Dropdown, Empty, Page, PillarDot, Seg } from '../components/primitives';
import { go, openPeek } from '../lib/events';
import { heatBg } from '../lib/helpers';
import { Icon } from '../lib/icons';
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

const stagesOf = (c: ValueChainCluster) => c.stories ?? 0;

// P1–P4 subcap tally as inline pills — used on a stage drilldown and a rollup detail card.
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

// Radial view — wedge radius ∝ delivered stories (falls back to subcap count when a version carries
// no story link yet), in chain order.
function RadialWheel({ segs }: { segs: ValueChainCluster[] }) {
  const cx = 200;
  const cy = 200;
  const hasStories = segs.some((s) => stagesOf(s) > 0);
  const metric = (s: ValueChainCluster) => (hasStories ? stagesOf(s) : s.count);
  const max = Math.max(1, ...segs.map(metric));
  const total = segs.reduce((a, s) => a + metric(s), 0);
  return (
    <div className="card pad" style={{ display: 'flex', justifyContent: 'center' }}>
      <svg width="100%" height={400} viewBox="0 0 400 400" style={{ maxWidth: 440 }}>
        {segs.map((s, i) => {
          const a0 = (i / segs.length) * 2 * Math.PI - Math.PI / 2;
          const a1 = ((i + 1) / segs.length) * 2 * Math.PI - Math.PI / 2;
          const rr = 60 + (metric(s) / max) * 90;
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
                fill={heatBg(metric(s) / max)}
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
          {total.toLocaleString()}
        </text>
        <text x={cx} y={cy + 12} fontSize="9" fill="var(--text-tertiary)" textAnchor="middle">
          {hasStories ? 'stories delivered' : 'subcaps mapped'}
        </text>
      </svg>
    </div>
  );
}

// One subvertical's ordered pipeline + its inline stage drilldown. Self-contained so the 'All SV'
// view can stack one section per subvertical, each with its own open stage.
function ChainSection({
  chain,
  showHeader,
}: {
  chain: ValueChainGroup;
  showHeader: boolean;
}) {
  const clusters = chain.clusters;
  const [open, setOpen] = useState<string | null>(clusters[0]?.code ?? null);
  // re-focus the first stage when the underlying chain changes (version / pillar / sv switch)
  useEffect(() => setOpen(clusters[0]?.code ?? null), [chain.sv, clusters.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const current = clusters.find((c) => c.code === open) ?? clusters[0] ?? null;
  const maxStories = Math.max(1, ...clusters.map(stagesOf));
  // top delivered subcaps for the open stage — prefer the story-ranked top, fall back to members
  const drill =
    current?.top && current.top.length
      ? current.top
      : (current?.subcaps ?? []).map((s) => ({ id: s.id, name: s.name, n: 0, pillar: s.pillar }));

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
      {/* the ORDERED pipeline — left-to-right, stage NAME headline, DELIVERY (stories) the metric */}
      <div className="card pad" style={{ marginBottom: 12, overflowX: 'auto' }}>
        <div className="row" style={{ gap: 0, alignItems: 'stretch', minWidth: 'min-content' }}>
          {clusters.map((c, i) => {
            const on = c.code === open;
            const ratio = stagesOf(c) / maxStories;
            return (
              <div key={c.code} className="row" style={{ gap: 0, alignItems: 'center' }}>
                <button
                  onClick={() => setOpen(c.code)}
                  className="card hov"
                  style={{
                    width: 150,
                    minHeight: 104,
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
                    {stagesOf(c).toLocaleString()}
                    <span className="muted" style={{ fontSize: 9.5, fontWeight: 400 }}> stories</span>
                  </div>
                  <div className="muted num" style={{ fontSize: 10 }}>{c.count} subcaps</div>
                  {/* delivery heat strip */}
                  <div style={{ height: 4, borderRadius: 3, marginTop: 6, background: heatBg(0.15 + ratio * 0.85) }} />
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
                {stagesOf(current).toLocaleString()} stories · {current.count} subcaps
              </span>
            </div>
            <PillarMix pillars={current.pillars} />
          </div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Top delivered subcaps — click to peek, double-click to open the deep dive
          </div>
          <div className="row wrap gap6">
            {drill.map((s) => (
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
                {s.n > 0 && <b className="num" style={{ color: 'var(--interactive)' }}>{s.n}</b>}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// Rollup view — the 8 canonical MECE stages as a delivery column chart + a selected-stage detail.
function OverviewRollup({ rollup, hasDates }: { rollup: ValueChainStageRollup[]; hasDates: boolean }) {
  const [sel, setSel] = useState<string>(rollup[0]?.code ?? '');
  const cur = rollup.find((s) => s.code === sel) ?? rollup[0] ?? null;
  const max = Math.max(1, ...rollup.map((s) => s.stories));
  const qmax = cur ? Math.max(1, ...cur.quarters) : 1;
  const perSub = cur && cur.subcaps ? Math.round(cur.stories / cur.subcaps) : 0;

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

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: 12,
              marginBottom: 16,
            }}
          >
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

          {hasDates && cur.quarters.some((q) => q > 0) && (
            <div style={{ marginTop: 16 }}>
              <div className="eyebrow" style={{ marginBottom: 8 }}>Delivery trend</div>
              <div className="row" style={{ gap: 6, alignItems: 'flex-end', height: 56 }}>
                {cur.quarters.map((q, i) => (
                  <div
                    key={i}
                    title={`${q} stories`}
                    style={{
                      flex: '1 1 0',
                      height: Math.max(2, Math.round((q / qmax) * 52)),
                      borderRadius: 3,
                      background: 'var(--interactive)',
                      opacity: 0.45 + 0.55 * (i / Math.max(1, cur.quarters.length - 1)),
                    }}
                  />
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
  // prefer the per-subvertical chains; fall back to wrapping the flat clusters (derived path)
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
          <OverviewRollup rollup={rollup} hasDates={!!data?.rollup_has_dates} />
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
        chains.map((ch) => (
          <div key={ch.sv} style={{ marginBottom: multi ? 22 : 0 }}>
            {multi && (
              <div className="row gap8" style={{ marginBottom: 8, alignItems: 'baseline' }}>
                <Icon n="route" s={13} cls="" style={{ color: 'var(--interactive)' }} />
                <b style={{ fontSize: 14 }}>{SV_NAME[ch.sv] ?? ch.sv} value chain</b>
              </div>
            )}
            <RadialWheel segs={ch.clusters} />
          </div>
        ))
      ) : (
        chains.map((ch) => <ChainSection key={ch.sv} chain={ch} showHeader={multi} />)
      )}
    </Page>
  );
}
