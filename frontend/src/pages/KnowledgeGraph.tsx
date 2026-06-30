// Knowledge graph (B3 · admin) — the relationships the flat catalogue hides, wired to
// GET /api/catalogue/{v}/kg?subcap=. Layer A (solid) is a DETERMINISTIC projection of the link
// tables. Layer B (dashed, coloured by relation) are AI-proposed/accepted edges carrying a unified
// strength — structural co-occurrence, semantic similarity, shared offering, and the LATENT
// co-delivery links mined from the Jira corpus. "Relationships you may be missing" ranks the most
// novel hidden links (strong but cross-pillar). Every inferred edge is grounded + gated; nothing
// renders as fact until approved in Change flags.
import { useEffect, useMemo, useState } from 'react';

import type { KgEdge, KgNode, LatentEdge } from '../api/client';
import { useKg, useKgDiscover, useSubcaps } from '../api/queries';
import { Dropdown, Empty, Page, Seg } from '../components/primitives';
import { go, openPeek } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const KIND_COLOR: Record<string, string> = {
  subcap: 'var(--p4)',
  offering: 'var(--interactive)',
  platform: 'var(--z-blue)',
  theme: 'var(--z-slate)',
};

// One colour per relation so the graph reads at a glance — co-delivery (the latent Jira signal) is
// the visual headline; structural/semantic relations each get their own hue.
const RELATION_COLOR: Record<string, string> = {
  co_delivered: '#8b5cf6',
  semantically_similar: 'var(--z-teal)',
  shares_offering: 'var(--interactive)',
  shares_platform: 'var(--z-blue)',
  shares_feature: 'var(--z-slate)',
  uses_platform: 'var(--border-medium)',
  maps_to_offering: 'var(--border-medium)',
};
const RELATION_LABEL: Record<string, string> = {
  co_delivered: 'co-delivered',
  semantically_similar: 'semantic',
  shares_offering: 'shared offering',
  shares_platform: 'shared platform',
  shares_feature: 'shared persona',
};
const edgeColor = (kind: string) => RELATION_COLOR[kind] ?? 'var(--border-medium)';

function CrossBadge({ crosses }: { crosses?: string | null }) {
  if (!crosses) return null;
  const xp = crosses === 'cross_pillar';
  return (
    <span
      className="chip"
      style={{
        fontSize: 9,
        background: xp ? 'var(--state-warn-bg)' : 'var(--surface-sunken)',
        color: xp ? 'var(--state-warn-text)' : 'var(--text-tertiary)',
      }}
    >
      {xp ? 'cross-pillar' : 'cross-capability'}
    </span>
  );
}

