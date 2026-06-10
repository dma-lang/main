// Vendor intelligence (F2) — weekly vendor developments typed into the eight event classes and
// mapped to subcap impact. Vendor profile cards (catalogue platforms · 90-day developments ·
// subcaps touched · heat), the typed developments feed (each card: type chip, honest low-tier
// source, claim label, impact note, affected subcaps, reasoning, consultant loop — sub-T3 signal
// is refused at the G3 floor), and the vendor x subcap heatmap whose cell intensity is evidence
// frequency x recency, never the static platform join. Weekly cadence from config/schedules.yaml.
import { useState } from 'react';

import { type VendorHeatCell, type VendorEventItem } from '../api/client';
import { useVendorActions, useVendorIntel } from '../api/queries';
import { Claim, Dropdown, Empty, Page, Tier } from '../components/primitives';
import { go, openReasoning, toast } from '../lib/events';
import { heatBg } from '../lib/helpers';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const TYPE_CHIP: Record<string, string> = {
  product_launch: 'teal',
  partnership: 'blue',
  deprecation: 'orange',
  pricing_change: 'slate',
  executive_move: 'slate',
  security_incident: 'orange',
  regulatory_action: 'orange',
  case_study: 'blue',
};

function fmtTs(s: string | null): string {
  if (!s) return '—';
  const iso = s.replace(' ', 'T').replace(/\+(\d{2})$/, '+$1:00');
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return s.slice(0, 16);
  return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

// Vendor x subcap heatmap: rows = vendors, columns = the top-impacted subcaps; cell intensity =
// sum(impact score x recency weight) — the evidence corpus, not the platform join.
function HeatMap({ cells }: { cells: VendorHeatCell[] }) {
  const vendors = [...new Set(cells.map((c) => c.vendor))].sort();
  const colTotals = new Map<string, number>();
  const names = new Map<string, string>();
  for (const c of cells) {
    colTotals.set(c.subcap_id, (colTotals.get(c.subcap_id) ?? 0) + c.score);
    names.set(c.subcap_id, c.name);
  }
  const cols = [...colTotals.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([id]) => id);
  const byKey = new Map(cells.map((c) => [c.vendor + '|' + c.subcap_id, c.score]));
  const max = Math.max(...cells.map((c) => c.score), 0.01);
  if (!vendors.length) return null;
  return (
    <div className="card pad" style={{ marginBottom: 18, overflowX: 'auto' }}>
      <div className="eyebrow" style={{ marginBottom: 4 }}>
        Vendor × subcap impact
      </div>
      <div className="muted" style={{ fontSize: 11.5, marginBottom: 10 }}>
        Cell intensity = development evidence frequency × recency — earned from gated events, not
        a static platform join. Click a cell to open the subcap.
      </div>
      <table style={{ borderCollapse: 'separate', borderSpacing: 3, fontSize: 10.5 }}>
        <thead>
          <tr>
            <th />
            {cols.map((c) => (
              <th key={c} style={{ padding: '0 2px', fontWeight: 600 }}>
                <span
                  className="mono sclink"
                  title={names.get(c)}
                  style={{ color: 'var(--interactive)', cursor: 'pointer', fontSize: 9.5 }}
                  onClick={() => go('subcap/' + c)}
                >
                  {c}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {vendors.map((v) => (
            <tr key={v}>
              <td
                style={{
                  paddingRight: 8,
                  fontWeight: 600,
                  whiteSpace: 'nowrap',
                  maxWidth: 170,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {v}
              </td>
              {cols.map((c) => {
                const score = byKey.get(v + '|' + c);
                return (
                  <td key={c}>
                    <div
                      title={score ? `${v} × ${names.get(c)} · ${score.toFixed(2)}` : undefined}
                      onClick={() => score && go('subcap/' + c)}
                      style={{
                        width: 46,
                        height: 26,
                        borderRadius: 5,
                        cursor: score ? 'pointer' : 'default',
                        background: score ? heatBg(score / max) : 'var(--surface-sunken)',
                        color: score && score / max > 0.5 ? '#fff' : 'var(--text-tertiary)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 9.5,
                        fontWeight: 700,
                      }}
                    >
                      {score ? score.toFixed(1) : ''}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EventCard({ e }: { e: VendorEventItem }) {
  const { loop } = useVendorActions();
  const onLoop = () =>
    loop.mutate(e.id, {
      onSuccess: (r) =>
        toast(
          r.staged
            ? `Staged ${r.kind} suggestion for ${r.target} → review in AI suggestions`
            : r.status === 'duplicate'
              ? `Already staged for ${r.target} — pending in AI suggestions`
              : (r.reason ?? `Loop ${r.status}`),
        ),
    });
  return (
    <div className="card pad fade-in">
      <div className="row gap8" style={{ marginBottom: 10, flexWrap: 'wrap' }}>
        <span className={'chip ' + (TYPE_CHIP[e.event_type] ?? 'slate')}>{e.type_label}</span>
        <Tier t={e.tier} />
        <Claim label={e.label} />
        <b style={{ fontSize: 11.5 }}>{e.vendor}</b>
        <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
          {e.date}
        </span>
      </div>
      <div className="h2" style={{ fontSize: 14.5, marginBottom: 8, lineHeight: 1.35 }}>
        {e.title}
      </div>
      <div className="muted" style={{ fontSize: 11.5, marginBottom: 10 }}>
        {e.impact_note}
      </div>
      <div className="row wrap gap8" style={{ marginBottom: 12 }}>
        {e.affects.map(([id, score, name]) => (
          <div key={id} className="row gap6 card" style={{ padding: '4px 8px' }}>
            <span
              className="mono sclink"
              style={{ color: 'var(--interactive)', cursor: 'pointer', fontSize: 10.5 }}
              onClick={() => go('subcap/' + id)}
            >
              {id}
            </span>
            <span
              className="muted"
              style={{
                fontSize: 10.5,
                maxWidth: 140,
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
                fontSize: 9.5,
              }}
            >
              {score.toFixed(2)}
            </span>
          </div>
        ))}
      </div>
      <div
        className="between"
        style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}
      >
        <div className="row gap8">
          {e.chain ? (
            <button className="linkbtn" onClick={() => e.chain && openReasoning(e.chain)}>
              <Icon n="eye" s={13} /> Reasoning
            </button>
          ) : (
            <span />
          )}
          <span className="muted" style={{ fontSize: 10.5 }}>
            {e.source.name} · ERS {e.reliability.toFixed(2)}
          </span>
        </div>
        <button className="btn ghost xs" disabled={loop.isPending} onClick={onLoop}>
          <Icon n="sparkles" s={13} /> Run consultant loop
        </button>
      </div>
    </div>
  );
}

export function Vendors() {
  const version = useUi((s) => s.version);
  const isAdmin = useUi((s) => s.adminView);
  const [eventType, setEventType] = useState('all');
  const q = useVendorIntel(eventType);
  const { scan } = useVendorActions();
  const vendors = q.data?.vendors ?? [];
  const items = q.data?.items ?? [];
  const heat = q.data?.heat ?? [];
  const types = q.data?.types ?? [];
  const scanInfo = q.data?.scan;

  return (
    <Page
      eyebrow="F · Lifecycle & competition"
      title="Vendor intelligence"
      width="wide"
      intro="Weekly vendor developments typed into eight event classes and mapped to subcap impact. Vendor-published signal is honestly low-tier — the loop stages an edit only from independent (T3+) coverage."
      actions={
        <div className="row gap8">
          <Dropdown
            value={eventType}
            icon="filter"
            options={[{ v: 'all', l: 'All event types' }, ...types]}
            onChange={setEventType}
          />
          {isAdmin && version ? (
            <button
              className="btn ghost sm"
              disabled={scan.isPending}
              onClick={() =>
                scan.mutate(version, {
                  onSuccess: (r) =>
                    toast(
                      `Scan ran · ${r.created} new, ${r.deduped} deduped · ${r.mapped} mapped, ${r.review} to review, ${r.flagged} flagged`,
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
            <span className="mono">({scanInfo.cron} UTC)</span> — developments reflect the last
            scan, not a live feed.
          </span>
        </div>
      )}

      {vendors.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))',
            gap: 10,
            marginBottom: 18,
          }}
        >
          {vendors.map((v) => (
            <div key={v.vendor_id} className="card pad" style={{ padding: '12px 14px' }}>
              <div className="row gap8" style={{ marginBottom: 8 }}>
                <Icon n="building" s={14} style={{ color: 'var(--interactive)' }} />
                <b style={{ fontSize: 12.5 }}>{v.name}</b>
              </div>
              <div className="row gap12" style={{ fontSize: 10.5, flexWrap: 'wrap' }}>
                <span className="muted">
                  <b className="num">{v.platforms}</b> platforms
                </span>
                <span className="muted">
                  <b className="num">{v.developments_90d}</b> dev · 90d
                </span>
                <span className="muted">
                  <b className="num">{v.subcaps_touched}</b> subcaps
                </span>
                <span className="muted">
                  heat <b className="num">{v.heat.toFixed(1)}</b>
                </span>
              </div>
              {v.platforms === 0 && (
                <div className="row gap6" style={{ marginTop: 7 }}>
                  <Icon n="alert" s={11} style={{ color: 'var(--z-orange)' }} />
                  <span className="muted" style={{ fontSize: 10 }}>
                    Not in the catalogue registry — flagged
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <HeatMap cells={heat} />

      <div className="eyebrow" style={{ marginBottom: 8 }}>
        Developments
      </div>
      <div style={{ display: 'grid', gap: 12 }}>
        {items.map((e) => (
          <EventCard key={e.id} e={e} />
        ))}
        {!items.length && (
          <Empty
            icon="building"
            title={eventType !== 'all' ? 'No developments of this type' : 'No vendor signal yet'}
            desc={
              eventType !== 'all'
                ? 'Widen the event-type filter — review-queued and gate-failed events live in Change Flags, not here.'
                : 'The weekly scan types vendor developments into eight event classes and maps them to subcap impact. Items appear after the next scheduled scan.'
            }
          />
        )}
      </div>
    </Page>
  );
}
