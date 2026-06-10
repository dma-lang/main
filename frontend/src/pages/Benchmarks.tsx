// Benchmarks studio (D4) — defensible external benchmarks with confidence bands and an
// adversarial verdict. Each card: the distribution of observations with the bootstrap CI band
// (the quantitative core), the methodology panel (the defensibility record — "not documented"
// is rendered, never invented), the adversary-verdict card (BENCHMARK / INDICATIVE / EXPLORATORY
// — the trust check on the benchmark itself), and the coverage-gap banner where support is thin
// (no false precision). Monthly cadence from config/schedules.yaml. Spec §D4 components rendered
// in the prototype's design language (the prototype ships no Benchmarks page).
import { useState } from 'react';

import { type BenchItem } from '../api/client';
import { useBenchmarkActions, useBenchmarks } from '../api/queries';
import { Claim, Dropdown, Empty, Page, Tier } from '../components/primitives';
import { go, openLoop, openReasoning, toast } from '../lib/events';
import { heatBg } from '../lib/helpers';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const VERDICT_CHIP: Record<string, string> = {
  BENCHMARK: 'teal',
  INDICATIVE: 'blue',
  EXPLORATORY: 'orange',
  pending: 'slate',
};

function fmtTs(s: string | null): string {
  if (!s) return '—';
  const iso = s.replace(' ', 'T').replace(/\+(\d{2})$/, '+$1:00');
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return s.slice(0, 16);
  return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

// Distribution strip: observation dots + IQR box + median line + (when not thin) the bootstrap
// CI band. Pure SVG on the shared tokens, same visual language as the workbench bars.
function Dist({ b }: { b: BenchItem }) {
  const lo = Math.min(...b.observations);
  const hi = Math.max(...b.observations);
  const span = hi - lo || 1;
  const x = (v: number) => 6 + ((v - lo) / span) * 88; // 6% padding each side
  return (
    <div>
      <svg width="100%" height="96" style={{ display: 'block' }}>
        {b.ci_low !== null && b.ci_high !== null && (
          <>
            <rect
              x={x(b.ci_low) + '%'}
              y="14"
              width={Math.max(0.5, x(b.ci_high) - x(b.ci_low)) + '%'}
              height="14"
              rx="3"
              fill="var(--z-blue)"
              opacity="0.22"
            />
            <text
              x={(x(b.ci_low) + x(b.ci_high)) / 2 + '%'}
              y="24"
              textAnchor="middle"
              fontSize="9"
              fill="var(--z-blue)"
            >
              95% CI {b.ci_low}–{b.ci_high}
            </text>
          </>
        )}
        <rect
          x={x(b.p25) + '%'}
          y="44"
          width={Math.max(0.5, x(b.p75) - x(b.p25)) + '%'}
          height="22"
          rx="4"
          fill="var(--surface-overlay)"
          stroke="var(--border-medium)"
        />
        <line
          x1={x(b.p50) + '%'}
          x2={x(b.p50) + '%'}
          y1="38"
          y2="72"
          stroke="var(--interactive)"
          strokeWidth="2.5"
        />
        {b.observations.map((v, i) => (
          <circle
            key={i}
            cx={x(v) + '%'}
            cy="55"
            r="3"
            fill="var(--z-dark)"
            opacity="0.38"
          />
        ))}
        <text x={x(lo) + '%'} y="88" textAnchor="middle" fontSize="9.5" fill="var(--text-tertiary)">
          {lo}
        </text>
        <text x={x(hi) + '%'} y="88" textAnchor="middle" fontSize="9.5" fill="var(--text-tertiary)">
          {hi}
        </text>
        <text
          x={x(b.p50) + '%'}
          y="88"
          textAnchor="middle"
          fontSize="10"
          fontWeight="700"
          fill="var(--interactive)"
        >
          {b.p50}
        </text>
      </svg>
      <div className="row gap12" style={{ fontSize: 10.5, justifyContent: 'center' }}>
        <span className="muted">
          p25 <b className="num">{b.p25}</b>
        </span>
        <span className="muted">
          median <b className="num">{b.p50}</b>
        </span>
        <span className="muted">
          p75 <b className="num">{b.p75}</b>
        </span>
        <span className="muted">
          {b.n} observations · {b.unit.trim()}
        </span>
      </div>
    </div>
  );
}

function BenchCard({ b }: { b: BenchItem }) {
  const onLoop = () =>
    openLoop({
      kind: 'benchmark',
      id: b.id,
      title: b.metric,
      claim: b.label,
      source: b.source?.name,
      subcap: b.affects?.[0]?.[0],
      subcapName: b.affects?.[0]?.[2],
      chain: b.chain,
    });

  return (
    <div className="card pad fade-in">
      <div className="row gap8" style={{ marginBottom: 10, flexWrap: 'wrap' }}>
        <span className={'chip ' + (VERDICT_CHIP[b.verdict] ?? 'slate')}>{b.verdict}</span>
        <Tier t={b.tier} />
        <Claim label={b.label} />
        <span className="chip soft" style={{ fontSize: 10 }}>
          {b.segment}
        </span>
        <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
          {b.date}
        </span>
      </div>
      <div className="h2" style={{ fontSize: 15.5, marginBottom: 12, lineHeight: 1.35 }}>
        {b.metric}
      </div>

      {b.thin && (
        <div
          className="card"
          style={{
            padding: '10px 13px',
            marginBottom: 12,
            background: 'var(--state-warn-bg)',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          <Icon n="alert" s={15} style={{ color: 'var(--z-orange)', flex: 'none' }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 600 }}>Coverage gap</div>
            <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
              {b.coverage_note} The confidence band is suppressed — no false precision.
            </div>
          </div>
        </div>
      )}

      <div className="card" style={{ padding: '12px 14px 8px', marginBottom: 12 }}>
        <div className="eyebrow" style={{ marginBottom: 4 }}>
          Distribution{b.thin ? '' : ' · bootstrap CI band'}
        </div>
        <Dist b={b} />
      </div>

      <div
        className="card"
        style={{ padding: '11px 13px', marginBottom: 12, background: 'var(--surface-raised)' }}
      >
        <div className="eyebrow" style={{ marginBottom: 5 }}>
          Methodology
        </div>
        <div
          className="muted"
          style={{
            fontSize: 11.5,
            lineHeight: 1.55,
            fontStyle: b.methodology === 'not documented' ? 'italic' : undefined,
          }}
        >
          {b.methodology}
        </div>
      </div>

      <div className="card" style={{ padding: '11px 13px', marginBottom: 12 }}>
        <div className="row gap8" style={{ marginBottom: 5 }}>
          <Icon n="shield" s={13} style={{ color: 'var(--interactive)' }} />
          <span className="eyebrow" style={{ margin: 0 }}>
            Adversarial review
          </span>
          <span className={'chip ' + (VERDICT_CHIP[b.verdict] ?? 'slate')} style={{ fontSize: 9.5 }}>
            {b.verdict}
          </span>
        </div>
        <div className="muted" style={{ fontSize: 11.5, lineHeight: 1.55 }}>
          {b.verdict_note}
        </div>
      </div>

      <div className="eyebrow" style={{ marginBottom: 7 }}>
        Mapped subcaps
      </div>
      <div className="row wrap gap8" style={{ marginBottom: 14 }}>
        {b.affects.map(([id, score, name]) => (
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
        <div className="row gap8">
          {b.chain ? (
            <button className="linkbtn" onClick={() => b.chain && openReasoning(b.chain)}>
              <Icon n="eye" s={13} /> Reasoning
            </button>
          ) : (
            <span />
          )}
          <span className="muted" style={{ fontSize: 10.5 }}>
            {b.source.name} · ERS {b.ers.toFixed(2)}
          </span>
        </div>
        <button className="btn ghost xs" onClick={onLoop}>
          <Icon n="sparkles" s={13} /> Run consultant loop
        </button>
      </div>
    </div>
  );
}

export function Benchmarks() {
  const version = useUi((s) => s.version);
  const isAdmin = useUi((s) => s.adminView);
  const [segment, setSegment] = useState('all');
  const q = useBenchmarks(segment);
  const { scan } = useBenchmarkActions();
  const items = q.data?.items ?? [];
  const segments = q.data?.segments ?? [];
  const scanInfo = q.data?.scan;

  return (
    <Page
      eyebrow="D · Public intelligence"
      title="Benchmarks studio"
      width="narrow"
      intro="Ground claims in defensible external benchmarks. Each curated panel carries its observation distribution with a bootstrap confidence band, the methodology behind it, and an adversarial verdict — thin coverage is flagged, never hidden."
      actions={
        <div className="row gap8">
          <Dropdown
            value={segment}
            icon="filter"
            options={[
              { v: 'all', l: 'All segments' },
              ...segments.map((s) => ({ v: s, l: s })),
            ]}
            onChange={setSegment}
          />
          {isAdmin && version ? (
            <button
              className="btn ghost sm"
              disabled={scan.isPending}
              onClick={() =>
                scan.mutate(version, {
                  onSuccess: (r) =>
                    toast(
                      `Ingest ran · ${r.created} new, ${r.deduped} deduped · ${r.mapped} mapped, ${r.flagged} flagged to review`,
                    ),
                })
              }
            >
              <Icon n="refresh" s={14} /> Ingest now
            </button>
          ) : null}
        </div>
      }
    >
      {scanInfo && (
        <div className="row gap8" style={{ marginBottom: 16 }}>
          <Icon n="clock" s={13} style={{ color: 'var(--text-tertiary)' }} />
          <span className="muted" style={{ fontSize: 11.5 }}>
            Monthly ingest · last {fmtTs(scanInfo.last_scan)} · next {fmtTs(scanInfo.next_scan)}{' '}
            <span className="mono">({scanInfo.cron} UTC)</span> — curated panels, not a live feed.
          </span>
        </div>
      )}

      <div style={{ display: 'grid', gap: 12 }}>
        {items.map((b) => (
          <BenchCard key={b.id} b={b} />
        ))}
        {!items.length && (
          <Empty
            icon="bars"
            title={segment !== 'all' ? 'No benchmarks in this segment' : 'No benchmarks yet'}
            desc={
              segment !== 'all'
                ? 'Widen the segment filter — panels are ingested per subvertical.'
                : 'The monthly ingest turns curated public datasets into confidence-banded, adversarially-reviewed benchmarks. Panels appear after the next scheduled run.'
            }
          />
        )}
      </div>
    </Page>
  );
}
