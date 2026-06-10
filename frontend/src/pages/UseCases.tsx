// Use case explorer (B2) — the catalogue's actual use cases, not just their tags. Ported from the
// prototype, wired to GET /api/catalogue/{v}/use-cases (server-filtered + paginated, with archetype
// facets). Narrow by pillar + capability area, filter by type or search text; open the owning subcap.
import { useEffect, useMemo, useState } from 'react';

import { useSubcaps, useUseCases } from '../api/queries';
import { Dropdown, Empty, Page, PillarDot } from '../components/primitives';
import { go } from '../lib/events';
import { PILLAR_COLORS } from '../lib/helpers';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const PILLARS: [string, string][] = [
  ['all', 'All'],
  ['P1', 'P1'],
  ['P2', 'P2'],
  ['P3', 'P3'],
  ['P4', 'P4'],
];
const PER = 12;

export function UseCases() {
  const version = useUi((s) => s.version);
  const [pillar, setPillar] = useState('all');
  const [cat, setCat] = useState('all');
  const [arch, setArch] = useState('all');
  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);

  // Debounced search.
  useEffect(() => {
    const t = setTimeout(() => setQ(qInput), 300);
    return () => clearTimeout(t);
  }, [qInput]);
  useEffect(() => setPage(1), [pillar, cat, arch, q]);

  const allSubs = useSubcaps(version);
  const subs = useMemo(() => allSubs.data ?? [], [allSubs.data]);

  // Capability-area options derive from the subcap tree (filtered by pillar), like the prototype.
  const catOpts = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of subs) if (pillar === 'all' || s.pillar === pillar) m.set(s.cat_id, s.cat_name);
    return [
      { v: 'all', l: 'All capability areas' },
      ...[...m.entries()].map(([v, l]) => ({ v, l })),
    ];
  }, [subs, pillar]);
  const scopeCount = useMemo(
    () =>
      subs.filter(
        (s) => (pillar === 'all' || s.pillar === pillar) && (cat === 'all' || s.cat_id === cat),
      ).length,
    [subs, pillar, cat],
  );

  const res = useUseCases(version, {
    pillar: pillar === 'all' ? '' : pillar,
    category: cat === 'all' ? '' : cat,
    archetype: arch === 'all' ? '' : arch,
    q,
    page,
    size: PER,
  });
  const data = res.data;
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PER));

  const archOpts = useMemo(
    () => [
      { v: 'all', l: 'All use-case types' },
      ...(data?.archetypes ?? []).map((a) => ({ v: a.archetype, l: `${a.archetype} (${a.count})` })),
    ],
    [data?.archetypes],
  );

  return (
    <Page
      eyebrow="B · Catalogue tools"
      title="Use case explorer"
      intro={
        <>
          Browse the catalogue's <b>actual use cases</b>, not just their tags. Narrow by pillar and
          capability area, filter by type or search the text, and open the owning subcap from any
          card.
        </>
      }
    >
      <div className="card pad" style={{ marginBottom: 16 }}>
        <div className="row gap10" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
          <div className="pillseg">
            {PILLARS.map(([v, l]) => (
              <button
                key={v}
                className={pillar === v ? 'on' : ''}
                onClick={() => {
                  setPillar(v);
                  setCat('all');
                }}
              >
                {v !== 'all' && <span className="dot" style={{ background: PILLAR_COLORS[v] }} />}
                {l}
              </button>
            ))}
          </div>
          <Dropdown value={cat} icon="filter" options={catOpts} onChange={setCat} />
          <Dropdown value={arch} options={archOpts} onChange={setArch} />
          <div className="searchbox" style={{ flex: 1, minWidth: 200 }}>
            <Icon n="search" s={15} />
            <input
              placeholder="Search use-case text…"
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
            />
            {qInput && (
              <button className="linkbtn" onClick={() => setQInput('')}>
                <Icon n="x" s={14} />
              </button>
            )}
          </div>
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
          Showing <b style={{ color: 'var(--text-primary)' }}>{total}</b> use cases across{' '}
          {scopeCount} subcaps
          {pillar !== 'all' ? ' in ' + pillar : ''}
          {cat !== 'all' ? ' · ' + (catOpts.find((o) => o.v === cat)?.l ?? '') : ''}.
        </div>
      </div>

      {items.length ? (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 10 }}>
            {items.map((u) => (
              <div
                key={u.use_case_id}
                className="card hov"
                style={{
                  padding: '13px 15px',
                  cursor: 'pointer',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 9,
                }}
                onClick={() => go('subcap/' + u.subcap_id)}
              >
                <div className="row gap6" style={{ flexWrap: 'wrap' }}>
                  <span className="chip blue" style={{ fontWeight: 700 }}>
                    {u.archetype ?? 'use case'}
                  </span>
                  <span className="mono muted" style={{ fontSize: 10, marginLeft: 'auto' }}>
                    {u.use_case_id}
                  </span>
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                  {u.description}
                </div>
                <div className="row gap6" style={{ marginTop: 'auto', alignItems: 'center' }}>
                  <PillarDot p={u.pillar} s={7} />
                  <span className="mono" style={{ fontSize: 10.5, color: 'var(--interactive)', fontWeight: 600 }}>
                    {u.subcap_id}
                  </span>
                  <span
                    className="muted"
                    style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {u.subcap_name} · {u.category}
                  </span>
                </div>
              </div>
            ))}
          </div>
          <div className="row gap10" style={{ justifyContent: 'center', marginTop: 16, alignItems: 'center' }}>
            <button className="btn subtle sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              <Icon n="chevL" s={14} /> Prev
            </button>
            <span className="muted" style={{ fontSize: 12 }}>
              Page {page} of {pages}
            </span>
            <button className="btn subtle sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
              Next <Icon n="chevR" s={14} />
            </button>
          </div>
        </>
      ) : (
        <Empty
          icon="puzzle"
          title="No use cases match"
          desc="Try a different pillar, capability area, type or search term."
        />
      )}
    </Page>
  );
}
