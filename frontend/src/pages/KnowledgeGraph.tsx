// Knowledge graph (B3 · admin) — the DEEP relationships the flat catalogue hides, wired to
// GET /api/catalogue/{v}/kg?subcap=. Layer A (solid) is a deterministic projection of the link
// tables (platforms/offerings used, siblings sharing a platform / offering / value-chain stage) —
// every edge traces to a real row. Layer B (dashed) are AI-proposed pending_edges — co-delivery
// bonds mined from the Jira corpus, structural co-membership, semantic near-neighbours — each with a
// unified STRENGTH (thickness ∝ strength), a NOVELTY rank, and a human-readable "why", gated in
// Change flags before commit. The headline: a novelty-ranked "relationships you may be missing"
// panel that surfaces the strong-but-non-obvious (cross-pillar, no shared platform) links.
import { useEffect, useMemo, useState } from 'react';

import type { KgEdge, KgNode, LatentEdge } from '../api/client';
import { useKg, useKgDiscover, useSubcaps } from '../api/queries';
import { Dropdown, Empty, Page, Seg } from '../components/primitives';
import { go, openPeek, openReasoning } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const NODE_COLOR: Record<string, string> = {
  subcap: 'var(--p4)',
  offering: 'var(--interactive)',
  platform: 'var(--z-blue)',
  theme: 'var(--z-slate)',
};

// One colour per relationship kind so the graph reads at a glance; co-delivery (the latent core) is
// the warm accent, the structural kinds are cool, semantic is the pillar-4 violet.
const REL_COLOR: Record<string, string> = {
  co_delivered: 'var(--z-orange)',
  shares_platform: 'var(--z-blue)',
  shares_offering: 'var(--interactive)',
  same_value_chain: 'var(--p3)',
  shares_feature: 'var(--p1)',
  semantically_similar: 'var(--p4)',
  uses_platform: 'var(--z-slate)',
  maps_to_offering: 'var(--interactive)',
};

// R6 directional relations get their OWN accessible palette (drawn from the app tokens) so the
// semantic verb reads at a glance and pairs with the arrowhead. When an edge carries a `relation`
// this colour wins over the structural `kind` colour above.
const REL_R6_COLOR: Record<string, string> = {
  enables: 'var(--interactive)', // teal — one capability unlocks another
  depends_on: 'var(--z-orange)', // orange — a hard prerequisite
  precedes: 'var(--z-blue)', // blue — sequencing in the value chain
  affects: 'var(--p4)', // slate-violet — influences without gating
  complements: 'var(--z-teal-light)', // mint — mutually reinforcing (symmetric)
  alternative_to: 'var(--z-slate)', // slate — substitutable (symmetric)
  subsumes: 'var(--interactive-active)', // deep teal — one contains the other
};
const relColor = (kind: string): string => REL_COLOR[kind] ?? 'var(--border-medium)';
const relLabel = (kind: string): string => kind.replace(/_/g, ' ');
// The colour an edge draws in: its R6 relation if present, else the structural-kind colour.
const edgeColor = (e: KgEdge | LatentEdge): string =>
  e.relation ? REL_R6_COLOR[e.relation] ?? relColor(e.kind) : relColor(e.kind);
// → for a directed (forward) relation, ↔ for a symmetric one (or a legacy null relation).
const relArrow = (dir?: string | null): string => (dir === 'forward' ? '→' : '↔');
const edgeStrength = (e: KgEdge): number => e.strength ?? e.score ?? 0.4;

