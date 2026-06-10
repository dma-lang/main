// News watch (D1) — grounded public news turned into subcap-scored, gated evidence. Each card
// carries the trust envelope (Mag · Tier · Claim), the expected catalogue impact, a clickable
// source sub-object {name,type,tier,url,ers,fetched_at} (R6) with its reliability, the top
// affected subcaps (heat-scored), a reasoning backlink and the consultant loop (→ gated
// suggestion, never a live edit). Weekly cadence from config/schedules.yaml — the scan line
// shows last/next scan and never implies real-time. Ported from the prototype News.
import { useState } from 'react';

import { useNews, useNewsActions } from '../api/queries';
import { Claim, Dropdown, Empty, Mag, Page, Tier } from '../components/primitives';
import { go, openLoop, openReasoning, toast } from '../lib/events';
import { heatBg, passesTrustFloor } from '../lib/helpers';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

// Prototype impact-chip colour rule, applied to the impact label.
const impClass = (imp: string) =>
  /Net-new/.test(imp)
    ? 'orange'
    : /Descriptor|use-case/.test(imp)
      ? 'blue'
      : /Retire/.test(imp)
        ? 'orange'
        : 'slate';

// Render a stored timestamp (timestamptz::text or ISO) as a stable UTC stamp — cadence is
// weekly, so the page must read as "as of the last scan", never as live.
function fmtTs(s: string | null): string {
  if (!s) return '—';
  const iso = s.replace(' ', 'T').replace(/\+(\d{2})$/, '+$1:00');
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return s.slice(0, 16);
  return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

export function News() {
  const version = useUi((s) => s.version);
  const isAdmin = useUi((s) => s.adminView);
  const [tier, setTier] = useState('all');
  const [impactF, setImpactF] = useState('all');
  const q = useNews(impactF, tier);
  const { scan } = useNewsActions();
  const claimF = useUi((s) => s.claim);
  const tierF = useUi((s) => s.tier);
  const items = (q.data?.items ?? []).filter((n) =>
    passesTrustFloor(n.label, n.tier, claimF, tierF),
  );
  const impacts = q.data?.impacts ?? [];
  const scanInfo = q.data?.scan;
  const filtered = impactF !== 'all' || tier !== 'all';

  return (
    <Page
      eyebrow="D · Public intelligence"
      title="News watch"
      width="narrow"
      intro="Turn raw public news into subcap-scored signal. Each item is classified by its expected impact to the catalogue, with a source you can open, its reliability, the top affected subcaps, and a reasoning link."
      actions={
        <div className="row gap8">
          <Dropdown
            value={impactF}
            icon="filter"
            options={[{ v: 'all', l: 'All impact' }, ...impacts]}
            onChange={setImpactF}
          />
          <Dropdown
            value={tier}
            options={[
              { v: 'all', l: 'All tiers' },
              { v: 'T1', l: 'T1 regulator' },
              { v: 'T2', l: 'T2 analyst' },
              { v: 'T3', l: 'T3 press' },
            ]}
            onChange={setTier}
          />
          {isAdmin && version ? (
            <button
              className="btn ghost sm"
              disabled={scan.isPending}
              onClick={() =>
                scan.mutate(version, {
                  onSuccess: (r) =>
                    toast(
                      `Scan ran · ${r.created} new, ${r.deduped} deduped · ${r.mapped} mapped, ${r.flagged} flagged to review`,
                    ),
                })
              }
            >
              <Icon n="refresh" s={14} /> Scan now
            </button>
          ) : null}
        </div>
      }
    >
      {scanInfo && (
        <div className="row gap8" style={{ marginBottom: 16 }}>
          <Icon n="clock" s={13} style={{ color: 'var(--text-tertiary)' }} />
          <span className="muted" style={{ fontSize: 11.5 }}>
            Weekly scan · last {fmtTs(scanInfo.last_scan)} · next {fmtTs(scanInfo.next_scan)}{' '}
            <span className="mono">({scanInfo.cron} UTC)</span> — items reflect the last scan, not
            a live feed.
          </span>
        </div>
      )}

      <div style={{ display: 'grid', gap: 12 }}>
        {items.map((n) => (
          <div key={n.id} className="card pad fade-in">
            <div className="row gap8" style={{ marginBottom: 10, flexWrap: 'wrap' }}>
              <Mag m={n.mag} />
              <Tier t={n.tier} />
              <Claim label={n.label} />
              <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
                {n.date}
              </span>
            </div>
            <div className="h2" style={{ fontSize: 15.5, marginBottom: 10, lineHeight: 1.35 }}>
              {n.title}
            </div>

            <div
              className="card"
              style={{
                padding: '10px 13px',
                marginBottom: 12,
                background: 'var(--surface-raised)',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
              }}
            >
              <Icon n="zap" s={15} style={{ color: 'var(--interactive)', flex: 'none' }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="row gap8">
                  <span className="eyebrow" style={{ margin: 0 }}>
                    Expected catalogue impact
                  </span>
                  <span className={'chip ' + impClass(n.impact_label)}>{n.impact_label}</span>
                </div>
                <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>
                  {n.impact_note}
                </div>
              </div>
            </div>

            <div className="eyebrow" style={{ marginBottom: 6 }}>
              Source
            </div>
            <a
              href={n.source.url}
              target="_blank"
              rel="noopener"
              className="card hov"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '9px 12px',
                marginBottom: 12,
                textDecoration: 'none',
              }}
            >
              <div
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: 6,
                  background: 'var(--surface-overlay)',
                  color: 'var(--interactive)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flex: 'none',
                }}
              >
                <Icon n="news" s={14} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="row gap8">
                  <b style={{ fontSize: 12.5, color: 'var(--text-primary)' }}>{n.source.name}</b>
                  <span className="chip soft" style={{ fontSize: 9.5 }}>
                    {n.source.type}
                  </span>
                  <Tier t={n.source.tier} />
                </div>
                <div
                  className="mono muted"
                  style={{
                    fontSize: 10.5,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {n.source.url}
                </div>
              </div>
              <div style={{ textAlign: 'right', flex: 'none' }}>
                <div
                  className="num"
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    color:
                      n.reliability >= 0.85
                        ? 'var(--interactive)'
                        : n.reliability >= 0.6
                          ? 'var(--z-blue)'
                          : 'var(--z-orange)',
                  }}
                >
                  {n.reliability.toFixed(2)}
                </div>
                <div className="muted" style={{ fontSize: 9 }}>
                  reliability
                </div>
              </div>
              <Icon n="ext" s={14} style={{ color: 'var(--text-tertiary)', flex: 'none' }} />
            </a>

            <div className="eyebrow" style={{ marginBottom: 7 }}>
              Top affected subcaps
            </div>
            <div className="row wrap gap8" style={{ marginBottom: 14 }}>
              {n.affects.map(([id, score, name]) => (
                <div key={id} className="row gap6 card" style={{ padding: '5px 9px' }}>
                  <span
                    className="mono sclink"
                    style={{ color: 'var(--interactive)', cursor: 'pointer', fontSize: 11 }}
                    onClick={() => go('subcap/' + id)}
                  >
                    {id}
                  </span>
                  <span
                    className="muted"
                    style={{
                      fontSize: 11,
                      maxWidth: 150,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {name}
                  </span>
                  <span
                    className="chip"
                    style={{
                      background: heatBg(score),
                      color: score > 0.5 ? '#fff' : 'var(--z-dark)',
                      padding: '1px 6px',
                    }}
                  >
                    {score.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>

            <div
              className="between"
              style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 12 }}
            >
              {n.chain ? (
                <button className="linkbtn" onClick={() => n.chain && openReasoning(n.chain)}>
                  <Icon n="eye" s={13} /> Reasoning
                </button>
              ) : (
                <span />
              )}
              <button
                className="btn ghost xs"
                onClick={() =>
                  openLoop({
                    kind: 'news',
                    id: n.id,
                    title: n.title,
                    claim: n.label,
                    source: n.source?.name,
                    subcap: n.affects?.[0]?.[0],
                    subcapName: n.affects?.[0]?.[2],
                    chain: n.chain,
                  })
                }
              >
                <Icon n="sparkles" s={13} /> Run consultant loop
              </button>
            </div>
          </div>
        ))}
        {!items.length && (
          <Empty
            icon="news"
            title={filtered ? 'No items match these filters' : 'No news signal yet'}
            desc={
              filtered
                ? 'Widen the impact or tier filter — gate-failed items live in Change Flags, not here.'
                : 'The weekly scan turns public sources into gated, subcap-scored evidence. Items appear after the next scheduled scan.'
            }
          />
        )}
      </div>
    </Page>
  );
}
