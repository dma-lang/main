// Knowledge graph (B3 · admin) — the structural relationships the flat catalogue hides, wired to
// GET /api/catalogue/{v}/kg?subcap=. Layer A (solid) is a DETERMINISTIC projection of the link
// tables (platforms used, offerings mapped, sibling subcaps sharing a platform) — every edge traces
// to a real row. Layer B (dashed) are AI-proposed pending_edges, never rendered as fact and gated
// in Change flags. Admin-only. Ported from the prototype KnowledgeGraph.
import { useMemo, useState } from 'react';

import type { KgNode } from '../api/client';
import { useKg, useSubcaps } from '../api/queries';
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

export function KnowledgeGraph() {
  const ui = useUi();
  const isAdmin = useUi((s) => s.adminView);
  const subs = useSubcaps(ui.version);
  const [layer, setLayer] = useState('full');
  const [center, setCenter] = useState('');

  const options = (subs.data ?? []).slice(0, 40).map((x) => ({
    v: x.id,
    l: x.id + ' · ' + x.name.slice(0, 20),
  }));
  const cur = center || options[0]?.v || '';
  const kg = useKg(ui.version, isAdmin ? cur : null);

  const showB = layer !== 'A';
  const edges = kg.data?.edges ?? [];
  const pending = showB ? kg.data?.pending ?? [] : [];
  const centerId = kg.data?.center ?? '';
  // Only draw nodes reachable by a currently-visible edge (or the centre), so toggling to
  // Deterministic doesn't leave a Layer-B-only neighbour floating with no edge.
  const visibleNodes = useMemo(() => {
    const vis = showB
      ? [...(kg.data?.edges ?? []), ...(kg.data?.pending ?? [])]
      : kg.data?.edges ?? [];
    const connected = new Set<string>([kg.data?.center ?? '']);
    vis.forEach((e) => {
      connected.add(e.source);
      connected.add(e.target);
    });
    return (kg.data?.nodes ?? []).filter((n) => connected.has(n.id));
  }, [kg.data, showB]);

  // Radial layout over the visible nodes: centre in the middle, neighbours evenly spaced on a ring.
  const layout = useMemo(() => {
    const W = 620;
    const H = 460;
    const cx = W / 2;
    const cy = H / 2;
    const neighbours = visibleNodes.filter((n) => n.id !== centerId);
    const pos = new Map<string, { x: number; y: number }>();
    pos.set(centerId, { x: cx, y: cy });
    neighbours.forEach((n, i) => {
      const a = (i / Math.max(1, neighbours.length)) * 2 * Math.PI - Math.PI / 2;
      const r = n.kind === 'subcap' ? 200 : 150;
      pos.set(n.id, { x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r });
    });
    return { W, H, pos };
  }, [visibleNodes, centerId]);

  const nodeById = new Map(visibleNodes.map((n) => [n.id, n]));
  const onNode = (n: KgNode) => {
    if (n.kind === 'subcap') openPeek(n.id);
    else if (n.kind === 'platform') go('platforms');
  };

  return (
    <Page
      eyebrow="B · Catalogue tools · admin"
      title="Knowledge graph"
      intro="Reveal the structural relationships the flat catalogue hides. Solid edges are deterministic (Layer A); dashed orange edges are AI-proposed (semantic-similarity / shared-feature), gated in the Change flags inbox before commit."
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
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 18, alignItems: 'start' }}>
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ padding: 12 }}>
              {kg.isLoading && <div className="muted" style={{ fontSize: 12, padding: 12 }}>Projecting the neighbourhood…</div>}
              {kg.data && visibleNodes.length <= 1 && (
                <Empty
                  icon="graph"
                  title="No structural edges for this subcap"
                  desc="This subcap has no platform, offering or shared-platform links in the catalogue yet. Pick another centre, or open it to add platform mappings."
                />
              )}
              {kg.data && visibleNodes.length > 1 && (
                <svg width="100%" viewBox={`0 0 ${layout.W} ${layout.H}`} style={{ display: 'block' }}>
                  {[...edges, ...pending].map((e, i) => {
                    const a = layout.pos.get(e.source);
                    const b = layout.pos.get(e.target);
                    if (!a || !b) return null;
                    const isB = e.layer === 'B_proposed';
                    return (
                      <line
                        key={i}
                        x1={a.x}
                        y1={a.y}
                        x2={b.x}
                        y2={b.y}
                        stroke={isB ? 'var(--z-orange)' : 'var(--border-medium)'}
                        strokeWidth={isB ? 1.5 : 1.5}
                        strokeDasharray={isB ? '5 4' : undefined}
                      />
                    );
                  })}
                  {visibleNodes.map((n) => {
                    const p = layout.pos.get(n.id);
                    if (!p) return null;
                    const isCenter = n.id === kg.data!.center;
                    const r = isCenter ? 26 : n.kind === 'subcap' ? 18 : 14;
                    return (
                      <g key={n.id} style={{ cursor: 'pointer' }} onClick={() => onNode(n)}>
                        <circle
                          cx={p.x}
                          cy={p.y}
                          r={r}
                          fill={isCenter ? 'var(--interactive)' : KIND_COLOR[n.kind] ?? 'var(--z-slate)'}
                          stroke="var(--surface-base)"
                          strokeWidth="2"
                          opacity={isCenter ? 1 : 0.88}
                        />
                        <text
                          x={p.x}
                          y={p.y + r + 11}
                          fontSize="9"
                          fill="var(--text-secondary)"
                          textAnchor="middle"
                        >
                          {n.label.length > 18 ? n.label.slice(0, 17) + '…' : n.label}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              )}
            </div>
            <div
              className="row gap16"
              style={{ padding: '10px 16px', borderTop: '1px solid var(--border-subtle)', fontSize: 11 }}
            >
              {Object.entries(KIND_COLOR).map(([k, c]) => (
                <span key={k} className="row gap6">
                  <span className="pilldot" style={{ borderRadius: '50%', width: 10, height: 10, background: c }} />
                  {k}
                </span>
              ))}
              <span className="grow" />
              <span className="row gap6">
                <span style={{ width: 16, height: 0, borderTop: '2px dashed var(--z-orange)' }} />
                AI-proposed
              </span>
            </div>
          </div>
          <div style={{ display: 'grid', gap: 14 }}>
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
            <div className="card pad">
              <div className="h3" style={{ marginBottom: 8 }}>
                Neighbour subcaps
              </div>
              <div style={{ display: 'grid', gap: 6 }}>
                {visibleNodes
                  .filter((n) => n.kind === 'subcap' && n.id !== centerId)
                  .map((n) => (
                    <div
                      key={n.id}
                      className="sclink mono"
                      style={{ fontSize: 11.5 }}
                      onClick={() => openPeek(n.id)}
                    >
                      {n.id} · {n.label.slice(0, 22)}
                    </div>
                  ))}
                {nodeById && (kg.data?.stats.siblings ?? 0) === 0 && (
                  <div className="muted" style={{ fontSize: 12 }}>
                    No subcap shares a platform with this one yet.
                  </div>
                )}
              </div>
            </div>
            <div className="card pad" style={{ borderColor: 'var(--border-medium)' }}>
              <div className="h3" style={{ marginBottom: 8 }}>
                Pending edges ({kg.data?.stats.pending ?? 0})
              </div>
              <div className="muted" style={{ fontSize: 12 }}>
                AI-proposed Layer-B edges queue here for review before commit. Resolve them in the
                Change flags inbox — nothing is written as fact ungated.
              </div>
              <button
                className="btn primary sm"
                style={{ width: '100%', justifyContent: 'center', marginTop: 10 }}
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
