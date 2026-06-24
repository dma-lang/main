// Capability workbench (A2) — the prototype's Capability explorer: a four-column drill
// (pillar -> category -> L1 cluster -> subcap), each column filtering the next, with a debounced
// search that swaps to a flat result list. Wired to GET /api/catalogue/{v}/subcaps (the tree) and
// /subcaps/{id} (the selected detail). Arrival from Mission control / the header pillar control sets
// the focused pillar and never resets context (AppFlow context-propagation rule). "Open deep dive"
// routes to the subcap deep-dive surface.
import { type ReactNode, useEffect, useMemo, useState } from 'react';

import { useSubcap, useSubcaps } from '../api/queries';
import { LifeChip, Page, PillarDot, Tier } from '../components/primitives';
import { go, toast } from '../lib/events';
import { PILLAR_SHORT } from '../lib/helpers';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const PILLARS = ['P1', 'P2', 'P3', 'P4'];

function Col({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
      <div className="eyebrow" style={{ padding: '0 4px 8px' }}>
        {title}
      </div>
      <div className="card" style={{ flex: 1, overflowY: 'auto', maxHeight: 520, padding: 5 }}>
        {children}
      </div>
    </div>
  );
}

function Row({
  on,
  onClick,
  children,
  count,
}: {
  on?: boolean;
  onClick: () => void;
  children: ReactNode;
  count?: number | null;
}) {
  return (
    <div
      className="navitem"
      style={{
        fontWeight: on ? 600 : 500,
        background: on ? 'var(--surface-overlay)' : '',
        color: on ? 'var(--text-primary)' : '',
      }}
      onClick={onClick}
    >
      <span
        style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
      >
        {children}
      </span>
      {count != null && <span className="ncount">{count}</span>}
      <Icon n="chevR" s={13} style={{ color: 'var(--text-disabled)' }} />
    </div>
  );
}

