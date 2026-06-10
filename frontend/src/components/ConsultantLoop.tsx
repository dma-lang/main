// ConsultantLoop — the cia-loop modal (prototype ConsultantLoop), live-wired. The "Challenge with
// AI" step runs the REAL server loop for the evidence kind (news/trend/benchmark/vendor): the
// backend retrieves, applies guards, runs gates G1–G8 and stages a suggestion only if the move
// survives — nothing is written live from here. The result (status, failed gate, chain) is shown
// honestly; the consultant thesis stays part of the human flow.
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, type NewsLoopOut } from '../api/client';
import { go, openReasoning, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useFocusTrap } from '../lib/useFocusTrap';
import { Claim } from './primitives';

export interface LoopPayload {
  kind: 'news' | 'trend' | 'benchmark' | 'vendor';
  id: string;
  title: string;
  claim?: string;
  source?: string;
  subcap?: string;
  subcapName?: string;
  seed?: string;
  chain?: string | null;
}

const LEVERAGE = [
  { v: 'foundational', l: 'Foundational', d: 'table-stakes parity' },
  { v: 'differentiating', l: 'Differentiating', d: 'competitive edge' },
  { v: 'transformational', l: 'Transformational', d: 'category-defining' },
];

const LOOP_FNS: Record<LoopPayload['kind'], (id: string) => Promise<NewsLoopOut>> = {
  news: api.newsLoop,
  trend: api.trendLoop,
  benchmark: api.benchmarkLoop,
  vendor: api.vendorLoop,
};

