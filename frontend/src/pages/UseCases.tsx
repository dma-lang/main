// Use case explorer (B2) — the catalogue's actual use cases, RANKED by the Jira stories that deliver
// them. Aligned to the prototype's V2: a most-delivered-archetype leaderboard, a delivery-ranked list
// (story count is the headline), a Top-delivered/A–Z sort, and a drawer that opens the owning subcap's
// delivering stories. Wired to GET /api/catalogue/{v}/use-cases (server-filtered/sorted/paginated)
// + /subcaps/{id}/stories for the drawer.
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import type { UseCaseRow } from '../api/client';
import { useSubcaps, useUseCaseStories, useUseCases } from '../api/queries';
import { Dropdown, Empty, Page, PillarDot, Seg } from '../components/primitives';
import { ClientChip, StoryDetail } from '../components/StoryDetail';
import { go } from '../lib/events';
import { heatBg, PILLAR_COLORS } from '../lib/helpers';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const PILLARS: [string, string][] = [
  ['all', 'All'],
  ['P1', 'P1'],
  ['P2', 'P2'],
  ['P3', 'P3'],
  ['P4', 'P4'],
];
const PER = 10;

// Drawer — the use case's owning subcap, its delivering Jira stories, and links onward.
function UseCaseDrawer({ version, uc, onClose }: { version: string; uc: UseCaseRow; onClose: () => void }) {
  const stories = useUseCaseStories(version, uc.use_case_id);
  const rows = stories.data?.items ?? [];
  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <div className="drawer" style={{ width: 460 }}>
        <div className="drawer-head">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="eyebrow" style={{ marginBottom: 4 }}>
              Use case · {uc.name ?? uc.archetype ?? 'use case'}
              {uc.is_new && <span className="chip green" style={{ marginLeft: 6 }}>new</span>}
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.4 }}>{uc.description}</div>
          </div>
          <button className="modal-x" onClick={onClose} aria-label="close">
            <Icon n="x" s={14} />
          </button>
        </div>
        <div className="drawer-body">
          <div className="between" style={{ marginBottom: 14 }}>
            <div>
              <span className="num" style={{ fontSize: 26, fontWeight: 700, color: 'var(--interactive)' }}>
                {uc.n_stories.toLocaleString()}
                <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}> matched stories</span>
              </span>
              <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                of {uc.subcap_stories.toLocaleString()} delivered to the owning subcap
              </div>
            </div>
            {uc.maturity && <span className="tierchip">{uc.maturity}</span>}
          </div>

          <button
            className="card hov"
            onClick={() => go('subcap/' + uc.subcap_id)}
            style={{ padding: '11px 13px', cursor: 'pointer', textAlign: 'left', width: '100%', marginBottom: 16 }}
          >
            <div className="row gap8" style={{ marginBottom: 3 }}>
              <PillarDot p={uc.pillar} s={7} />
              <span style={{ fontSize: 13, fontWeight: 600 }}>{uc.subcap_name}</span>
            </div>
            <div className="row gap8">
              <span className="mono muted" style={{ fontSize: 10.5 }}>
                {uc.subcap_id}
              </span>
              {uc.cluster && (
                <span className="muted" style={{ fontSize: 11 }}>
                  {uc.category} · {uc.cluster}
                </span>
              )}
              <Icon n="arrowR" s={12} style={{ color: 'var(--interactive)', marginLeft: 'auto' }} />
            </div>
          </button>

          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Matched stories {rows.length > 0 && <span className="muted">· top {rows.length}</span>}
          </div>
          {stories.isLoading ? (
            <div className="muted" style={{ fontSize: 12 }}>
              Loading…
            </div>
          ) : rows.length === 0 ? (
            <div className="muted" style={{ fontSize: 12 }}>
              No Jira story matched specifically to this use case — its subcap's delivery is general.
            </div>
          ) : (
            <div style={{ display: 'grid', gap: 7 }}>
              {rows.map((st) => (
                <div key={st.story_key} className="card" style={{ padding: '9px 11px' }}>
                  {/* the resolved client leads (client_name + story_key id + project secondary) */}
                  <div className="row wrap gap6" style={{ marginBottom: 5 }}>
                    <ClientChip story={st} idFirst size={9.5} />
                  </div>
                  <div className="muted" style={{ fontSize: 11.5, lineHeight: 1.45, marginBottom: 6 }}>
                    {st.summary}
                  </div>
                  {/* narrative + collapsible acceptance-criteria / solution-design */}
                  <StoryDetail story={st} showClient={false} />
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="drawer-head" style={{ borderTop: '1px solid var(--border-subtle)', borderBottom: 'none' }}>
          <button className="btn ghost sm" onClick={() => go('subcap/' + uc.subcap_id)}>
            Open owning subcap
          </button>
          <button className="btn subtle sm" onClick={() => go('stories')}>
            Story library <Icon n="arrowR" s={12} />
          </button>
        </div>
      </div>
    </>
  );
}

export function UseCases() {
  const version = useUi((s) => s.version);
  const [sp] = useSearchParams();
  // arriving from a platform's use-case (or any deep link) pre-applies archetype/pillar filters
  const [pillar, setPillar] = useState(() => sp.get('pillar') ?? 'all');
  const [cat, setCat] = useState('all');
  const [arch, setArch] = useState(() => sp.get('archetype') ?? 'all');
  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('delivery');
  const [page, setPage] = useState(1);
  const [drill, setDrill] = useState<UseCaseRow | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setQ(qInput), 300);
    return () => clearTimeout(t);
  }, [qInput]);
  useEffect(() => setPage(1), [pillar, cat, arch, q, sort]);
  // re-apply nav params if they change while the page is already mounted
  useEffect(() => {
    const a = sp.get('archetype');
    const p = sp.get('pillar');
    if (a) setArch(a);
    if (p) setPillar(p);
  }, [sp]);

  const allSubs = useSubcaps(version);
  const subs = useMemo(() => allSubs.data ?? [], [allSubs.data]);

  const catOpts = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of subs) if (pillar === 'all' || s.pillar === pillar) m.set(s.cat_id, s.cat_name);
    return [{ v: 'all', l: 'All capability areas' }, ...[...m.entries()].map(([v, l]) => ({ v, l }))];
  }, [subs, pillar]);

  const res = useUseCases(version, {
    pillar: pillar === 'all' ? '' : pillar,
    category: cat === 'all' ? '' : cat,
    archetype: arch === 'all' ? '' : arch,
    q,
    sort,
    page,
    size: PER,
  });
  const data = res.data;
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PER));

  // the "All use-case types" dropdown is removed — the most-delivered archetype leaderboard below
  // IS the type filter (click a bar to filter, click again to clear).
  const board = useMemo(() => (data?.archetypes ?? []).slice(0, 6), [data?.archetypes]);
  const boardMax = Math.max(1, ...board.map((a) => a.n_stories));
  // L1-capability grouping: the categories in scope, ranked by matched delivery (the "matched use
  // cases by capability" overview). Shown when no specific capability is selected; click to drill in.
  const cats = useMemo(() => data?.categories ?? [], [data?.categories]);
  const catMax = Math.max(1, ...cats.map((c) => c.n_stories));

  return (
    <Page
      eyebrow="B · Catalogue tools"
      title="Use case explorer"
      intro={
        <>
          Browse the catalogue's <b>actual use cases</b>, ranked by how many real Jira stories deliver
          them. Narrow by pillar, area, type or text; open any use case to see the stories behind it.
        </>
      }
      actions={
        <Seg
          options={[
            { v: 'delivery', l: 'Top delivered' },
            { v: 'alpha', l: 'A–Z' },
          ]}
          value={sort}
          onChange={setSort}
        />
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
          <div className="searchbox" style={{ flex: 1, minWidth: 200 }}>
            <Icon n="search" s={15} />
            <input placeholder="Search use-case text…" value={qInput} onChange={(e) => setQInput(e.target.value)} />
            {qInput && (
              <button className="linkbtn" onClick={() => setQInput('')}>
                <Icon n="x" s={14} />
              </button>
            )}
          </div>
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
          <b style={{ color: 'var(--text-primary)' }}>{total.toLocaleString()}</b> use cases · ranked by
          delivery
          {pillar !== 'all' ? ' · ' + pillar : ''}
          {cat !== 'all' ? ' · ' + (catOpts.find((o) => o.v === cat)?.l ?? '') : ''}.
        </div>
      </div>

      {board.length > 0 && (
        <div className="card pad" style={{ marginBottom: 16 }}>
          <div className="eyebrow" style={{ marginBottom: 12 }}>
            Most-delivered use-case types
          </div>
          <div style={{ display: 'grid', gap: 8 }}>
            {board.map((a) => {
              const on = arch === a.archetype;
              return (
                <button
                  key={a.archetype}
                  onClick={() => setArch((cur) => (cur === a.archetype ? 'all' : a.archetype))}
                  className="row gap10"
                  style={{
                    border: 'none',
                    background: on ? 'var(--surface-overlay)' : 'none',
                    cursor: 'pointer',
                    padding: '4px 6px',
                    borderRadius: 6,
                    textAlign: 'left',
                  }}
                >
                  <span className="chip blue" style={{ width: 150, justifyContent: 'flex-start', flex: 'none' }}>
                    {a.archetype}
                  </span>
                  <div className="bartrack" style={{ flex: 1 }}>
                    <div className="barfill" style={{ width: `${(a.n_stories / boardMax) * 100}%`, background: heatBg(0.3 + 0.7 * (a.n_stories / boardMax)) }} />
                  </div>
                  <span className="num" style={{ fontSize: 12, fontWeight: 700, width: 70, textAlign: 'right', flex: 'none' }}>
                    {a.n_stories.toLocaleString()}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {cat === 'all' && cats.length > 0 && (
        <div className="card pad" style={{ marginBottom: 16 }}>
          <div className="eyebrow" style={{ marginBottom: 12 }}>
            Capability areas (L1) · matched delivery — click to scope
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
              gap: 8,
            }}
          >
            {cats.map((c) => (
              <button
                key={c.category_id}
                onClick={() => setCat(c.category_id)}
                className="card hov"
                style={{ padding: '10px 12px', cursor: 'pointer', textAlign: 'left' }}
              >
                <div className="row gap6" style={{ marginBottom: 5 }}>
                  <span className="dot" style={{ background: PILLAR_COLORS[c.pillar] }} />
                  <span style={{ fontSize: 12.5, fontWeight: 600 }}>{c.category}</span>
                </div>
                <div className="bartrack" style={{ marginBottom: 5 }}>
                  <div
                    className="barfill"
                    style={{
                      width: `${(c.n_stories / catMax) * 100}%`,
                      background: heatBg(0.3 + 0.7 * (c.n_stories / catMax)),
                    }}
                  />
                </div>
                <div className="muted" style={{ fontSize: 10.5 }}>
                  <b style={{ color: 'var(--text-primary)' }}>{c.n_stories.toLocaleString()}</b> matched ·{' '}
                  {c.use_cases} use cases
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {items.length ? (
        <>
          <div style={{ display: 'grid', gap: 8 }}>
            {items.map((u) => (
              <button
                key={u.use_case_id}
                className="card hov"
                onClick={() => setDrill(u)}
                style={{ padding: 0, cursor: 'pointer', textAlign: 'left', display: 'flex', alignItems: 'stretch' }}
              >
                <div
                  style={{
                    flex: 'none',
                    width: 92,
                    borderRight: '1px solid var(--border-subtle)',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: '12px 8px',
                    background: 'var(--surface-raised)',
                  }}
                >
                  <div className="num" style={{ fontSize: 20, fontWeight: 700, color: 'var(--interactive)' }}>
                    {u.n_stories.toLocaleString()}
                  </div>
                  <div className="muted" style={{ fontSize: 9.5 }}>
                    matched
                  </div>
                  {u.subcap_stories > 0 && (
                    <div className="muted" style={{ fontSize: 8.5, marginTop: 1 }}>
                      of {u.subcap_stories.toLocaleString()}
                    </div>
                  )}
                </div>
                <div style={{ flex: 1, minWidth: 0, padding: '12px 15px' }}>
                  <div className="row gap6" style={{ flexWrap: 'wrap', marginBottom: 6 }}>
                    <span className="chip blue" style={{ fontWeight: 700 }}>
                      {u.name ?? u.archetype ?? 'use case'}
                    </span>
                    {u.is_new && <span className="chip green">new</span>}
                    {u.maturity && <span className="tierchip">{u.maturity}</span>}
                    <span className="mono muted" style={{ fontSize: 10, marginLeft: 'auto' }}>
                      {u.use_case_id}
                    </span>
                  </div>
                  <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 7 }}>
                    {u.description}
                  </div>
                  <div className="row gap6" style={{ alignItems: 'center' }}>
                    <PillarDot p={u.pillar} s={7} />
                    <span className="mono" style={{ fontSize: 10.5, color: 'var(--interactive)', fontWeight: 600 }}>
                      {u.subcap_id}
                    </span>
                    <span
                      className="muted"
                      style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    >
                      {u.subcap_name} · {u.cluster ?? u.category}
                    </span>
                  </div>
                </div>
              </button>
            ))}
          </div>
          <div className="row gap10" style={{ justifyContent: 'center', marginTop: 16, alignItems: 'center' }}>
            <button className="btn subtle sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              <Icon n="chevL" s={14} /> Prev
            </button>
            <span className="muted" style={{ fontSize: 12 }}>
              Page {page} of {pages} · ranked by delivery
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
          desc="Try a broader pillar, capability area, type or search term."
        />
      )}

      {drill && <UseCaseDrawer version={version} uc={drill} onClose={() => setDrill(null)} />}
    </Page>
  );
}
