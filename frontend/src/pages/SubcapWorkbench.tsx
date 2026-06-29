// Subcap deep dive (A2) — the prototype's Workbench detail at /subcap/:id: a sticky catalogue tree
// (search + pillar pills + collapsible category -> cluster -> subcap) beside a detail panel (hero +
// completeness ring + stat buttons + five tabs). Wired to GET /api/catalogue/{v}/subcaps (tree),
// /subcaps/{id} (detail), /subcaps/{id}/stories (Delivery), /subcaps/{id}/enrichment (Maturity /
// Use cases) and /subcaps/{id}/connections (siblings + gated news signals).
import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { useLocation, useParams } from 'react-router-dom';

import type { SubcapDetail, SubcapEnrichment, SubcapNode } from '../api/client';
import {
  useSubcap,
  useSubcapConnections,
  useSubcapEnrichment,
  useSubcaps,
  useSubcapStories,
} from '../api/queries';
import { DeliveryDrillPanel } from '../components/DeliveryDrillPanel';
import { Bar, Claim, Empty, LifeChip, Mag, PillarDot, Tier } from '../components/primitives';
import { go, openOffering, openReasoning, toast } from '../lib/events';
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

function OverviewTab({
  d,
  node,
  enr,
}: {
  d: SubcapDetail | undefined;
  node: SubcapNode | null;
  enr: SubcapEnrichment | undefined;
}) {
  const personas = enr?.personas ?? [];
  const platforms = enr?.platforms ?? [];
  return (
    <div className="fade-in">
      {enr?.inherited_from && (
        <div className="banner info" style={{ fontSize: 11.5, marginBottom: 12 }}>
          <Icon n="branch" s={13} />
          This version carries no enrichment of its own — platforms, use cases and maturity are
          shown from the <b>{enr.inherited_from}</b> reference catalogue, mapped by subcap ID.
        </div>
      )}
      <p style={{ margin: '0 0 16px', fontSize: 13.5, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
        {d?.description ?? 'No description recorded in this version.'}
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 14 }}>
        <div>
          <div className="eyebrow" style={{ marginBottom: 7 }}>
            Personas
          </div>
          {personas.length ? (
            <div className="row wrap gap6">
              {personas.map((p) => (
                <span key={p.persona_id} className="chip outline" title={p.role_description ?? ''}>
                  {p.canonical_name}
                </span>
              ))}
            </div>
          ) : (
            <span className="muted" style={{ fontSize: 12 }}>
              none recorded
            </span>
          )}
        </div>
        <div>
          <div className="eyebrow" style={{ marginBottom: 7 }}>
            Offering
          </div>
          {(enr?.offerings ?? []).length ? (
            <div className="row wrap gap6">
              {(enr?.offerings ?? []).map((o) => (
                <span
                  key={o.offering_id}
                  className="chip teal"
                  style={{ cursor: 'pointer' }}
                  title={'Open ' + o.name + ' — matched subcaps & capabilities'}
                  onClick={() => openOffering(o.offering_id)}
                >
                  <Icon n="package" s={11} /> {o.name}
                </span>
              ))}
            </div>
          ) : (
            <span className="muted" style={{ fontSize: 12 }}>
              No productized offering yet
            </span>
          )}
        </div>
      </div>
      <div className="divider" />
      <div className="between" style={{ marginBottom: 9 }}>
        <div className="eyebrow">Linked L3 platforms · {platforms.length}</div>
        <span className="muted" style={{ fontSize: 11 }}>
          click to drill into the platform
        </span>
      </div>
      {platforms.length ? (
        <div style={{ display: 'grid', gap: 6 }}>
          {platforms.map((p) => (
            <div
              key={p.l3_id}
              className="card hov"
              style={{ padding: '9px 12px', cursor: 'pointer' }}
              onClick={() => go('platforms/' + p.l3_id)}
            >
              <div className="between">
                <div className="row gap8" style={{ minWidth: 0 }}>
                  <div
                    style={{
                      width: 26,
                      height: 26,
                      borderRadius: 6,
                      background: 'var(--surface-overlay)',
                      color: 'var(--interactive)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flex: 'none',
                    }}
                  >
                    <Icon n="database" s={13} />
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 12.5,
                        fontWeight: 600,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {p.name}
                    </div>
                    <div className="mono muted" style={{ fontSize: 10 }}>
                      {p.l3_id}
                    </div>
                  </div>
                </div>
                <div className="row gap8" style={{ flex: 'none' }}>
                  {p.vendor && (
                    <span className="chip soft" style={{ fontSize: 10 }}>
                      {p.vendor}
                    </span>
                  )}
                  <Icon n="arrowR" s={13} style={{ color: 'var(--text-tertiary)' }} />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <span className="muted" style={{ fontSize: 12 }}>
          none mapped
        </span>
      )}
      <div className="muted" style={{ fontSize: 11, marginTop: 8 }}>
        {d?.n_use_cases ?? 0} use cases and {d?.n_stories ?? 0} stories on {node?.id ?? 'this subcap'}{' '}
        ride on these platforms — open the Use cases and Delivery tabs for detail.
      </div>
    </div>
  );
}

const MLEVELS: [string, string][] = [
  ['M1', 'Foundational'],
  ['M2', 'Developing'],
  ['M3', 'Established / AI-assisted'],
  ['M4', 'Advanced hybrid agentic'],
  ['M5', 'Transformational'],
];
const MHEAT = ['#7fd8cf', '#5cc9bd', '#2fb9ab', '#16a596', '#0a8f86'];

function MaturityTab({ enr }: { enr: SubcapEnrichment | undefined }) {
  const [open, setOpen] = useState(0);
  const byLevel = new Map((enr?.maturity ?? []).map((m) => [m.level, m]));
  const has = (i: number) => {
    const m = byLevel.get(MLEVELS[i][0]);
    return !!(m && m.descriptor && m.descriptor.length > 20);
  };
  const cur = byLevel.get(MLEVELS[open][0]);
  return (
    <div className="fade-in">
      <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
        Five maturity levels. Click a level to read its descriptor — only one is expanded so it stays
        scannable.
      </div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
        {MLEVELS.map(([lv], i) => (
          <button
            key={lv}
            onClick={() => setOpen(i)}
            style={{
              flex: 1,
              border: 'none',
              cursor: 'pointer',
              padding: '9px 4px',
              borderRadius: 6,
              background: open === i ? MHEAT[i] : 'var(--surface-sunken)',
              color:
                open === i
                  ? i >= 2
                    ? '#fff'
                    : 'var(--z-dark)'
                  : has(i)
                    ? 'var(--text-secondary)'
                    : 'var(--text-disabled)',
              fontWeight: 700,
              fontSize: 12,
              position: 'relative',
            }}
          >
            {lv}
            {!has(i) && <span style={{ position: 'absolute', top: 3, right: 5, fontSize: 8 }}>○</span>}
          </button>
        ))}
      </div>
      <div className="card" style={{ padding: '14px 16px', background: 'var(--surface-raised)' }}>
        <div className="h3" style={{ marginBottom: 6 }}>
          {MLEVELS[open][0]} · {MLEVELS[open][1]}
        </div>
        <div
          style={{
            fontSize: 13,
            color: cur?.descriptor ? 'var(--text-secondary)' : 'var(--text-disabled)',
            lineHeight: 1.55,
          }}
        >
          {cur?.descriptor ?? 'No descriptor at this level yet — flagged thin in maturity coverage.'}
        </div>
        {cur?.features && (
          <div
            className="muted"
            style={{ fontSize: 11.5, marginTop: 10, lineHeight: 1.5, whiteSpace: 'pre-line' }}
          >
            {cur.features}
          </div>
        )}
      </div>
    </div>
  );
}

function UseTab({ enr }: { enr: SubcapEnrichment | undefined }) {
  const ucs = enr?.use_cases ?? [];
  if (!ucs.length) {
    return (
      <EmptyTab icon="puzzle" title="No use cases" desc="This subcap has no use cases mapped yet." />
    );
  }
  return (
    <div className="fade-in">
      <div style={{ display: 'grid', gap: 8 }}>
        {ucs.map((u) => (
          <div key={u.use_case_id} className="card" style={{ padding: '11px 13px' }}>
            <div className="row gap8" style={{ marginBottom: 6, flexWrap: 'wrap' }}>
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
          </div>
        ))}
      </div>
    </div>
  );
}

const SCORES: [string, 'composite_score' | 'ac_score' | 'sd_score' | 'story_score' | 'delivery_score'][] =
  [
    ['Composite', 'composite_score'],
    ['Acceptance criteria', 'ac_score'],
    ['Solution design', 'sd_score'],
    ['Story score', 'story_score'],
    ['Delivery', 'delivery_score'],
  ];

function scoreColor(v: number): string {
  return v >= 3 ? 'var(--interactive)' : v >= 2 ? 'var(--z-blue)' : 'var(--z-orange)';
}

// Delivery tab (F5) — confirmed Jira stories carried onto this subcap, top by composite score, each
// expandable to its real ac/sd/ss sub-scores. The corpus has no per-quarter date dimension, so the
// prototype's hashed quarter bars are intentionally omitted rather than faked.
function DeliveryTab({ version, node }: { version: string; node: SubcapNode }) {
  const [open, setOpen] = useState<string | null>(null);
  // ONE toggle for the whole Delivery tab: Jira-only (analysis grade) vs include synthetic. It
  // drives the story list AND the clients/clusters drilldown below, so they stay consistent.
  const [synthetic, setSynthetic] = useState(false);
  const stories = useSubcapStories(version, node.id, synthetic);
  const data = stories.data;
  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  const toggle = (
    <div className="row gap8" style={{ marginBottom: 14 }}>
      <span className="muted" style={{ fontSize: 11 }}>
        Stories:
      </span>
      <button
        className={'btn xs ' + (!synthetic ? 'primary' : 'ghost')}
        onClick={() => setSynthetic(false)}
        title="Real Jira delivery only (analysis grade)"
      >
        Jira only
      </button>
      <button
        className={'btn xs ' + (synthetic ? 'primary' : 'ghost')}
        onClick={() => setSynthetic(true)}
        title="Also show the labelled synthetic stories"
      >
        + synthetic
      </button>
    </div>
  );

  if (stories.isLoading) {
    return (
      <div className="fade-in">
        {toggle}
        <div className="muted" style={{ fontSize: 12 }}>
          Loading delivery…
        </div>
      </div>
    );
  }
  if (total === 0) {
    return (
      <div className="fade-in">
        {toggle}
        <EmptyTab
          icon="book"
          title={synthetic ? 'No mapped stories' : 'No real-client stories'}
          desc={
            synthetic
              ? 'No Jira or synthetic story carries forward to this subcap in this version.'
              : 'No real-client (Jira) stories carry forward here. Toggle “+ synthetic” to include synthetic stories.'
          }
        />
      </div>
    );
  }

  return (
    <div className="fade-in">
      {toggle}
      <div className="row gap16" style={{ marginBottom: 14, flexWrap: 'wrap' }}>
        <div style={{ textAlign: 'center' }}>
          <div className="num" style={{ fontSize: 20, fontWeight: 700 }}>
            {total}
          </div>
          <div className="muted" style={{ fontSize: 10 }}>
            {synthetic ? 'stories (incl. synthetic)' : 'Jira stories'}
          </div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <LifeChip life={node.life} />
          <div className="muted" style={{ fontSize: 10, marginTop: 4 }}>
            lifecycle
          </div>
        </div>
      </div>
      <div className="eyebrow" style={{ marginBottom: 8 }}>
        Mapped user stories{' '}
        <span className="muted" style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
          · top {items.length} by composite · click to expand
        </span>
      </div>
      <div style={{ display: 'grid', gap: 6 }}>
        {items.map((st) => {
          const isOpen = open === st.story_key;
          const cs = st.composite_score ?? 0;
          return (
            <div key={st.story_key} className="card" style={{ overflow: 'hidden' }}>
              <div
                className="between"
                style={{ padding: '9px 12px', cursor: 'pointer' }}
                onClick={() => setOpen(isOpen ? null : st.story_key)}
              >
                <div className="row gap8" style={{ minWidth: 0 }}>
                  <Icon n={isOpen ? 'chevD' : 'chevR'} s={13} style={{ color: 'var(--text-tertiary)' }} />
                  <span className="mono" style={{ fontSize: 11, color: 'var(--text-primary)', flex: 'none' }}>
                    {st.story_key}
                  </span>
                  {st.is_synthetic && (
                    <span className="chip orange" style={{ fontSize: 8.5, flex: 'none' }} title="synthetic story (not real Jira delivery)">
                      synthetic
                    </span>
                  )}
                  {st.project_key && (
                    <span className="chip soft" style={{ fontSize: 9, flex: 'none' }} title="Jira project (client proxy)">
                      {st.project_key}
                    </span>
                  )}
                  <span
                    className="muted"
                    style={{ fontSize: 10.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {st.summary}
                  </span>
                </div>
                <b className="num" style={{ fontSize: 12, flex: 'none', color: scoreColor(cs) }}>
                  {cs.toFixed(1)}
                </b>
              </div>
              {isOpen && (
                <div
                  className="fade-in"
                  style={{ padding: '4px 14px 14px', borderTop: '1px solid var(--border-subtle)' }}
                >
                  {/* full summary, not truncated */}
                  <div
                    style={{
                      fontSize: 12.5,
                      lineHeight: 1.45,
                      margin: '10px 0',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    {st.summary || 'No summary recorded.'}
                  </div>
                  {/* delivery metadata pulled from the Jira corpus */}
                  <div className="row wrap gap6" style={{ marginBottom: 10 }}>
                    {st.epic_key && (
                      <span className="chip soft" style={{ fontSize: 9.5 }} title="Jira epic">
                        epic {st.epic_key}
                      </span>
                    )}
                    {st.project_key && (
                      <span className="chip soft" style={{ fontSize: 9.5 }} title="Jira project (client proxy)">
                        {st.project_key}
                      </span>
                    )}
                    {st.story_sv_code && (
                      <span className="chip soft" style={{ fontSize: 9.5 }} title="subvertical">
                        {st.story_sv_code}
                      </span>
                    )}
                    {st.tier && (
                      <span className="chip soft" style={{ fontSize: 9.5 }} title="capability tier">
                        {st.tier}
                      </span>
                    )}
                    {st.reusability_layer && (
                      <span className="chip soft" style={{ fontSize: 9.5 }} title="reusability layer">
                        {st.reusability_layer}
                      </span>
                    )}
                    {st.population && (
                      <span className="chip soft" style={{ fontSize: 9.5 }} title="population segment">
                        pop {st.population}
                      </span>
                    )}
                    {st.confidence_level && (
                      <span
                        className={'chip ' + (st.confidence_level === 'HIGH' ? 'teal' : 'soft')}
                        style={{ fontSize: 9.5 }}
                        title="mapping confidence"
                      >
                        {st.confidence_level}
                      </span>
                    )}
                  </div>
                  {(st.category_name || st.cap_name) && (
                    <div className="muted" style={{ fontSize: 11, marginBottom: 12 }}>
                      {[st.category_name, st.cap_name].filter(Boolean).join(' · ')} →{' '}
                      <b style={{ color: 'var(--text-secondary)' }}>{node.name}</b>
                    </div>
                  )}
                  {/* graded sub-scores incl. composite + delivery */}
                  <div className="row wrap gap16" style={{ maxWidth: 640 }}>
                    {SCORES.map(([label, key]) => {
                      const v = st[key];
                      return (
                        <div key={key} style={{ minWidth: 110, flex: 1 }}>
                          <div className="between" style={{ fontSize: 11, marginBottom: 4 }}>
                            <span className="muted">{label}</span>
                            <b className="num">{v != null ? v.toFixed(1) : 'n/a'}</b>
                          </div>
                          <Bar v={v ?? 0} max={5} color={scoreColor(v ?? 0)} />
                        </div>
                      );
                    })}
                  </div>
                  <div className="row gap12 mt12">
                    <button className="linkbtn" onClick={() => go('stories')}>
                      Open in Story library <Icon n="arrowR" s={12} />
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      {total > items.length && (
        <button
          className="btn subtle sm"
          style={{ justifyContent: 'center', width: '100%', marginTop: 8 }}
          onClick={() => go('stories')}
        >
          All {total} stories in the Story library <Icon n="arrowR" s={13} />
        </button>
      )}
      <div className="divider" />
      <div className="eyebrow" style={{ marginBottom: 8 }}>
        Who delivered this, and what clusters together
      </div>
      <DeliveryDrillPanel version={version} id={node.id} synthetic={synthetic} />
    </div>
  );
}

// Connections tab — KG Layer-A siblings (same-capability subcaps, ranked by shared L3 platforms),
// a deterministic projection of the link tables, plus recent gated news signals (F7) with the
// full trust envelope (Mag · Tier · Claim · ERS) and a reasoning backlink.
function ConnTab({ version, node }: { version: string; node: SubcapNode }) {
  const conn = useSubcapConnections(version, node.id);
  const sibs = conn.data?.siblings ?? [];
  const signals = conn.data?.signals ?? [];
  return (
    <div className="fade-in">
      <div className="eyebrow" style={{ marginBottom: 8 }}>
        Related subcaps · same capability, by shared platforms (Layer A)
      </div>
      <div style={{ display: 'grid', gap: 6, marginBottom: 16 }}>
        {sibs.length ? (
          sibs.map((x) => (
            <div
              key={x.id}
              className="card hov"
              style={{ padding: '9px 12px', cursor: 'pointer' }}
              onClick={() => go('subcap/' + x.id)}
            >
              <div className="between">
                <div className="row gap8" style={{ minWidth: 0 }}>
                  <Icon n="graph" s={13} style={{ color: 'var(--z-slate)' }} />
                  <span
                    style={{ fontSize: 12.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {x.name}
                  </span>
                </div>
                <span className="chip soft" style={{ fontSize: 9.5, flex: 'none' }}>
                  {x.shared_platforms} shared platform{x.shared_platforms === 1 ? '' : 's'}
                </span>
              </div>
            </div>
          ))
        ) : (
          <span className="muted" style={{ fontSize: 12 }}>
            No siblings in this capability.
          </span>
        )}
      </div>
      <div className="eyebrow" style={{ marginBottom: 8 }}>
        Signals
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        {signals.map((sig, i) => (
          <div key={i} className="card" style={{ padding: '10px 13px' }}>
            <div className="row gap8" style={{ marginBottom: 5, flexWrap: 'wrap' }}>
              <Mag m={sig.mag} />
              <Tier t={sig.tier} />
              <Claim label={sig.label} />
              <span className="muted" style={{ fontSize: 10, marginLeft: 'auto' }}>
                {sig.source} · {sig.date}
              </span>
            </div>
            <div style={{ fontSize: 12.5, fontWeight: 500 }}>{sig.title}</div>
            <div className="mt8 row gap12">
              {sig.chain && (
                <button className="linkbtn" onClick={() => sig.chain && openReasoning(sig.chain)}>
                  <Icon n="eye" s={13} /> Reasoning
                </button>
              )}
              <span className="muted" style={{ fontSize: 10.5 }}>
                ERS {sig.ers.toFixed(2)} · impact {sig.score.toFixed(2)}
              </span>
            </div>
          </div>
        ))}
        {!signals.length && (
          <div className="banner info">
            <Icon n="news" s={14} />
            No public or vendor signal currently maps to this subcap.
          </div>
        )}
      </div>
    </div>
  );
}

export function SubcapWorkbench() {
  const params = useParams<{ id?: string }>();
  const routeId = params.id ?? null;
  const loc = useLocation();
  // ?tab=delivery (etc.) preselects a deep-dive tab — this is how peek stats / mission control
  // drill STRAIGHT to the related user stories instead of always landing on Overview.
  const tabParam = new URLSearchParams(loc.search).get('tab');
  const version = useUi((s) => s.version);
  const ctxPillar = useUi((s) => s.pillar);
  const ctxSv = useUi((s) => s.sv); // header subvertical — scopes the tree like mission control
  const subcaps = useSubcaps(version, ctxSv);
  const all = useMemo(() => subcaps.data ?? [], [subcaps.data]);

  const [pillar, setPillar] = useState<string>(
    routeId ? routeId.slice(0, 2) : ctxPillar === 'all' ? 'P1' : ctxPillar,
  );
  const [q, setQ] = useState('');
  const [sel, setSel] = useState<string | null>(routeId);
  const [tab, setTab] = useState('overview');
  const [openCat, setOpenCat] = useState<string | null>(null);

  // Keep the tree's pillar in step with the header pillar toggle (arriving from mission control
  // with P2 selected lands on P2; the local pills still switch within the page).
  useEffect(() => {
    if (!routeId && ctxPillar !== 'all') setPillar(ctxPillar);
  }, [ctxPillar, routeId]);

  // Deep-link / back-forward: when the route id (or requested tab) changes, focus it.
  useEffect(() => {
    if (routeId) {
      setSel(routeId);
      setPillar(routeId.slice(0, 2));
      setTab(TABS.some(([t]) => t === tabParam) ? (tabParam as string) : 'overview');
    }
  }, [routeId, tabParam]);

  const node = useMemo(() => all.find((x) => x.id === sel) ?? null, [all, sel]);
  const detail = useSubcap(version, sel);
  const d = detail.data;
  const enrichment = useSubcapEnrichment(version, sel);
  const enr = enrichment.data;

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

  // record completeness = filled core fields / 5 (name, description, tier, solution type,
  // status) — computed at provision; shown as a percentage, never a magic '/8'.
  const comp = Math.round((d?.completeness ?? 0) * 100);
  const stats: [number, string, string][] = [
    [d?.n_use_cases ?? 0, 'use cases', 'usecases'],
    [d?.n_stories ?? 0, 'stories', 'delivery'],
    [d?.n_platforms ?? 0, 'platforms', 'overview'],
    [enr?.maturity.length ?? 0, 'maturity levels', 'maturity'],
  ];

  const tabBody: ReactNode =
    tab === 'overview' ? (
      <OverviewTab d={d} node={node} enr={enr} />
    ) : tab === 'maturity' ? (
      <MaturityTab enr={enr} />
    ) : tab === 'usecases' ? (
      <UseTab enr={enr} />
    ) : tab === 'delivery' ? (
      node ? <DeliveryTab version={version} node={node} /> : null
    ) : node ? (
      <ConnTab version={version} node={node} />
    ) : null;

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
            {!searching && tree.length === 0 && (
              <div className="muted" style={{ padding: 14, fontSize: 12 }}>
                No {pillar} subcaps{ctxSv && ctxSv !== 'all' ? ` in the ${ctxSv} value chain` : ''}.
                {ctxSv && ctxSv !== 'all' ? ' Switch the subvertical in the header to widen.' : ''}
              </div>
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
                <div style={{ textAlign: 'center' }} title="Record coverage — share of core fields populated on this subcap (name, description, tier, solution type, status). Distinct from mission-control delivery completeness.">
                  <Ring v={comp} max={100} />
                  <div className="muted" style={{ fontSize: 9.5, marginTop: 2 }}>
                    record coverage
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
                {enr?.inherited_from && (
                  <span
                    className="chip soft"
                    style={{ fontSize: 9.5, alignSelf: 'center' }}
                    title={`Use-case / platform / maturity counts are shown from the ${enr.inherited_from} reference catalogue (this version carries none of its own), mapped by subcap id.`}
                  >
                    <Icon n="branch" s={10} /> enriched from {enr.inherited_from}
                  </span>
                )}
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
