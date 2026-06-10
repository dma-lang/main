// Story library (C2) — the canonical 14,406 real-client Jira stories (the analysis set). Ported from
// the prototype, wired to GET /api/stories (server-filtered + paginated, with confidence counts and
// the composite quality histogram). Honours the header subvertical filter. Click a row for its
// quality breakdown (ac/sd/ss) and to open the matched subcap.
import { useEffect, useState } from 'react';

import type { StoryLibraryRow } from '../api/client';
import { useStoryLibrary } from '../api/queries';
import { Bar, Dropdown, Empty, Page } from '../components/primitives';
import { go } from '../lib/events';
import { PILLAR_COLORS } from '../lib/helpers';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const PILLARS = ['all', 'P1', 'P2', 'P3', 'P4'];
const CONF_OPTS = [
  { v: 'all', l: 'All confidence' },
  { v: 'HIGH', l: 'HIGH' },
  { v: 'MEDIUM', l: 'MEDIUM' },
  { v: 'LOW', l: 'LOW' },
];
// The corpus split: analysis is Jira-only; the v7 workbooks' synthetic/derived stories are
// visible only behind an explicit, labelled filter (never mixed into analysis).
const SYN_OPTS = [
  { v: 'exclude', l: 'Jira only' },
  { v: 'include', l: 'Jira + synthetic' },
  { v: 'only', l: 'Synthetic only' },
] as const;
type SynMode = (typeof SYN_OPTS)[number]['v'];
const PER = 10;

const confClass = (c: string | null) =>
  c === 'HIGH' ? 'teal' : c === 'MEDIUM' ? 'orange' : 'slate';
const compColor = (v: number) =>
  v >= 2.5 ? 'var(--interactive)' : v >= 1.5 ? 'var(--z-blue)' : 'var(--z-orange)';

function StoryDrill({ s }: { s: StoryLibraryRow }) {
  const scores: [string, number | null][] = [
    ['Acceptance criteria', s.ac_score],
    ['Solution design', s.sd_score],
    ['Story score', s.story_score],
  ];
  return (
    <div className="fade-in" style={{ padding: '12px 16px', background: 'var(--surface-raised)' }}>
      <div className="row gap8" style={{ marginBottom: 12, flexWrap: 'wrap' }}>
        <span className={'chip ' + confClass(s.confidence_level)}>{s.confidence_level} confidence</span>
        {s.is_synthetic && (
          <span className="chip orange" title={'Source: ' + (s.source_system ?? 'synthetic')}>
            synthetic · provisional — not used in analysis
          </span>
        )}
        {s.pillar && <span className="chip soft mono">{s.pillar}</span>}
        {s.sv && <span className="chip soft">{s.sv}</span>}
        <span className="muted" style={{ fontSize: 11.5 }}>
          {s.subcap_name ?? s.subcap_id}
        </span>
        <span className="muted mono" style={{ fontSize: 10.5 }}>
          {s.source_system ?? (s.is_synthetic ? 'synthetic' : 'jira')}
        </span>
      </div>
      <div className="row gap16" style={{ maxWidth: 520, marginBottom: 12 }}>
        {scores.map(([label, v]) => (
          <div key={label} style={{ flex: 1 }}>
            <div className="between" style={{ fontSize: 11, marginBottom: 4 }}>
              <span className="muted">{label}</span>
              <b className="num">{v != null ? v.toFixed(1) : 'n/a'}</b>
            </div>
            <Bar v={v ?? 0} max={5} color={(v ?? 0) >= 3 ? 'var(--interactive)' : 'var(--z-blue)'} />
          </div>
        ))}
      </div>
      <button className="btn primary sm" onClick={() => go('subcap/' + s.subcap_id)}>
        Open matched subcap <Icon n="arrowR" s={14} />
      </button>
    </div>
  );
}