export function KnowledgeGraph() {
  const ui = useUi();
  const isAdmin = useUi((s) => s.adminView);
  const subs = useSubcaps(ui.version);
  const [layer, setLayer] = useState('full');
  const [strong, setStrong] = useState(false);
  const [center, setCenter] = useState('');
  const [sel, setSel] = useState<string | null>(null);

  const options = (subs.data ?? []).slice(0, 40).map((x) => ({
    v: x.id,
    l: x.id + ' · ' + x.name.slice(0, 20),
  }));
  const cur = center || options[0]?.v || '';
  const kg = useKg(ui.version, isAdmin ? cur : null);
  const discover = useKgDiscover(ui.version, isAdmin);
  useEffect(() => setSel(null), [cur, layer]);

  const centerId = kg.data?.center ?? '';

  // Build the rendered graph: Layer A always; Layer B (pending + accepted) at +AI/Full; the centre's
  // LATENT co-delivery links (faint dashed, with synthesized nodes) at Full. A strength filter hides
  // the weak edges. Memoised so the layout is stable across selection changes.
  const graph = useMemo(() => {
    const data = kg.data;
    if (!data) return { nodes: [] as KgNode[], edges: [] as KgEdge[] };
    const showB = layer !== 'A';
    const showLatent = layer === 'full';
    const baseEdges: KgEdge[] = [...data.edges, ...(showB ? data.pending : [])];
    const baseIds = new Set(data.nodes.map((n) => n.id));
    const latN: KgNode[] = [];
    const latE: KgEdge[] = [];
    if (showLatent) {
      const seen = new Set<string>();
      data.latent.forEach((l) => {
        latE.push({
          source: l.source,
          target: l.target,
          kind: l.kind,
          layer: 'latent',
          strength: l.strength,
          score: l.strength,
          basis: l.basis,
          crosses: l.crosses,
        });
        (
          [
            [l.source, l.source_name],
            [l.target, l.target_name],
          ] as const
        ).forEach(([id, nm]) => {
          if (id !== data.center && !baseIds.has(id) && !seen.has(id)) {
            seen.add(id);
            latN.push({ id, kind: 'subcap', label: nm, pillar: id.slice(0, 2) });
          }
        });
      });
    }
    const min = strong ? 0.5 : 0;
    const edges = [...baseEdges, ...latE].filter((e) => (e.strength ?? 1) >= min);
    const connected = new Set<string>([data.center]);
    edges.forEach((e) => {
      connected.add(e.source);
      connected.add(e.target);
    });
    const nodes = [...data.nodes, ...latN].filter((n) => connected.has(n.id));
    return { nodes, edges };
  }, [kg.data, layer, strong]);

  const layout = useMemo(() => {
    const W = 620;
    const H = 460;
    const cx = W / 2;
    const cy = H / 2;
    const neighbours = graph.nodes.filter((n) => n.id !== centerId);
    const pos = new Map<string, { x: number; y: number }>();
    pos.set(centerId, { x: cx, y: cy });
    neighbours.forEach((n, i) => {
      const a = (i / Math.max(1, neighbours.length)) * 2 * Math.PI - Math.PI / 2;
      const r = n.kind === 'subcap' ? 200 : 150;
      pos.set(n.id, { x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r });
    });
    return { W, H, pos };
  }, [graph.nodes, centerId]);

  const onNode = (n: KgNode) => setSel((s) => (s === n.id ? null : n.id));
  const navNode = (n: KgNode) => {
    if (n.kind === 'subcap') openPeek(n.id);
    else if (n.kind === 'platform') go('platforms');
  };

  const latent = kg.data?.latent ?? [];
  const globalLatent = discover.data ?? [];

  return (
    <Page
      eyebrow="B · Catalogue tools · admin"
      title="Knowledge graph"
      intro="Reveal the relationships the flat catalogue hides — structural co-occurrence, semantic similarity, and the LATENT co-delivery links mined from the Jira corpus (delivered together far more than chance). Edge thickness is the relationship strength; dashed edges are AI-proposed, gated in Change flags before commit. Nothing renders as fact ungated."
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
          <Seg
            options={[
              { v: 'all', l: 'All' },
              { v: 'strong', l: 'Strong' },
            ]}
            value={strong ? 'strong' : 'all'}
            onChange={(v) => setStrong(v === 'strong')}
          />
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
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 18, alignItems: 'start' }}>
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ padding: 12 }}>
              {kg.isLoading && (
                <div className="muted" style={{ fontSize: 12, padding: 12 }}>
                  Projecting the neighbourhood…
                </div>
              )}
              {kg.data && graph.nodes.length <= 1 && (
                <Empty
                  icon="graph"
                  title="No edges for this subcap"
                  desc="This subcap has no platform, offering, structural or co-delivery links in this version yet. Pick another centre, or relax the strength filter."
                />
              )}
              {kg.data && graph.nodes.length > 1 && (
                <svg width="100%" viewBox={`0 0 ${layout.W} ${layout.H}`} style={{ display: 'block' }}>
                  {graph.edges.map((e, i) => {
                    const a = layout.pos.get(e.source);
                    const b = layout.pos.get(e.target);
                    if (!a || !b) return null;
                    const isLatent = e.layer === 'latent';
                    const isB = e.layer === 'B_proposed' || isLatent;
                    const inc = sel != null && (e.source === sel || e.target === sel);
                    const dim = sel != null && !inc;
                    const col = edgeColor(e.kind);
                    const w = 1 + 2.6 * (e.strength ?? 0.45) + (inc ? 1 : 0);
                    return (
                      <g key={i} opacity={dim ? 0.16 : isLatent ? 0.55 : 1}>
                        <line
                          x1={a.x}
                          y1={a.y}
                          x2={b.x}
                          y2={b.y}
                          stroke={col}
                          strokeWidth={w}
                          strokeDasharray={isB ? '5 4' : undefined}
                        >
                          <title>
                            {(RELATION_LABEL[e.kind] ?? e.kind.replace(/_/g, ' ')) +
                              (e.basis ? ` — ${e.basis}` : '')}
                          </title>
                        </line>
                        {inc && (
                          <text
                            x={(a.x + b.x) / 2}
                            y={(a.y + b.y) / 2 - 3}
                            fontSize="8.5"
                            fontWeight="700"
                            fill={isB ? col : 'var(--text-tertiary)'}
                            textAnchor="middle"
                          >
                            {RELATION_LABEL[e.kind] ?? e.kind.replace(/_/g, ' ')}
                            {e.strength != null ? ` · ${e.strength.toFixed(2)}` : ''}
                          </text>
                        )}
                      </g>
                    );
                  })}
                  {graph.nodes.map((n) => {
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
                          fill={isCenter ? 'var(--interactive)' : KIND_COLOR[n.kind] ?? 'var(--z-slate)'}
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
            <div
              className="row gap12"
              style={{
                padding: '10px 16px',
                borderTop: '1px solid var(--border-subtle)',
                fontSize: 10.5,
                flexWrap: 'wrap',
              }}
            >
              {Object.entries(RELATION_LABEL).map(([k, l]) => (
                <span key={k} className="row gap6">
                  <span style={{ width: 14, height: 0, borderTop: `3px solid ${edgeColor(k)}` }} />
                  {l}
                </span>
              ))}
              <span className="grow" />
              <span className="row gap6">
                <span style={{ width: 16, height: 0, borderTop: '2px dashed var(--text-tertiary)' }} />
                AI-proposed / latent
              </span>
              <span className="muted">· thickness ∝ strength · hover an edge for the why</span>
            </div>
          </div>
          <div style={{ display: 'grid', gap: 14 }}>
            {/* Relationships you may be missing — the headline: the most novel hidden links */}
            <div className="card pad" style={{ borderColor: '#8b5cf6' }}>
              <div className="row gap8" style={{ marginBottom: 4 }}>
                <Icon n="sparkles" s={15} style={{ color: '#8b5cf6' }} />
                <div className="h3">Relationships you may be missing</div>
              </div>
              <div className="muted" style={{ fontSize: 10.5, marginBottom: 10 }}>
                Co-delivered far more than chance, yet hidden by the catalogue structure. Ranked by
                novelty (cross-pillar, not already linked). Grounded inference — promote in Change flags.
              </div>
              {discover.isLoading && (
                <div className="muted" style={{ fontSize: 12 }}>Mining the corpus…</div>
              )}
              {!discover.isLoading && globalLatent.length === 0 && (
                <div className="muted" style={{ fontSize: 12 }}>
                  No above-chance co-delivery links yet. They appear once the Jira corpus is carried.
                </div>
              )}
              <div style={{ display: 'grid', gap: 7 }}>
                {globalLatent.slice(0, 8).map((l: LatentEdge, i) => (
                  <div
                    key={i}
                    className="card hov"
                    style={{ padding: '8px 10px', cursor: 'pointer' }}
                    onClick={() => setCenter(l.source)}
                    title="Centre the graph on this relationship"
                  >
                    <div className="between" style={{ marginBottom: 3 }}>
                      <CrossBadge crosses={l.crosses} />
                      <span
                        className="num"
                        style={{ fontSize: 11, fontWeight: 700, color: '#8b5cf6' }}
                      >
                        {l.lift.toFixed(1)}× lift
                      </span>
                    </div>
                    <div className="mono" style={{ fontSize: 10.5 }}>
                      {l.source} ~ {l.target}
                    </div>
                    <div className="muted" style={{ fontSize: 10, marginTop: 2 }}>
                      {l.basis}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="card pad">
              <div className="h3" style={{ marginBottom: 8 }}>
                Centre: {kg.data?.name ?? cur ?? '—'}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 6, marginBottom: 10 }}>
                {(
                  [
                    ['siblings', 'structural'],
                    ['pending', 'pending'],
                    ['accepted', 'accepted'],
                    ['latent', 'latent'],
                  ] as const
                ).map(([k, lbl]) => (
                  <div key={k} className="card" style={{ padding: '8px 4px', textAlign: 'center' }}>
                    <div className="num" style={{ fontSize: 16, fontWeight: 700, color: 'var(--interactive)' }}>
                      {kg.data?.stats[k] ?? 0}
                    </div>
                    <div className="muted" style={{ fontSize: 9 }}>{lbl}</div>
                  </div>
                ))}
              </div>
              {latent.length > 0 && (
                <div className="muted" style={{ fontSize: 10.5, marginBottom: 8 }}>
                  This subcap is co-delivered with{' '}
                  <b style={{ color: '#8b5cf6' }}>{latent.length}</b> subcap(s) the tree doesn’t link —
                  shown faint-dashed on the graph.
                </div>
              )}
              <button
                className="btn ghost sm"
                style={{ width: '100%', justifyContent: 'center' }}
                onClick={() => go('subcap/' + cur)}
              >
                Open subcap <Icon n="arrowR" s={13} />
              </button>
            </div>

            <div className="card pad" style={{ borderColor: 'var(--border-medium)' }}>
              <div className="h3" style={{ marginBottom: 8 }}>
                Pending edges ({kg.data?.stats.pending ?? 0})
              </div>
              {(kg.data?.pending ?? []).length > 0 ? (
                <div style={{ display: 'grid', gap: 7, marginBottom: 10 }}>
                  {(kg.data?.pending ?? []).map((e, i) => (
                    <div key={i} className="card" style={{ padding: '8px 10px' }}>
                      <div className="between" style={{ marginBottom: 4 }}>
                        <span className="row gap6">
                          <span className="claim hypothesis">AI proposed</span>
                          <CrossBadge crosses={e.crosses} />
                        </span>
                        {e.strength != null && (
                          <span
                            className="num"
                            style={{ fontSize: 11, fontWeight: 700, color: edgeColor(e.kind) }}
                          >
                            {e.strength.toFixed(2)}
                          </span>
                        )}
                      </div>
                      <div className="mono" style={{ fontSize: 10.5 }}>
                        {e.source} → {e.target}
                      </div>
                      <div className="muted" style={{ fontSize: 10.5, marginTop: 2 }}>
                        {e.basis ?? (RELATION_LABEL[e.kind] ?? e.kind.replace(/_/g, ' '))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="muted" style={{ fontSize: 12 }}>
                  AI-proposed Layer-B edges queue here for review before commit. Resolve them in the
                  Change flags inbox — nothing is written as fact ungated.
                </div>
              )}
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
      )}
    </Page>
  );
}