export function CapabilityWorkbench() {
  const version = useUi((s) => s.version);
  const ctxPillar = useUi((s) => s.pillar);
  const ctxSv = useUi((s) => s.sv); // header subvertical scopes the tree, like mission control
  const subcaps = useSubcaps(version, ctxSv);
  const all = useMemo(() => subcaps.data ?? [], [subcaps.data]);
  const svActive = !!ctxSv && ctxSv !== 'all';

  const [pillar, setPillar] = useState<string>(ctxPillar === 'all' ? 'P1' : ctxPillar);
  const [cat, setCat] = useState<string | null>(null);
  const [cluster, setCluster] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [q, setQ] = useState('');

  useEffect(() => {
    if (ctxPillar !== 'all') {
      setPillar(ctxPillar);
      setCat(null);
      setCluster(null);
      setSel(null);
    }
  }, [ctxPillar]);

  const pillarCount = useMemo(() => {
    const m: Record<string, number> = { P1: 0, P2: 0, P3: 0, P4: 0 };
    for (const s of all) if (m[s.pillar] != null) m[s.pillar] += 1;
    return m;
  }, [all]);

  const cats = useMemo(() => {
    const m = new Map<string, { id: string; name: string; n: number }>();
    for (const s of all) {
      if (s.pillar !== pillar) continue;
      const e = m.get(s.cat_id) ?? { id: s.cat_id, name: s.cat_name, n: 0 };
      e.n += 1;
      m.set(s.cat_id, e);
    }
    return [...m.values()];
  }, [pillar, all]);

  const clusters = useMemo(() => {
    if (!cat) return [];
    const m = new Map<string, number>();
    for (const s of all) if (s.cat_id === cat) m.set(s.cluster, (m.get(s.cluster) ?? 0) + 1);
    return [...m.entries()].map(([name, n]) => ({ name, n }));
  }, [cat, all]);

  const leaves = useMemo(
    () => (cluster ? all.filter((s) => s.cat_id === cat && s.cluster === cluster) : []),
    [cluster, cat, all],
  );

  const results = useMemo(() => {
    if (q.trim().length < 2) return null;
    const t = q.toLowerCase();
    return all
      .filter(
        (s) =>
          s.name.toLowerCase().includes(t) ||
          s.id.toLowerCase().includes(t) ||
          s.cluster.toLowerCase().includes(t),
      )
      .slice(0, 40);
  }, [q, all]);

  const selNode = useMemo(() => all.find((s) => s.id === sel) ?? null, [all, sel]);
  const detail = useSubcap(version, sel);
  const d = detail.data;

  return (
    <Page
      eyebrow="A · Explore"
      title="Capability workbench"
      intro={
        <>
          Drill from pillar to a single subcap — each column filters the next — then open its deep
          dive for use cases and user stories. <b>{all.length} subcaps</b> in the {version || '—'}{' '}
          catalogue{svActive ? ` · scoped to the ${ctxSv} value chain` : ''}.
        </>
      }
    >
      <div className="searchbox" style={{ marginBottom: 18, maxWidth: 520 }}>
        <Icon n="search" s={16} />
        <input
          placeholder="Search Sub_Cap_Name, ID or L1 capability… (debounced)"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {q && (
          <button className="linkbtn" onClick={() => setQ('')}>
            <Icon n="x" s={14} />
          </button>
        )}
      </div>

      {results ? (
        <div className="card" style={{ padding: 6, maxWidth: 760 }}>
          {results.length === 0 ? (
            <div className="muted" style={{ padding: 14, fontSize: 12 }}>
              No matches — try a subcap name, ID or capability cluster.
            </div>
          ) : (
            results.map((s) => (
              <div key={s.id} className="navitem" onClick={() => go('subcap/' + s.id)}>
                <PillarDot p={s.pillar} s={7} />
                <span
                  style={{
                    flex: 1,
                    minWidth: 0,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {s.name}
                </span>
                <span className="mono muted" style={{ fontSize: 11 }}>
                  {s.id}
                </span>
                <Icon n="arrowR" s={13} />
              </div>
            ))
          )}
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr 1fr 1.1fr',
            gap: 12,
            alignItems: 'stretch',
          }}
        >
          <Col title="Pillar">
            {PILLARS.map((p) => (
              <Row
                key={p}
                on={pillar === p}
                count={pillarCount[p]}
                onClick={() => {
                  setPillar(p);
                  setCat(null);
                  setCluster(null);
                  setSel(null);
                }}
              >
                <span className="row gap8">
                  <PillarDot p={p} />
                  {p} · {PILLAR_SHORT[p]}
                </span>
              </Row>
            ))}
          </Col>

          <Col title="Category">
            {cats.map((c) => (
              <Row
                key={c.id}
                on={cat === c.id}
                count={c.n}
                onClick={() => {
                  setCat(c.id);
                  setCluster(null);
                  setSel(null);
                }}
              >
                {c.name}
              </Row>
            ))}
          </Col>

          <Col title="L1 capability cluster">
            {!cat ? (
              <div className="muted" style={{ padding: 14, fontSize: 12 }}>
                Pick a category.
              </div>
            ) : (
              clusters.map((c) => (
                <Row
                  key={c.name}
                  on={cluster === c.name}
                  count={c.n}
                  onClick={() => {
                    setCluster(c.name);
                    setSel(null);
                  }}
                >
                  {c.name}
                </Row>
              ))
            )}
          </Col>

          <Col title="Sub_Cap">
            {!cluster ? (
              <div className="muted" style={{ padding: 14, fontSize: 12 }}>
                Pick a cluster.
              </div>
            ) : (
              leaves.map((s) => (
                <div
                  key={s.id}
                  className="navitem"
                  style={{ background: sel === s.id ? 'var(--surface-overlay)' : '' }}
                  onClick={() => setSel(s.id)}
                >
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span
                      style={{
                        display: 'block',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {s.name}
                    </span>
                    <span className="mono muted" style={{ fontSize: 10.5 }}>
                      {s.id}
                    </span>
                  </span>
                  {s.is_new && (
                    <span className="chip teal" style={{ padding: '1px 5px' }}>
                      new
                    </span>
                  )}
                </div>
              ))
            )}
          </Col>
        </div>
      )}

      {sel && !results && selNode && (
        <div
          className="card pad fade-in"
          style={{ marginTop: 18, maxWidth: 680, borderColor: 'var(--border-medium)' }}
        >
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Selected
          </div>
          <div className="between">
            <div className="h1" style={{ fontSize: 20 }}>
              {selNode.name}
            </div>
            <LifeChip life={d?.lifecycle_state ?? selNode.life} />
          </div>
          <div className="row gap8 mt8">
            <span className="mono muted">{selNode.id}</span>
            {d?.tier && <Tier t={d.tier} />}
            <span className="chip soft">{selNode.cat_name}</span>
          </div>
          <div className="muted" style={{ fontSize: 13, margin: '12px 0', lineHeight: 1.55 }}>
            {d?.description ?? (detail.isLoading ? 'Loading detail…' : 'No description in this version.')}
          </div>
          <div className="row gap16" style={{ fontSize: 12 }}>
            <span className="muted" title="Share of core fields populated on this subcap">
              Record coverage{' '}
              <b style={{ color: 'var(--text-primary)' }}>
                {Math.round((d?.completeness ?? 0) * 100)}%
              </b>
            </span>
            <span className="muted">{d?.n_use_cases ?? 0} use cases</span>
            <span className="muted">{d?.n_stories ?? 0} stories</span>
            <span className="muted">{d?.n_platforms ?? 0} platforms</span>
          </div>
          <div className="row gap8 mt16">
            <button className="btn primary sm" onClick={() => go('subcap/' + selNode.id)}>
              Open deep dive <Icon n="arrowR" s={14} />
            </button>
            <button
              className="btn ghost sm"
              onClick={() => toast('Recent AI activity appears once the evidence pipeline (F7) is live.')}
            >
              Show recent AI activity
            </button>
          </div>
        </div>
      )}
    </Page>
  );
}