export function StoryLibrary() {
  const sv = useUi((st) => st.sv);
  const [pillar, setPillar] = useState('all');
  const [conf, setConf] = useState('all');
  const [syn, setSyn] = useState<SynMode>('exclude');
  const [minQ, setMinQ] = useState(0);
  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setQ(qInput), 300);
    return () => clearTimeout(t);
  }, [qInput]);
  useEffect(() => setPage(1), [pillar, conf, syn, minQ, sv, q]);

  const res = useStoryLibrary({
    pillar: pillar === 'all' ? '' : pillar,
    conf: conf === 'all' ? '' : conf,
    sv: sv === 'all' ? '' : sv,
    min_composite: minQ,
    q,
    synthetic: syn,
    page,
    size: PER,
  });
  const data = res.data;
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PER));
  const buckets = data?.buckets ?? [0, 0, 0, 0, 0, 0];
  const bmax = Math.max(1, ...buckets);
  const jiraTotal = data?.jira_total ?? 0;
  const synTotal = data?.synthetic_total ?? 0;

  return (
    <Page
      eyebrow="C · Project validation"
      title="Story library"
      intro={
        <>
          The canonical <b>{jiraTotal ? jiraTotal.toLocaleString() : '14,406'} real-client Jira
          stories</b> — the analysis set. The {synTotal ? synTotal.toLocaleString() + ' ' : ''}
          synthetic stories shipped inside the v7 workbooks are excluded from analysis by
          construction; flip the corpus filter to inspect them, always labelled provisional. Filter,
          search and open any story for its quality and match breakdown.
        </>
      }
    >
      <div
        style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 14, marginBottom: 16, alignItems: 'stretch' }}
      >
        <div className="card pad">
          <div className="searchbox" style={{ marginBottom: 14 }}>
            <Icon n="search" s={16} />
            <input
              placeholder="Search story key, summary or subcap name…"
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
            />
            {qInput && (
              <button className="linkbtn" onClick={() => setQInput('')}>
                <Icon n="x" s={14} />
              </button>
            )}
          </div>
          <div className="row wrap gap8">
            <div className="pillseg">
              {PILLARS.map((p) => (
                <button key={p} className={pillar === p ? 'on' : ''} onClick={() => setPillar(p)}>
                  {p !== 'all' && <span className="dot" style={{ background: PILLAR_COLORS[p] }} />}
                  {p === 'all' ? 'All' : p}
                </button>
              ))}
            </div>
            <Dropdown value={conf} options={CONF_OPTS} onChange={setConf} />
            <Dropdown
              value={syn}
              options={[...SYN_OPTS]}
              onChange={(v) => setSyn(v as SynMode)}
            />
            <div className="row gap8">
              <span className="muted" style={{ fontSize: 12 }}>
                Min composite
              </span>
              <input
                type="range"
                min="0"
                max="3"
                step="0.5"
                value={minQ}
                onChange={(e) => setMinQ(+e.target.value)}
                style={{ accentColor: 'var(--z-teal)', width: 90 }}
              />
              <b className="num" style={{ fontSize: 12 }}>
                {minQ.toFixed(1)}
              </b>
            </div>
          </div>
        </div>
        <div className="card pad">
          <div className="between" style={{ marginBottom: 10 }}>
            <span className="eyebrow">Quality distribution</span>
            <b className="num" style={{ fontSize: 13 }}>
              {total}
            </b>
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 5, height: 50 }}>
            {buckets.map((b, i) => (
              <div
                key={i}
                title={`${b} stories`}
                style={{
                  flex: 1,
                  background: i >= 4 ? 'var(--interactive)' : 'var(--surface-overlay)',
                  height: Math.max(3, (b / bmax) * 46),
                  borderRadius: '2px 2px 0 0',
                }}
              />
            ))}
          </div>
          <div className="row gap8 mt12" style={{ fontSize: 10.5 }}>
            <span className="chip teal">{data?.high ?? 0} HIGH</span>
            <span className="chip orange">{data?.medium ?? 0} MED</span>
            <span className="chip slate">{data?.low ?? 0} LOW</span>
          </div>
        </div>
      </div>

      {items.length ? (
        <div className="card" style={{ overflow: 'hidden' }}>
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: 104 }}>Story</th>
                <th>User story</th>
                <th style={{ width: 132 }}>Subcap</th>
                <th style={{ width: 54 }}>SV</th>
                <th style={{ width: 74 }}>Composite</th>
                <th style={{ width: 84 }}>Confidence</th>
                <th style={{ width: 34 }} />
              </tr>
            </thead>
            <tbody>
              {items.map((s) => {
                const isOpen = open === s.story_key;
                return [
                  <tr
                    key={s.story_key}
                    onClick={() => setOpen(isOpen ? null : s.story_key)}
                    style={{ cursor: 'pointer' }}
                  >
                    <td className="mono" style={{ fontSize: 11, color: 'var(--text-primary)' }}>
                      {s.story_key}
                    </td>
                    <td>
                      <div className="row gap8" style={{ flexWrap: 'nowrap' }}>
                        {s.is_synthetic && (
                          <span className="chip orange" style={{ fontSize: 9.5, flexShrink: 0 }}>
                            synthetic · provisional
                          </span>
                        )}
                        <div style={{ maxWidth: 340, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12.5 }}>
                          {s.summary}
                        </div>
                      </div>
                    </td>
                    <td>
                      <span
                        className="sclink mono"
                        style={{ fontSize: 11 }}
                        onClick={(e) => {
                          e.stopPropagation();
                          go('subcap/' + s.subcap_id);
                        }}
                      >
                        {s.subcap_id}
                      </span>
                    </td>
                    <td>
                      <span className="chip soft" style={{ fontSize: 10 }}>
                        {s.sv || '—'}
                      </span>
                    </td>
                    <td>
                      <b className="num" style={{ color: compColor(s.composite_score ?? 0) }}>
                        {(s.composite_score ?? 0).toFixed(2)}
                      </b>
                    </td>
                    <td>
                      <span className={'chip ' + confClass(s.confidence_level)} style={{ fontSize: 10 }}>
                        {s.confidence_level}
                      </span>
                    </td>
                    <td>
                      <Icon n={isOpen ? 'chevD' : 'chevR'} s={14} style={{ color: 'var(--text-disabled)' }} />
                    </td>
                  </tr>,
                  isOpen ? (
                    <tr key={s.story_key + '-d'}>
                      <td colSpan={7} style={{ padding: 0 }}>
                        <StoryDrill s={s} />
                      </td>
                    </tr>
                  ) : null,
                ];
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty icon="book" title="No stories match" desc="Try a different pillar, confidence, composite floor or search term." />
      )}

      <div className="between mt16">
        <span className="muted" style={{ fontSize: 12 }}>
          Page {page} of {pages} · {total.toLocaleString()} match · corpus{' '}
          {jiraTotal.toLocaleString()} Jira
          {synTotal > 0 ? ` + ${synTotal.toLocaleString()} synthetic` : ''}
          {syn === 'exclude' ? ' (synthetic excluded)' : ''}
        </span>
        <div className="row gap8">
          <button className="btn ghost sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            <Icon n="chevL" s={14} /> Prev
          </button>
          <button className="btn ghost sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
            Next <Icon n="chevR" s={14} />
          </button>
        </div>
      </div>
    </Page>
  );
}
