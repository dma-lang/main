// Trends monitor (D2) — multi-signal trends earned from the 8-week evidence window. Each card shows
// the signal breakdown (burst velocity · tier-weighted diversity · novelty/emergence · persistence)
// so an analyst sees WHY it surfaced, the affected subcaps (emergent flagged — the only path a
// provisional synthetic story surfaces), the trust envelope (Claim · Tier · ERS), a reasoning
// backlink, the evidence-cluster drilldown, Promote/Dismiss, and the consultant loop (→ gated
// suggestion, never a live edit). Weekly cadence from config/schedules.yaml. Ported from the prototype.
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { api, type TrendItem } from '../api/client';
import { useTrends, useTrendsActions } from '../api/queries';
import { Bar, Claim, Dropdown, Empty, Page, Tier } from '../components/primitives';
import { go, openReasoning, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

function fmtTs(s: string | null): string {
  if (!s) return '—';
  const iso = s.replace(' ', 'T').replace(/\+(\d{2})$/, '+$1:00');
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return s.slice(0, 16);
  return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

const SIGNALS: [keyof TrendItem['signals'], string, string][] = [
  ['velocity', 'Burst velocity', 'var(--z-teal)'],
  ['diversity', 'Source diversity', 'var(--z-blue)'],
  ['novelty', 'Novelty / emergence', 'var(--z-orange)'],
  ['persistence', 'Persistence', 'var(--interactive)'],
];

const STATUS_CHIP: Record<string, string> = {
  staged: 'blue',
  promoted: 'teal',
  consumed: 'slate',
  dismissed: 'slate',
  review: 'orange',
};

// Evidence-cluster drilldown — the gated items clustered into the trend, lazy-loaded on expand.
function ClusterEvidence({ trendId }: { trendId: string }) {
  const q = useQuery({ queryKey: ['trend-evidence', trendId], queryFn: () => api.trendEvidence(trendId) });
  if (q.isLoading) return <div className="muted" style={{ fontSize: 11.5, padding: '8px 2px' }}>Loading cluster…</div>;
  const rows = q.data?.evidence ?? [];
  return (
    <div style={{ display: 'grid', gap: 7, marginTop: 10 }}>
      {rows.map((e, i) => (
        <a
          key={i}
          href={e.url}
          target="_blank"
          rel="noopener"
          className="card hov"
          style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '7px 10px', textDecoration: 'none' }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="row gap6">
              <b style={{ fontSize: 11.5, color: 'var(--text-primary)' }}>{e.source}</b>
              <Tier t={e.tier} />
              <span className="muted" style={{ fontSize: 10 }}>{e.date}</span>
            </div>
            <div className="muted" style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {e.title}
            </div>
          </div>
          <div style={{ textAlign: 'right', flex: 'none' }}>
            <div className="num" style={{ fontSize: 12, fontWeight: 700, color: 'var(--interactive)' }}>{e.ers.toFixed(2)}</div>
            <div className="muted" style={{ fontSize: 8.5 }}>ERS</div>
          </div>
          <Icon n="ext" s={13} style={{ color: 'var(--text-tertiary)', flex: 'none' }} />
        </a>
      ))}
    </div>
  );
}

function TrendCard({ t }: { t: TrendItem }) {
  const [open, setOpen] = useState(false);
  const { loop, feedback } = useTrendsActions();
  const actionable = t.status === 'staged' || t.status === 'review';

  const onLoop = () =>
    loop.mutate(t.id, {
      onSuccess: (r) =>
        toast(
          r.staged
            ? `Staged ${r.kind} suggestion for ${r.target} → review in AI suggestions`
            : r.status === 'duplicate'
              ? `Already staged for ${r.target} — pending in AI suggestions`
              : (r.reason ?? `Loop ${r.status}`),
        ),
    });
  const onFeedback = (verdict: 'promote' | 'dismiss') =>
    feedback.mutate({ id: t.id, verdict }, { onSuccess: (r) => toast(`Trend ${r.status}`) });

  return (
    <div className="card pad fade-in">
      <div className="row gap8" style={{ marginBottom: 10, flexWrap: 'wrap' }}>
        <span className={'chip ' + (STATUS_CHIP[t.status] ?? 'slate')}>{t.status}</span>
        <span className="chip soft" style={{ fontSize: 10 }}>
          <Icon n="layers" s={11} /> {t.evidence_count} signals
        </span>
        {t.emergent && (
          <span className="chip orange" style={{ fontSize: 10 }}>
            <Icon n="alert" s={11} /> Emergent
          </span>
        )}
        <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>{t.window}</span>
      </div>

      <div className="h2" style={{ fontSize: 15.5, marginBottom: 12, lineHeight: 1.35 }}>{t.label}</div>

      <div className="card" style={{ padding: '11px 13px', marginBottom: 12, background: 'var(--surface-raised)' }}>
        <div className="between" style={{ marginBottom: 9 }}>
          <span className="eyebrow" style={{ margin: 0 }}>Why it surfaced</span>
          <span className="num" style={{ fontSize: 12.5, fontWeight: 700 }}>
            score {t.score.toFixed(2)}
          </span>
        </div>
        <div style={{ display: 'grid', gap: 7 }}>
          {SIGNALS.map(([k, lbl, color]) => (
            <div key={k} className="row gap8">
              <span className="muted" style={{ fontSize: 11, width: 130, flex: 'none' }}>{lbl}</span>
              <div style={{ flex: 1 }}>
                <Bar v={t.signals[k]} max={1} color={color} />
              </div>
              <span className="num" style={{ fontSize: 11, width: 30, textAlign: 'right', flex: 'none' }}>
                {t.signals[k].toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="eyebrow" style={{ marginBottom: 7 }}>Affected subcaps</div>
      <div className="row wrap gap8" style={{ marginBottom: 12 }}>
        {t.affects.map((a) => (
          <div
            key={a.subcap_id}
            className="row gap6 card"
            style={{ padding: '5px 9px', borderColor: a.emergent ? 'var(--z-orange)' : undefined }}
          >
            {a.emergent && <Icon n="alert" s={11} style={{ color: 'var(--z-orange)' }} />}
            <span
              className="mono sclink"
              style={{ color: 'var(--interactive)', cursor: 'pointer', fontSize: 11 }}
              onClick={() => go('subcap/' + a.subcap_id)}
            >
              {a.subcap_id}
            </span>
            <span
              className="muted"
              style={{ fontSize: 11, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
            >
              {a.name}
            </span>
            {a.emergent && <span className="chip orange" style={{ fontSize: 9 }}>emergent</span>}
          </div>
        ))}
      </div>

      <div className="row gap8" style={{ marginBottom: 4, flexWrap: 'wrap' }}>
        <Claim label={t.label_claim} />
        <Tier t={t.tier} />
        <span className="chip soft" style={{ fontSize: 10 }}>ERS {t.ers.toFixed(2)}</span>
        <button className="linkbtn" style={{ fontSize: 11.5 }} onClick={() => setOpen((o) => !o)}>
          <Icon n={open ? 'chevD' : 'chevR'} s={12} /> {t.evidence_count} evidence
        </button>
      </div>
      {open && <ClusterEvidence trendId={t.id} />}

      <div className="between" style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 12, marginTop: 12 }}>
        {t.chain ? (
          <button className="linkbtn" onClick={() => t.chain && openReasoning(t.chain)}>
            <Icon n="eye" s={13} /> Reasoning
          </button>
        ) : (
          <span />
        )}
        <div className="row gap8">
          <button className="btn ghost xs" disabled={loop.isPending} onClick={onLoop}>
            <Icon n="sparkles" s={13} /> Run consultant loop
          </button>
          {actionable && (
            <>
              <button className="btn ghost xs" disabled={feedback.isPending} onClick={() => onFeedback('dismiss')}>
                <Icon n="x" s={13} /> Dismiss
              </button>
              <button className="btn primary xs" disabled={feedback.isPending} onClick={() => onFeedback('promote')}>
                <Icon n="check" s={13} /> Promote
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export function Trends() {
  const version = useUi((s) => s.version);
  const isAdmin = useUi((s) => s.adminView);
  const [status, setStatus] = useState('all');
  const q = useTrends(status, version);
  const { scan } = useTrendsActions();
  const items = q.data?.items ?? [];
  const counts = q.data?.counts ?? {};
  const scanInfo = q.data?.scan;

  return (
    <Page
      eyebrow="D · Public intelligence"
      title="Trends monitor"
      width="narrow"
      intro="Multi-signal trends earned from the last 8 weeks of gated evidence — clustered by meaning, scored on burst, diversity, novelty and persistence, and staged for the consultant cycle. A trend flagged emergent is the only path a provisional synthetic story surfaces."
      actions={
        <div className="row gap8">
          <Dropdown
            value={status}
            icon="filter"
            options={[
              { v: 'all', l: 'All status' },
              { v: 'staged', l: 'Staged' },
              { v: 'promoted', l: 'Promoted' },
              { v: 'dismissed', l: 'Dismissed' },
              { v: 'review', l: 'In review' },
            ]}
            onChange={setStatus}
          />
          {isAdmin && version ? (
            <button
              className="btn ghost sm"
              disabled={scan.isPending}
              onClick={() =>
                scan.mutate(version, {
                  onSuccess: (r) =>
                    toast(
                      `Detection ran · ${r.detected} earned (${r.staged} staged, ${r.review} review) · ${r.filtered} thin clusters filtered`,
                    ),
                })
              }
            >
              <Icon n="refresh" s={14} /> Detect now
            </button>
          ) : null}
        </div>
      }
    >
      {scanInfo && (
        <div className="row gap8" style={{ marginBottom: 16 }}>
          <Icon n="clock" s={13} style={{ color: 'var(--text-tertiary)' }} />
          <span className="muted" style={{ fontSize: 11.5 }}>
            Weekly detection · last {fmtTs(scanInfo.last_scan)} · next {fmtTs(scanInfo.next_scan)}{' '}
            <span className="mono">({scanInfo.cron} UTC)</span> — over a rolling 8-week window.
          </span>
        </div>
      )}

      {(counts.staged || counts.promoted || counts.dismissed || counts.review) && (
        <div className="row gap8" style={{ marginBottom: 16, flexWrap: 'wrap' }}>
          {(['staged', 'promoted', 'review', 'dismissed'] as const).map((k) =>
            counts[k] ? (
              <div key={k} className="card" style={{ padding: '7px 12px' }}>
                <span className="num" style={{ fontSize: 15, fontWeight: 700 }}>{counts[k]}</span>{' '}
                <span className="muted" style={{ fontSize: 11 }}>{k}</span>
              </div>
            ) : null,
          )}
        </div>
      )}

      <div style={{ display: 'grid', gap: 12 }}>
        {items.map((t) => (
          <TrendCard key={t.id} t={t} />
        ))}
        {!items.length && (
          <Empty
            icon="trend"
            title={status !== 'all' ? 'No trends in this status' : 'No trends earned yet'}
            desc={
              status !== 'all'
                ? 'Switch the status filter — trends move from staged to promoted or dismissed as analysts act.'
                : 'Trends are earned, not counted: a cluster needs enough independent, multi-source evidence over the window to clear the signal bar. Detection runs weekly after the news scan.'
            }
          />
        )}
      </div>
    </Page>
  );
}