function LatentRow({ e }: { e: LatentEdge }) {
  const crossPillar = e.crosses === 'cross_pillar';
  const arrow = relArrow(e.direction);
  return (
    <div className="card" style={{ padding: '9px 11px' }}>
      <div className="between" style={{ marginBottom: 3 }}>
        <span className="row gap6" style={{ fontSize: 10.5 }}>
          <span className={crossPillar ? 'claim hypothesis' : 'claim inference'}>
            {crossPillar ? 'cross-pillar' : 'cross-cap'}
          </span>
          {/* R6 directional relation + arrow glyph (→ forward, ↔ symmetric) over the legacy kind */}
          <span className="mono" style={{ color: edgeColor(e) }}>
            {e.relation ? `${relLabel(e.relation)} ${arrow}` : relLabel(e.kind)}
          </span>
        </span>
        <span className="num" style={{ fontSize: 11, fontWeight: 700, color: 'var(--state-warn-text)' }}>
          novelty {e.novelty.toFixed(2)}
        </span>
      </div>
      <div className="sclink mono" style={{ fontSize: 11 }} onClick={() => openPeek(e.target)}>
        {e.source} {arrow} {e.target} · {e.target_name.slice(0, 26)}
      </div>
      <div className="muted" style={{ fontSize: 10.5, marginTop: 2 }}>{e.rationale || e.basis}</div>
      {e.keywords && e.keywords.length > 0 && (
        <div className="row wrap gap6" style={{ marginTop: 5 }}>
          {e.keywords.slice(0, 5).map((k) => (
            <span key={k} className="chip outline" style={{ fontSize: 9.5, padding: '2px 6px' }}>
              {k}
            </span>
          ))}
        </div>
      )}
      <div className="row gap8" style={{ marginTop: 6 }}>
        {e.chain && (
          <button className="btn ghost sm" onClick={() => openReasoning(e.chain)}>
            Reasoning
          </button>
        )}
        <button className="btn ghost sm" onClick={() => openPeek(e.target)}>
          Peek
        </button>
        <button className="btn ghost sm" onClick={() => go('change-flags')}>
          Review
        </button>
      </div>
    </div>
  );
}

