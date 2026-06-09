// Subcap deep dive (A2) — the prototype's Workbench detail at /subcap/:id: a sticky catalogue tree
// (search + pillar pills + collapsible category -> cluster -> subcap) beside a detail panel (hero +
// completeness ring + stat buttons + five tabs). Wired to GET /api/catalogue/{v}/subcaps (tree) and
// /subcaps/{id} (detail). Overview renders live data; Maturity / Use cases / Delivery / Connections
// are designed-empty states until their foundations (enrichment, F5 carry-forward, KG) seed them.
import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';

import type { SubcapDetail, SubcapNode } from '../api/client';
import { useSubcap, useSubcaps } from '../api/queries';
import { Empty, LifeChip, PillarDot, Tier } from '../components/primitives';
import { go, toast } from '../lib/events';
import { clamp, LIFE_COLORS, PILLAR_COLORS, PILLAR_SHORT } from '../lib/helpers';
import { Icon, type IconName } from '../lib/icons';
import { useUi } from '../state/store';

const PILLARS = ['P1', 'P2', 'P3', 'P4'];
const TABS: [string, string][] = [
  ['overview', 'Overview'],
  ['maturity', 'Maturity'],
  ['usecases', 'Use cases'],
  ['delivery', 'Delivery'],
  ['connections', 'Connections'],
];

function Ring({ v, max = 8, size = 46 }: { v: number; max?: number; size?: number }) {
  const pct = clamp(v / max, 0, 1);
  const r = (size - 6) / 2;
  const c = 2 * Math.PI * r;
  const col = pct >= 0.85 ? 'var(--interactive)' : pct >= 0.6 ? 'var(--z-blue)' : 'var(--z-orange)';
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flex: 'none' }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-sunken)" strokeWidth="4" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={col}
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - pct)}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text
        x="50%"
        y="52%"
        dominantBaseline="middle"
        textAnchor="middle"
        fontSize="12"
        fontWeight="700"
        fill="var(--text-primary)"
      >
        {v}
      </text>
    </svg>
  );
}

function NavLeaf({ x, sel, onPick }: { x: SubcapNode; sel: string | null; onPick: (id: string) => void }) {
  return (
    <div
      className="navitem"
      style={{
        padding: '6px 8px',
        background: sel === x.id ? 'var(--surface-overlay)' : '',
        color: sel === x.id ? 'var(--text-primary)' : '',
      }}
      onClick={() => onPick(x.id)}
    >
      <span
        style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
      >
        {x.name}
      </span>
      {x.is_new && (
        <span className="chip teal" style={{ padding: '0 4px', fontSize: 9.5 }}>
          new
        </span>
      )}
      <span className="pilldot" style={{ width: 6, height: 6, background: LIFE_COLORS[x.life] }} title={x.life} />
    </div>
  );
}

function EmptyTab({ icon, title, desc }: { icon: IconName; title: string; desc: string }) {
  return (
    <div className="fade-in">
      <Empty icon={icon} title={title} desc={desc} />
    </div>
  );
}

function OverviewTab({ d, node }: { d: SubcapDetail | undefined; node: SubcapNode | null }) {
  return (
    <div className="fade-in">
      <p style={{ margin: '0 0 16px', fontSize: 13.5, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
        {d?.description ?? 'No description recorded in this version.'}
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 14 }}>
        <div>
          <div className="eyebrow" style={{ marginBottom: 7 }}>
            Personas
          </div>
          <span className="muted" style={{ fontSize: 12 }}>
            none recorded
          </span>
        </div>
        <div>
          <div className="eyebrow" style={{ marginBottom: 7 }}>
            Offering
          </div>
          <span className="muted" style={{ fontSize: 12 }}>
            No productized offering yet
          </span>
        </div>
      </div>
      <div className="divider" />
      <div className="between" style={{ marginBottom: 9 }}>
        <div className="eyebrow">Linked L3 platforms · {d?.n_platforms ?? 0}</div>
        <span className="muted" style={{ fontSize: 11 }}>
          click to drill into the platform
        </span>
      </div>
      <span className="muted" style={{ fontSize: 12 }}>
        none mapped
      </span>
      <div className="muted" style={{ fontSize: 11, marginTop: 8 }}>
        The {d?.n_use_cases ?? 0} use cases and {d?.n_stories ?? 0} stories on {node?.id ?? 'this subcap'}{' '}
        ride on these platforms — platform links and counts arrive with catalogue enrichment.
      </div>
    </div>
  );
}

