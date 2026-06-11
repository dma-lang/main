// Project-subcap trace (C3) — every cross-signal event that touched a subcap on one timeline,
// wired to GET /api/catalogue/{v}/subcaps/{id}/timeline (a union of the news/vendor/suggestion/
// trend/benchmark impact tables; each event carries its claim · tier · reasoning backlink).
// Deep-linkable per subcap; reachable without an id (shows a picker). Stories carry no real
// delivery dates, so delivery is a summary KPI, not a dated lane.
import { useState } from 'react';
import { useParams } from 'react-router-dom';

import type { TimelineEvent } from '../api/client';
import { useSubcaps, useTimeline } from '../api/queries';
import { DeliveryDrillPanel } from '../components/DeliveryDrillPanel';
import { Claim, Dropdown, Empty, Page, PillarDot, Tier } from '../components/primitives';
import { go, openPeek, openReasoning, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const LANE: Record<string, { label: string; color: string; icon: string }> = {
  news: { label: 'News', color: 'var(--z-orange)', icon: 'news' },
  vendor: { label: 'Vendor', color: 'var(--z-slate)', icon: 'building' },
  suggestion: { label: 'Suggestion', color: 'var(--p4)', icon: 'sparkles' },
  benchmark: { label: 'Benchmark', color: 'var(--z-teal-light)', icon: 'bars' },
  trend: { label: 'Trend', color: 'var(--z-blue)', icon: 'trend' },
};

function fmtDate(d: string | null): string {
  if (!d) return '—';
  const t = Date.parse(d);
  return Number.isNaN(t) ? d.slice(0, 10) : new Date(t).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function EventCard({ e }: { e: TimelineEvent }) {
  const lane = LANE[e.kind] ?? { label: e.kind, color: 'var(--text-tertiary)', icon: 'dot' };
  return (
    <div className="card pad" style={{ padding: '11px 13px', borderLeft: `3px solid ${lane.color}` }}>
      <div className="row gap8" style={{ marginBottom: 5, flexWrap: 'wrap' }}>
        <span className="row gap6" style={{ fontSize: 10.5, fontWeight: 700, color: lane.color }}>
          <Icon n={lane.icon as never} s={12} /> {lane.label.toUpperCase()}
        </span>
        {e.claim && <Claim label={e.claim} />}
        {e.tier && <Tier t={e.tier} />}
        {e.mag && <span className={'mag ' + e.mag.toLowerCase()}>{e.mag}</span>}
        <span className="muted" style={{ fontSize: 10.5, marginLeft: 'auto' }}>
          {fmtDate(e.date)}
        </span>
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--text-primary)', lineHeight: 1.4 }}>{e.title}</div>
      {e.excerpt && (
        <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>
          {e.excerpt}
        </div>
      )}
      {e.chain && (
        <button className="linkbtn" style={{ marginTop: 6 }} onClick={() => openReasoning(e.chain)}>
          <Icon n="eye" s={12} /> Reasoning
        </button>
      )}
    </div>
  );
}

export function Trace() {
  const ui = useUi();
  const { id } = useParams<{ id: string }>();
  const subs = useSubcaps(ui.version);
  const [pick, setPick] = useState('');
  const activeId = id || pick;
  const tl = useTimeline(ui.version, activeId || null);

  const options = (subs.data ?? []).slice(0, 60).map((x) => ({
    v: x.id,
    l: x.id + ' · ' + x.name.slice(0, 22),
  }));
  const s = (subs.data ?? []).find((x) => x.id === activeId);
  const events = tl.data?.events ?? [];
  const lastActivity = events.find((e) => e.date)?.date ?? null;
  const kpis: [string, string][] = [
    [String(events.length), 'cross-signal events'],
    [`${tl.data?.sources ?? 0}`, 'signal sources touched'],
    [fmtDate(lastActivity), 'last activity'],
    [(tl.data?.stories ?? 0).toLocaleString(), 'delivered stories'],
  ];

  return (
    <Page
      eyebrow="C · Project validation"
      title="Project-subcap trace"
      intro={
        <>
          Pick any subcap to see <b>every event that ever touched it</b> — delivered stories, news,
          vendor moves, benchmarks, trends and suggestions — on one timeline. Click an event to read
          what it means and drill to its reasoning.
        </>
      }
      actions={
        <div className="row gap8">
          <Dropdown
            value={activeId}
            icon="branch"
            options={options}
            onChange={(v) => (id ? go('trace/' + v) : setPick(v))}
          />
          <button className="btn ghost sm" onClick={() => toast('Exporting trace as CSV…')}>
            <Icon n="file" s={14} />
            Export CSV
          </button>
        </div>
      }
    >
      {!activeId ? (
        <div className="card pad">
          <Empty
            icon="branch"
            title="Pick a subcap to trace"
            desc="Choose a subcap above to assemble its cross-signal timeline. Every delivered story, news item, vendor move, benchmark, trend and suggestion that touched it lands on one lane view."
            cta="Browse the catalogue"
            onCta={() => go('explorer')}
          />
        </div>
      ) : (
        <>
          <div className="card pad" style={{ marginBottom: 16 }}>
            <div className="between">
              <div className="row gap10">
                {s && <PillarDot p={s.pillar} />}
                <div>
                  <div className="h2">{tl.data?.name ?? s?.name ?? activeId}</div>
                  <div className="row gap8 mt8">
                    <span className="mono muted" style={{ fontSize: 11 }}>
                      {activeId}
                    </span>
                    {s && (
                      <span className="muted" style={{ fontSize: 11 }}>
                        {s.cat_name}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="row gap8">
                <button className="btn ghost xs" onClick={() => openPeek(activeId)}>
                  <Icon n="eye" s={13} />
                  Peek
                </button>
                <button className="btn ghost xs" onClick={() => go('subcap/' + activeId)}>
                  Deep dive
                </button>
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginTop: 16 }}>
              {kpis.map((k, i) => (
                <div key={i} className="card" style={{ padding: '11px 14px' }}>
                  <div className="num" style={{ fontSize: 19, fontWeight: 700 }}>
                    {k[0]}
                  </div>
                  <div className="muted" style={{ fontSize: 10.5 }}>
                    {k[1]}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="card pad" style={{ marginBottom: 16 }}>
            <div className="between" style={{ marginBottom: 10 }}>
              <div className="h3">Delivery drilldown · clients & story clusters</div>
              <span className="muted" style={{ fontSize: 11 }}>
                same join as the heatmap — figures reconcile exactly
              </span>
            </div>
            <DeliveryDrillPanel version={ui.version} id={activeId} />
          </div>

          <div className="card pad">
            <div className="between" style={{ marginBottom: 10 }}>
              <div className="h3">Signal timeline</div>
              <span className="muted" style={{ fontSize: 11 }}>
                newest first · each event carries its claim, tier and reasoning
              </span>
            </div>
            {tl.isLoading && <div className="muted" style={{ fontSize: 12 }}>Assembling the timeline…</div>}
            {tl.data && events.length === 0 && (
              <Empty
                icon="route"
                title="No signals on this subcap yet"
                desc="No news, vendor move, benchmark, trend or suggestion has mapped to this subcap. As the weekly scans run and the consultant loop stages suggestions, they appear here on their lanes."
              />
            )}
            {events.length > 0 && (
              <div style={{ display: 'grid', gap: 8 }}>
                {events.map((e, i) => (
                  <EventCard key={i} e={e} />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </Page>
  );
}