export function KnowledgeGraph() {
  const ui = useUi();
  const isAdmin = useUi((s) => s.adminView);
  const subs = useSubcaps(ui.version);
  const [layer, setLayer] = useState('full');
  const [center, setCenter] = useState('');
  const [sel, setSel] = useState<string | null>(null);
  const [selEdge, setSelEdge] = useState<KgEdge | null>(null);
  const [minStrength, setMinStrength] = useState(0);

  const options = (subs.data ?? []).slice(0, 40).map((x) => ({
    v: x.id,
    l: x.id + ' · ' + x.name.slice(0, 20),
  }));
  const cur = center || options[0]?.v || '';
  const kg = useKg(ui.version, isAdmin ? cur : null);
  const disc = useKgDiscover(ui.version, isAdmin);
  useEffect(() => {
    setSel(null);
    setSelEdge(null);
  }, [cur, layer]);

  const showB = layer !== 'A';
  const latent = kg.data?.latent ?? [];
  const centerId = kg.data?.center ?? '';
  const allShown = useMemo(() => {
    const pass = (e: KgEdge) => edgeStrength(e) >= minStrength;
    const edges = (kg.data?.edges ?? []).filter(pass);
    const pending = showB ? (kg.data?.pending ?? []).filter(pass) : [];
    return [...edges, ...pending];
  }, [kg.data, showB, minStrength]);
  const visibleNodes = useMemo(() => {
    const connected = new Set<string>([centerId]);
    allShown.forEach((e) => {
      connected.add(e.source);
      connected.add(e.target);
    });
    return (kg.data?.nodes ?? []).filter((n) => connected.has(n.id));
  }, [kg.data, allShown, centerId]);

  // R6 relations actually present in the drawn graph — drives the legend (only what's on screen).
  const presentRelations = useMemo(() => {
    const seen = new Set<string>();
    allShown.forEach((e) => {
      if (e.relation) seen.add(e.relation);
    });
    return [...seen];
  }, [allShown]);

  const layout = useMemo(() => {
    const W = 620;
    const H = 460;
    const cx = W / 2;
    const cy = H / 2;
    const neighbours = visibleNodes.filter((n) => n.id !== centerId);
    const pos = new Map<string, { x: number; y: number }>();
    // node draw-radius (kept in sync with the circle render below) — so a forward arrowhead lands on
    // the target's rim instead of hiding under its circle.
    const rad = new Map<string, number>();
    pos.set(centerId, { x: cx, y: cy });
    rad.set(centerId, 26);
    neighbours.forEach((n, i) => {
      const a = (i / Math.max(1, neighbours.length)) * 2 * Math.PI - Math.PI / 2;
      const r = n.kind === 'subcap' ? 200 : 150;
      pos.set(n.id, { x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r });
      rad.set(n.id, n.kind === 'subcap' ? 18 : 14);
    });
    return { W, H, pos, rad };
  }, [visibleNodes, centerId]);

  const onNode = (n: KgNode) => {
    setSelEdge(null);
    setSel((s) => (s === n.id ? null : n.id));
  };
  const navNode = (n: KgNode) => {
    if (n.kind === 'subcap') openPeek(n.id);
    else if (n.kind === 'platform') go('platforms');
  };

  return (
    <Page
      eyebrow="B · Catalogue tools · admin"
      title="Knowledge graph"
      intro="Reveal the deep relationships the flat catalogue hides. Solid edges are deterministic (Layer A); dashed edges are AI-proposed (Layer B) — co-delivery bonds mined from the Jira corpus, structural co-membership, semantic near-neighbours — each weighted by strength and gated in Change flags. The 'relationships you may be missing' panel ranks the strong-but-non-obvious links first."
      actions={
        <div className="row gap8">
          <Dropdown value={cur} icon="branch" options={options} onChange={(v) => setCenter(v)} />
          <Seg
            options={[
              { v: 'A', l: 'Deterministic' },
              { v: 'B', l: '+ AI' },
              { v: 'full', l: 'Full' },
            ]}
            value={layer}
            onChange={setLayer}
          />
          <label className="row gap6 muted" style={{ fontSize: 11 }}>
            strength ≥ {minStrength.toFixed(2)}
            <input
              type="range"
              min={0}
              max={0.95}
              step={0.05}
              value={minStrength}
              onChange={(ev) => setMinStrength(Number(ev.target.value))}
            />
          </label>
        </div>
      }
    >
      {!isAdmin ? (
        <div className="banner warn">
          <Icon n="lock" s={15} />
          The knowledge graph is admin-only. Enable the is_admin toggle to explore catalogue
          relationships.
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 18 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 18, alignItems: 'start' }}>
            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div style={{ padding: 12 }}>
                {kg.isLoading && (
                  <div className="muted" style={{ fontSize: 12, padding: 12 }}>
                    Projecting the neighbourhood…
                  </div>
                )}
                {kg.data && visibleNodes.length <= 1 && (
                  <Empty
                    icon="graph"
                    title="No edges at this strength"
                    desc="This subcap has no platform, offering, value-chain or co-delivery links above the strength filter. Lower the slider, pick another centre, or open it to add mappings."
                  />
                )}
                {kg.data && visibleNodes.length > 1 && (
                  <svg width="100%" viewBox={`0 0 ${layout.W} ${layout.H}`} style={{ display: 'block' }}>
                    {/* One arrowhead marker per present R6 relation so its colour matches the stroke
                        (SVG context-stroke isn't reliable across browsers). Drawn only for forward
                        (directed) edges; symmetric/legacy edges stay arrowless as today. */}
                    <defs>
                      {presentRelations.map((rel) => (
                        <marker
                          key={rel}
                          id={`arrow-${rel}`}
                          viewBox="0 0 10 10"
                          refX="9"
                          refY="5"
                          markerWidth="9"
                          markerHeight="9"
                          markerUnits="userSpaceOnUse"
                          orient="auto-start-reverse"
                        >
                          <path d="M0 0 L10 5 L0 10 z" fill={REL_R6_COLOR[rel] ?? 'var(--border-medium)'} />
                        </marker>
                      ))}
                    </defs>
                    {allShown.map((e, i) => {
                      const a = layout.pos.get(e.source);
                      const b = layout.pos.get(e.target);
                      if (!a || !b) return null;
                      const isB = e.layer === 'B_proposed';
                      const inc = sel != null && (e.source === sel || e.target === sel);
                      const isSel = selEdge === e;
                      const dim = (sel != null && !inc) || (selEdge != null && !isSel);
                      const color = edgeColor(e);
                      const forward = e.direction === 'forward' && !!e.relation;
                      // Trim the drawn line back to the target's rim so a forward arrowhead sits ON
                      // the node edge, not buried under the circle.
                      const dx = b.x - a.x;
                      const dy = b.y - a.y;
                      const len = Math.hypot(dx, dy) || 1;
                      const rB = (layout.rad.get(e.target) ?? 16) + 3;
                      const ex = forward ? b.x - (dx / len) * rB : b.x;
                      const ey = forward ? b.y - (dy / len) * rB : b.y;
                      return (
                        <g
                          key={i}
                          opacity={dim ? 0.16 : 1}
                          style={{ cursor: 'pointer' }}
                          onClick={() => {
                            setSel(null);
                            setSelEdge((s) => (s === e ? null : e));
                          }}
                        >
                          <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="transparent" strokeWidth={10} />
                          <line
                            x1={a.x}
                            y1={a.y}
                            x2={ex}
                            y2={ey}
                            stroke={color}
                            strokeWidth={(isSel || inc ? 1.5 : 0) + 1 + edgeStrength(e) * 3.5}
                            strokeDasharray={isB ? '5 4' : undefined}
                            markerEnd={forward ? `url(#arrow-${e.relation})` : undefined}
                          />
                          {/* Relation label at the midpoint: always shown when the edge carries an R6
                              relation, otherwise (legacy) only on hover/select as before. */}
                          {(e.relation || inc || isSel) && (
                            <text
                              x={(a.x + b.x) / 2}
                              y={(a.y + b.y) / 2 - 3}
                              fontSize="8.5"
                              fontWeight="700"
                              fill={color}
                              textAnchor="middle"
                            >
                              {e.relation ? relLabel(e.relation) : relLabel(e.kind)}
                              {(inc || isSel) && ` · ${edgeStrength(e).toFixed(2)}`}
                            </text>
                          )}
                        </g>
                      );
                    })}
                    {visibleNodes.map((n) => {
                      const p = layout.pos.get(n.id);
                      if (!p) return null;
                      const isCenter = n.id === centerId;
                      const r = isCenter ? 26 : n.kind === 'subcap' ? 18 : 14;
                      return (
                        <g
                          key={n.id}
                          style={{ cursor: 'pointer' }}
                          onClick={() => onNode(n)}
                          onDoubleClick={() => navNode(n)}
                        >
                          {n.id === sel && (
                            <circle cx={p.x} cy={p.y} r={r + 4} fill="none" stroke="var(--interactive)" strokeWidth="2" />
                          )}
                          <circle
                            cx={p.x}
                            cy={p.y}
                            r={r}
                            fill={isCenter ? 'var(--interactive)' : NODE_COLOR[n.kind] ?? 'var(--z-slate)'}
                            stroke="var(--surface-base)"
                            strokeWidth="2"
                            opacity={isCenter ? 1 : 0.88}
                          />
                          <text x={p.x} y={p.y + r + 11} fontSize="9" fill="var(--text-secondary)" textAnchor="middle">
                            {n.label.length > 18 ? n.label.slice(0, 17) + '…' : n.label}
                          </text>
                        </g>
                      );
                    })}
                  </svg>
                )}
              </div>
              {/* R6 directional legend — only the relations present in THIS graph, with the arrow
                  glyph (→ forward, ↔ symmetric) taken from a representative edge. */}
              {presentRelations.length > 0 && (
                <div
                  className="row gap12"
                  style={{ padding: '9px 16px', borderTop: '1px solid var(--border-subtle)', fontSize: 10.5, flexWrap: 'wrap' }}
                >
                  <span className="eyebrow" style={{ fontSize: 9.5 }}>
                    Relations
                  </span>
                  {presentRelations.map((rel) => {
                    const dir = allShown.find((e) => e.relation === rel)?.direction;
                    return (
                      <span key={rel} className="row gap6">
                        <span
                          style={{ width: 16, height: 0, borderTop: `2px solid ${REL_R6_COLOR[rel] ?? 'var(--border-medium)'}` }}
                        />
                        {relLabel(rel)} <span className="mono">{relArrow(dir)}</span>
                      </span>
                    );
                  })}
                </div>
              )}
              <div
                className="row gap12"
                style={{ padding: '10px 16px', borderTop: '1px solid var(--border-subtle)', fontSize: 10.5, flexWrap: 'wrap' }}
              >
                {['co_delivered', 'shares_platform', 'shares_offering', 'same_value_chain', 'semantically_similar'].map(
                  (k) => (
                    <span key={k} className="row gap6">
                      <span style={{ width: 16, height: 0, borderTop: `2px solid ${relColor(k)}` }} />
                      {relLabel(k)}
                    </span>
                  ),
                )}
                <span className="grow" />
                <span className="row gap6">
                  <span style={{ width: 16, height: 0, borderTop: '2px dashed var(--text-tertiary)' }} />
                  AI-proposed · thickness ∝ strength · click an edge for its “why”
                </span>
              </div>
            </div>
            <div style={{ display: 'grid', gap: 14 }}>
              {selEdge ? (
                <div className="card pad" style={{ borderColor: edgeColor(selEdge) }}>
                  <div className="between" style={{ marginBottom: 8 }}>
                    <span className="h3">
                      Edge · {relLabel(selEdge.relation || selEdge.kind)}
                    </span>
                    <button className="btn ghost sm" onClick={() => setSelEdge(null)}>
                      <Icon n="x" s={13} />
                    </button>
                  </div>
                  <div className="mono" style={{ fontSize: 11.5, marginBottom: 6 }}>
                    {selEdge.source} {relArrow(selEdge.direction)} {selEdge.target}
                  </div>
                  <div className="row wrap gap8" style={{ marginBottom: 6 }}>
                    <span className="claim hypothesis">
                      {selEdge.layer === 'B_proposed' ? 'AI proposed' : 'deterministic'}
                    </span>
                    {/* R6 direction: directed (→) vs symmetric (↔), stated in words, not colour-only */}
                    {selEdge.relation && (
                      <span className="chip outline">
                        {selEdge.direction === 'forward' ? 'directed →' : 'symmetric ↔'}
                      </span>
                    )}
                    {selEdge.crosses && <span className="chip">{selEdge.crosses.replace(/_/g, '-')}</span>}
                    <span className="num" style={{ fontSize: 11, fontWeight: 700 }}>
                      strength {edgeStrength(selEdge).toFixed(2)}
                    </span>
                  </div>
                  {/* R6 grounded "why" (rationale) preferred over the legacy basis line */}
                  {(selEdge.rationale || selEdge.basis) && (
                    <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                      {selEdge.rationale || selEdge.basis}
                    </div>
                  )}
                  {selEdge.keywords && selEdge.keywords.length > 0 && (
                    <div className="row wrap gap6" style={{ marginBottom: 8 }}>
                      {selEdge.keywords.map((k) => (
                        <span key={k} className="chip outline" style={{ fontSize: 10 }}>
                          {k}
                        </span>
                      ))}
                    </div>
                  )}
                  {/* R6 adversary survival + Jira-corpus corroboration — the trust evidence */}
                  {(selEdge.verify_survived != null || selEdge.corroboration) && (
                    <div
                      className="card"
                      style={{ background: 'var(--surface-raised)', padding: '8px 10px', marginBottom: 8 }}
                    >
                      {selEdge.verify_survived != null && (
                        <div className="row gap6" style={{ fontSize: 11.5, marginBottom: selEdge.corroboration ? 4 : 0 }}>
                          <Icon n="shield" s={12} />
                          <span>
                            adversary upheld{' '}
                            <b className="num">{Math.round(selEdge.verify_survived * 100)}%</b>
                          </span>
                        </div>
                      )}
                      {selEdge.corroboration && (
                        <div className="muted" style={{ fontSize: 11 }}>{selEdge.corroboration}</div>
                      )}
                    </div>
                  )}
                  <div className="row gap8">
                    {selEdge.chain && (
                      <button className="btn ghost sm" onClick={() => openReasoning(selEdge.chain)}>
                        Reasoning
                      </button>
                    )}
                    <button className="btn ghost sm" onClick={() => openPeek(selEdge.target)}>
                      Peek target
                    </button>
                    {selEdge.layer === 'B_proposed' && (
                      <button className="btn ghost sm" onClick={() => go('change-flags')}>
                        Review
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                <div className="card pad">
                  <div className="h3" style={{ marginBottom: 8 }}>
                    Centre: {kg.data?.name ?? cur ?? '—'}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginBottom: 10 }}>
                    {(['platforms', 'offerings', 'siblings'] as const).map((k) => (
                      <div key={k} className="card" style={{ padding: '8px 6px', textAlign: 'center' }}>
                        <div className="num" style={{ fontSize: 18, fontWeight: 700, color: 'var(--interactive)' }}>
                          {kg.data?.stats[k] ?? 0}
                        </div>
                        <div className="muted" style={{ fontSize: 9.5 }}>{k}</div>
                      </div>
                    ))}
                  </div>
                  <button
                    className="btn ghost sm"
                    style={{ width: '100%', justifyContent: 'center' }}
                    onClick={() => go('subcap/' + cur)}
                  >
                    Open subcap <Icon n="arrowR" s={13} />
                  </button>
                </div>
              )}
              {latent.length > 0 && (
                <div className="card pad" style={{ borderColor: 'var(--z-orange)' }}>
                  <div className="h3" style={{ marginBottom: 8 }}>
                    You may be missing ({latent.length})
                  </div>
                  <div style={{ display: 'grid', gap: 8 }}>
                    {latent.slice(0, 5).map((e, i) => (
                      <LatentRow key={i} e={e} />
                    ))}
                  </div>
                </div>
              )}
              <div className="card pad" style={{ borderColor: 'var(--border-medium)' }}>
                <div className="h3" style={{ marginBottom: 8 }}>
                  Pending edges ({kg.data?.stats.pending ?? 0})
                </div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
                  AI-proposed Layer-B edges queue for review before commit — nothing is written as
                  fact ungated.
                </div>
                <button
                  className="btn primary sm"
                  style={{ width: '100%', justifyContent: 'center' }}
                  onClick={() => go('change-flags')}
                >
                  Review in change flags <Icon n="arrowR" s={14} />
                </button>
              </div>
            </div>
          </div>
          {/* Headline: version-wide "relationships you may be missing" — novelty-ranked discoveries */}
          <div className="card pad">
            <div className="between" style={{ marginBottom: 4 }}>
              <span className="h3">Relationships you may be missing</span>
              <span className="muted" style={{ fontSize: 11 }}>
                strong yet non-obvious · ranked by novelty · gated
              </span>
            </div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
              The links the catalogue structure hides — cross-pillar subcaps co-delivered together in
              real projects, with no shared platform to give them away. Every one is a gated proposal.
            </div>
            {disc.isLoading && <div className="muted" style={{ fontSize: 12 }}>Mining the corpus…</div>}
            {disc.data && disc.data.latent.length === 0 && (
              <div className="muted" style={{ fontSize: 12 }}>
                No latent relationships surfaced for this version yet.
              </div>
            )}
            {disc.data && disc.data.latent.length > 0 && (
              <div
                style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 10 }}
              >
                {disc.data.latent.map((e, i) => (
                  <LatentRow key={i} e={e} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </Page>
  );
}