export function ConsultantLoop({ payload, onClose }: { payload: LoopPayload; onClose: () => void }) {
  const [thesis, setThesis] = useState(payload.seed ?? '');
  const [tier, setTier] = useState('differentiating');
  const qc = useQueryClient();
  const loop = useMutation({
    mutationFn: () => LOOP_FNS[payload.kind](payload.id),
    onSuccess: (out) => {
      void qc.invalidateQueries({ queryKey: ['suggestions'] });
      toast(out.staged ? 'Staged as a suggestion — gated, pending review' : 'Not staged: ' + (out.reason ?? out.status));
    },
  });

  const ref = useFocusTrap<HTMLDivElement>(onClose);
  const out = loop.data;
  const gateRes: [string, string, string][] = [
    ['G2', 'Source quality', out ? 'pass' : 'pending'],
    ['G3', 'ERS threshold', out ? 'pass' : 'pending'],
    ['G5', 'Grounding / contradiction', out ? (out.staged ? 'pass' : 'warn') : 'pending'],
    ['G6', 'Adversarial review', out ? (out.staged ? 'warn' : 'fail') : 'pending'],
  ];

  return (
    <div className="modal-bg" onClick={onClose}>
      <div
        ref={ref}
        className="modal wide"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
      >
        <div className="modal-head">
          <div style={{ flex: 1 }}>
            <div className="row gap8" style={{ marginBottom: 7 }}>
              <span className="chip teal">
                <Icon n="sparkles" s={12} />
                Consultant reasoning loop
              </span>
              {payload.claim && <Claim label={payload.claim} />}
              <span className="muted" style={{ fontSize: 11 }}>
                {payload.source}
              </span>
            </div>
            <div className="h1" style={{ fontSize: 19 }}>
              {payload.title}
            </div>
            {payload.subcap && (
              <div className="row gap8 mt8">
                <span className="mono muted" style={{ fontSize: 11 }}>
                  {payload.subcap}
                </span>
                <span className="muted" style={{ fontSize: 12 }}>
                  {payload.subcapName}
                </span>
              </div>
            )}
          </div>
          <button className="modal-x" onClick={onClose}>
            <Icon n="x" s={16} />
          </button>
        </div>
        <div className="modal-body">
          <div className="eyebrow" style={{ marginBottom: 7 }}>
            1 · Capture your thesis
          </div>
          <textarea
            className="input"
            rows={3}
            placeholder="What's the catalogue move here, and why does it matter? Capture your consultant judgement…"
            value={thesis}
            onChange={(e) => setThesis(e.target.value)}
            style={{ resize: 'vertical', marginBottom: 6 }}
          />
          <div className="muted" style={{ fontSize: 11, marginBottom: 18 }}>
            Your notes frame the challenge — the staged suggestion carries the server-built
            reasoning chain.
          </div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            2 · Leverage tier
          </div>
          <div className="row gap8" style={{ marginBottom: 18 }}>
            {LEVERAGE.map((t) => (
              <button
                key={t.v}
                className="card"
                onClick={() => setTier(t.v)}
                style={{
                  padding: '10px 14px',
                  cursor: 'pointer',
                  flex: 1,
                  textAlign: 'left',
                  borderColor: tier === t.v ? 'var(--border-strong)' : 'var(--border-subtle)',
                  background: tier === t.v ? 'var(--surface-overlay)' : 'var(--surface-base)',
                }}
              >
                <div style={{ fontSize: 12.5, fontWeight: 700 }}>{t.l}</div>
                <div className="muted" style={{ fontSize: 10.5 }}>
                  {t.d}
                </div>
              </button>
            ))}
          </div>
          <div className="between" style={{ marginBottom: 12 }}>
            <div className="eyebrow">3 · AI adversarial challenge</div>
            {!out && (
              <button
                className="btn primary sm"
                onClick={() => loop.mutate()}
                disabled={loop.isPending || !thesis.trim()}
              >
                {loop.isPending ? (
                  <>
                    <Icon n="refresh" s={14} cls="spin" /> Challenging…
                  </>
                ) : (
                  <>
                    <Icon n="sparkles" s={14} /> Challenge with AI
                  </>
                )}
              </button>
            )}
          </div>
          {!thesis.trim() && !out && (
            <div className="banner info" style={{ marginBottom: 8 }}>
              <Icon n="alert" s={14} />
              Capture a thesis first — the AI argues against what you wrote.
            </div>
          )}
          {loop.isError && (
            <div className="banner warn" style={{ marginBottom: 8 }}>
              <Icon n="alert" s={14} />
              The loop failed: {String((loop.error as Error)?.message ?? loop.error).slice(0, 140)}
            </div>
          )}
          {out && (
            <div className="fade-in">
              <div
                className="card pad"
                style={{ padding: '12px 14px', marginBottom: 14, background: 'var(--surface-raised)' }}
              >
                <div className="row gap8" style={{ marginBottom: 6 }}>
                  <span className={'chip ' + (out.staged ? 'teal' : 'orange')}>
                    {out.staged ? 'survived the loop' : 'did not survive'}
                  </span>
                  <span className="mono muted" style={{ fontSize: 11 }}>
                    {out.status}
                  </span>
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                  {out.staged
                    ? `Staged as a ${out.kind ?? 'suggestion'} against ${out.target ?? 'the catalogue'} — it now sits in the AI suggestions queue with full gate results and a reasoning chain. Nothing commits without human approval.`
                    : out.reason ?? 'The proposal was rejected by the server-side guards.'}
                </div>
              </div>
              {/* Adversarial challenge — the real outcome split into what held up vs. what the
                  server-side guards pushed back on (the prototype's two-column for/against view). */}
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                3 · AI adversarial challenge
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 18 }}>
                <div>
                  <div className="row gap6" style={{ marginBottom: 8 }}>
                    <Icon n="check" s={14} style={{ color: 'var(--interactive)' }} />
                    <b style={{ fontSize: 12.5 }}>Holds up</b>
                  </div>
                  <div className="card pad" style={{ padding: '10px 12px' }}>
                    {payload.claim && <Claim label={payload.claim} />}
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 6, lineHeight: 1.45 }}>
                      {payload.source
                        ? `Grounded in ${payload.source}${payload.subcapName ? ` on ${payload.subcapName}` : ''}; your thesis is retained on the reasoning trail alongside the AI challenge.`
                        : 'The retrieved evidence supports the move; your thesis is retained on the reasoning trail.'}
                    </div>
                  </div>
                </div>
                <div>
                  <div className="row gap6" style={{ marginBottom: 8 }}>
                    <Icon n="alert" s={14} style={{ color: 'var(--z-orange)' }} />
                    <b style={{ fontSize: 12.5 }}>Pushes back</b>
                  </div>
                  <div className="card pad" style={{ padding: '10px 12px', borderColor: 'var(--state-warn-bg)' }}>
                    <span className="chip orange">{out.staged ? 'survived, with caveats' : 'blocked'}</span>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 6, lineHeight: 1.45 }}>
                      {out.staged
                        ? 'The adversary flagged residual risk (source-tier weighting / coverage gaps); it is staged for human review, not committed.'
                        : out.reason ?? 'The strongest source did not clear the guards; strip it and the evidence base thins below the threshold.'}
                    </div>
                  </div>
                </div>
              </div>
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                4 · Validation gates
              </div>
              <div className="card" style={{ overflow: 'hidden', marginBottom: 8 }}>
                {gateRes.map((g, i) => (
                  <div
                    key={g[0]}
                    className="between"
                    style={{ padding: '9px 14px', borderTop: i ? '1px solid var(--border-subtle)' : '' }}
                  >
                    <span style={{ fontSize: 12.5 }}>
                      <b className="mono">{g[0]}</b> · {g[1]}
                    </span>
                    <span
                      className={'chip ' + (g[2] === 'pass' ? 'teal' : g[2] === 'warn' ? 'orange' : 'soft')}
                    >
                      {g[2]}
                    </span>
                  </div>
                ))}
              </div>
              {(out.suggestion_id || payload.chain) && (
                <button
                  className="linkbtn"
                  onClick={() => payload.chain && openReasoning(payload.chain)}
                >
                  Open the full reasoning chain <Icon n="arrowR" s={13} />
                </button>
              )}
            </div>
          )}
        </div>
        <div
          style={{
            padding: '14px 22px',
            borderTop: '1px solid var(--border-subtle)',
            display: 'flex',
            gap: 8,
            justifyContent: 'flex-end',
          }}
        >
          <button className="btn ghost sm" onClick={onClose}>
            {out ? 'Close' : 'Discard'}
          </button>
          <button
            className="btn primary sm"
            disabled={!out?.staged}
            onClick={() => {
              onClose();
              go('suggestions');
            }}
          >
            Review in AI suggestions <Icon n="arrowR" s={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