export function SubcapWorkbench() {
  const params = useParams<{ id?: string }>();
  const routeId = params.id ?? null;
  const version = useUi((s) => s.version);
  const ctxPillar = useUi((s) => s.pillar);
  const subcaps = useSubcaps(version);
  const all = useMemo(() => subcaps.data ?? [], [subcaps.data]);

  const [pillar, setPillar] = useState<string>(
    routeId ? routeId.slice(0, 2) : ctxPillar === 'all' ? 'P1' : ctxPillar,
  );
  const [q, setQ] = useState('');
  const [sel, setSel] = useState<string | null>(routeId);
  const [tab, setTab] = useState('overview');
  const [openCat, setOpenCat] = useState<string | null>(null);

  // Deep-link / back-forward: when the route id changes, focus it.
  useEffect(() => {
    if (routeId) {
      setSel(routeId);
      setPillar(routeId.slice(0, 2));
      setTab('overview');
    }
  }, [routeId]);

  const node = useMemo(() => all.find((x) => x.id === sel) ?? null, [all, sel]);
  const detail = useSubcap(version, sel);
  const d = detail.data;

  const searching = q.trim().length >= 2;
  const results = useMemo(() => {
    if (!searching) return null;
    const t = q.toLowerCase();
    return all
      .filter(
        (x) =>
          x.name.toLowerCase().includes(t) ||
          x.id.toLowerCase().includes(t) ||
          x.cluster.toLowerCase().includes(t),
      )
      .slice(0, 60);
  }, [searching, q, all]);

  const tree = useMemo(() => {
    const pool = searching ? [] : all.filter((x) => x.pillar === pillar);
    const cats = new Map<string, { id: string; name: string; clusters: Map<string, SubcapNode[]>; n: number }>();
    for (const x of pool) {
      let c = cats.get(x.cat_id);
      if (!c) {
        c = { id: x.cat_id, name: x.cat_name, clusters: new Map(), n: 0 };
        cats.set(x.cat_id, c);
      }
      c.n += 1;
      const arr = c.clusters.get(x.cluster) ?? [];
      arr.push(x);
      c.clusters.set(x.cluster, arr);
    }
    return [...cats.values()];
  }, [searching, all, pillar]);

  // Keep the selected subcap's category expanded; otherwise default to the first.
  useEffect(() => {
    if (node) setOpenCat(node.cat_id);
    else if (tree[0]) setOpenCat(tree[0].id);
  }, [node, tree]);

  const pick = (id: string) => {
    setSel(id);
    setTab('overview');
  };

  const comp = Math.round((d?.completeness ?? 0) * 8);
  const stats: [number, string, string][] = [
    [d?.n_use_cases ?? 0, 'use cases', 'usecases'],
    [d?.n_stories ?? 0, 'stories', 'delivery'],
    [d?.n_platforms ?? 0, 'platforms', 'overview'],
    [0, 'maturity levels', 'maturity'],
  ];

  const tabBody: ReactNode =
    tab === 'overview' ? (
      <OverviewTab d={d} node={node} />
    ) : tab === 'maturity' ? (
      <EmptyTab
        icon="bars"
        title="Maturity ladder lands with enrichment"
        desc="The M1–M5 maturity descriptors are generated by the catalogue enrichment pass (F6); this tab renders the ladder once they are stored for the active version."
      />
    ) : tab === 'usecases' ? (
      <EmptyTab
        icon="puzzle"
        title="No use cases recorded yet"
        desc="Use cases are populated by enrichment from the source workbook; archetype and maturity cards appear here when the use_case table is seeded for this version."
      />
    ) : tab === 'delivery' ? (
      <EmptyTab
        icon="trend"
        title="Delivery evidence lands with the story corpus"
        desc="F5 carry-forward links the 14,406-row Jira corpus to this subcap; the six-quarter delivery bars and story rows (with ac/sd/ss sub-scores) light up then."
      />
    ) : (
      <EmptyTab
        icon="graph"
        title="Connections light up with the knowledge graph"
        desc="Deterministic KG siblings (Layer A) and recent news/vendor signals — each carrying the full trust envelope — appear here once evidence (F7) and the graph projection land."
      />
    );

  return (
    <>
      <div className="titlebar">
        <div className="crumbs">
          <a onClick={() => go('explorer')}>A · Explore</a>
          <span className="sep">
            <Icon n="chevR" s={11} />
          </span>
          <span style={{ color: 'var(--text-secondary)' }}>Capability workbench</span>
        </div>
        <span className="grow" />
        {node && (
          <button className="btn ghost sm" onClick={() => go('trace/' + node.id)}>
            <Icon n="branch" s={14} /> Trace
          </button>
        )}
        {node && (
          <button
            className="btn primary sm"
            onClick={() => toast('AI audit runs once the reasoning + gates pipeline (F7/F8) is live.')}
          >
            <Icon n="sparkles" s={14} /> AI audit
          </button>
        )}
      </div>

      <div
        className="content wide fade-in"
        style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 20, alignItems: 'start' }}
      >
        <div style={{ position: 'sticky', top: 78, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div className="searchbox">
            <Icon n="search" s={15} />
            <input
              placeholder={`Search ${all.length} subcaps…`}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            {q && (
              <button className="linkbtn" onClick={() => setQ('')}>
                <Icon n="x" s={14} />
              </button>
            )}
          </div>
          {!searching && (
            <div className="pillseg" style={{ justifyContent: 'space-between' }}>
              {PILLARS.map((p) => (
                <button
                  key={p}
                  className={pillar === p ? 'on' : ''}
                  onClick={() => setPillar(p)}
                  title={PILLAR_SHORT[p]}
                >
                  <span className="dot" style={{ background: PILLAR_COLORS[p] }} />
                  {p}
                </button>
              ))}
            </div>
          )}
          <div className="card" style={{ padding: 6, maxHeight: 'calc(100vh - 220px)', overflowY: 'auto' }}>
            {searching ? (
              results && results.length ? (
                results.map((x) => <NavLeaf key={x.id} x={x} sel={sel} onPick={pick} />)
              ) : (
                <div className="muted" style={{ padding: 14, fontSize: 12 }}>
                  No matches.
                </div>
              )
            ) : (
              tree.map((c) => {
                const open = openCat === c.id;
                return (
                  <div key={c.id}>
                    <div
                      className="navitem"
                      style={{ fontWeight: 600, fontSize: 12.5 }}
                      onClick={() => setOpenCat(open ? null : c.id)}
                    >
                      <Icon n={open ? 'chevD' : 'chevR'} s={13} style={{ color: 'var(--text-tertiary)' }} />
                      <span
                        style={{
                          flex: 1,
                          minWidth: 0,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {c.name}
                      </span>
                      <span className="ncount">{c.n}</span>
                    </div>
                    {open && (
                      <div style={{ paddingLeft: 6 }}>
                        {[...c.clusters.entries()].map(([cl, subs]) => (
                          <div key={cl} style={{ marginBottom: 2 }}>
                            <div className="eyebrow" style={{ padding: '7px 8px 3px', fontSize: 9.5 }}>
                              {cl}
                            </div>
                            {subs.map((x) => (
                              <NavLeaf key={x.id} x={x} sel={sel} onPick={pick} />
                            ))}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>

        {!node ? (
          <div className="card pad">
            <Empty
              icon="layers"
              title="Pick a capability to explore"
              desc="Browse the tree or search, then drill into a subcap. Its detail opens here with tabs — overview, maturity, use cases, delivery and connections — so you see only what you need."
            />
          </div>
        ) : (
          <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div className="card pad">
              <div className="row gap8" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
                <PillarDot p={node.pillar} />
                <LifeChip life={d?.lifecycle_state ?? node.life} />
                {d?.tier && <Tier t={d.tier} />}
                <span className="chip soft">{d?.solution_type || '—'}</span>
                {node.is_new && <span className="chip teal">new in v7</span>}
              </div>
              <div className="row gap16" style={{ alignItems: 'flex-start' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="display" style={{ fontSize: 24, marginBottom: 5, lineHeight: 1.12 }}>
                    {node.name}
                  </div>
                  <div className="row gap8" style={{ flexWrap: 'wrap' }}>
                    <span className="mono" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                      {node.id}
                    </span>
                    <span className="muted">·</span>
                    <span className="muted" style={{ fontSize: 12 }}>
                      {node.cat_name} → {node.cluster}
                    </span>
                  </div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <Ring v={comp} />
                  <div className="muted" style={{ fontSize: 9.5, marginTop: 2 }}>
                    complete
                  </div>
                </div>
              </div>
              <div className="row gap8 mt16" style={{ flexWrap: 'wrap' }}>
                {stats.map((k, i) => (
                  <button
                    key={i}
                    className="card hov"
                    style={{
                      padding: '7px 12px',
                      cursor: 'pointer',
                      display: 'flex',
                      gap: 7,
                      alignItems: 'baseline',
                      background: 'var(--surface-base)',
                    }}
                    onClick={() => setTab(k[2])}
                  >
                    <b className="num" style={{ fontSize: 15, color: 'var(--interactive)' }}>
                      {k[0]}
                    </b>
                    <span className="muted" style={{ fontSize: 11 }}>
                      {k[1]}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            <div className="card" style={{ overflow: 'hidden' }}>
              <div
                style={{
                  display: 'flex',
                  gap: 2,
                  padding: '8px 8px 0',
                  borderBottom: '1px solid var(--border-subtle)',
                  overflowX: 'auto',
                }}
              >
                {TABS.map(([id, t]) => (
                  <button
                    key={id}
                    onClick={() => setTab(id)}
                    style={{
                      border: 'none',
                      background: 'none',
                      fontFamily: 'inherit',
                      fontSize: 12.5,
                      fontWeight: tab === id ? 700 : 500,
                      color: tab === id ? 'var(--text-primary)' : 'var(--text-tertiary)',
                      padding: '8px 12px',
                      cursor: 'pointer',
                      borderBottom: '2px solid ' + (tab === id ? 'var(--interactive)' : 'transparent'),
                      marginBottom: -1,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {t}
                  </button>
                ))}
              </div>
              <div className="pad" style={{ padding: 18 }}>
                {tabBody}
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
