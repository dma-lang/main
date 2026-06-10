// CommitModal — the cia-commit confirmation (prototype CommitModal), live-wired. The page that
// opens it passes `run`: its OWN existing mutation (apply suggestion / approve flag / promote).
// The server re-gates G1–G8 inside that call and writes the snapshot + audit row; this modal is
// the human friction + honest result surface, not the security boundary.
import { useState } from 'react';

import { go, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useFocusTrap } from '../lib/useFocusTrap';

export interface CommitResult {
  ok: boolean;
  detail?: string | null; // e.g. the failed gate name
}

export interface CommitPayload {
  title: string;
  kind?: string;
  summary: string;
  target?: string | null;
  impact?: number; // affected rows, when the caller knows it
  run: () => Promise<CommitResult>;
  onRejectInstead?: () => void; // optional "Reject with reason" hook (pages with reject flows)
}

const GATES: [string, string][] = [
  ['G1', 'Schema conformance'],
  ['G2', 'Source quality'],
  ['G3', 'ERS threshold'],
  ['G4', 'Citation integrity'],
];

export function CommitModal({ payload, onClose }: { payload: CommitPayload; onClose: () => void }) {
  const [committing, setCommitting] = useState(false);
  const [done, setDone] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  const ref = useFocusTrap<HTMLDivElement>(onClose);

  const commit = async () => {
    setCommitting(true);
    setFailed(null);
    try {
      const res = await payload.run();
      if (res.ok) {
        setDone(true);
        toast('Committed · new version snapshot created');
      } else {
        setFailed(res.detail ?? 'a server-side gate failed — routed to Change flags');
      }
    } catch (e) {
      setFailed(String((e as Error)?.message ?? e).slice(0, 160));
    } finally {
      setCommitting(false);
    }
  };

  return (
    <div className="modal-bg" onClick={onClose}>
      <div
        ref={ref}
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 540 }}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
      >
        <div className="modal-head">
          <div style={{ flex: 1 }}>
            <div className="row gap8" style={{ marginBottom: 6 }}>
              <span className="chip orange">
                <Icon n="shield" s={12} />
                Commit · COMMIT tier
              </span>
              {payload.kind && (
                <span className="muted" style={{ fontSize: 11 }}>
                  {payload.kind}
                </span>
              )}
            </div>
            <div className="h1" style={{ fontSize: 18 }}>
              {payload.title}
            </div>
          </div>
          <button className="modal-x" onClick={onClose}>
            <Icon n="x" s={16} />
          </button>
        </div>
        <div className="modal-body">
          {!done ? (
            <>
              <div
                className="card pad"
                style={{ padding: '12px 14px', marginBottom: 14, background: 'var(--surface-raised)' }}
              >
                <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
                  {payload.summary}
                </div>
                {payload.target && (
                  <div className="row gap8 mt8">
                    <span className="muted" style={{ fontSize: 11 }}>
                      Target
                    </span>
                    <span
                      className="mono"
                      style={{ fontSize: 11, color: 'var(--interactive)', fontWeight: 600 }}
                    >
                      {payload.target}
                    </span>
                  </div>
                )}
              </div>
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                What will change
              </div>
              <div
                style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginBottom: 16 }}
              >
                {(
                  [
                    [payload.impact ?? 1, 'affected rows'],
                    ['1', 'new snapshot'],
                    ['reversible', 'revert anytime'],
                  ] as [string | number, string][]
                ).map((k, i) => (
                  <div key={i} className="card" style={{ padding: '10px 12px', textAlign: 'center' }}>
                    <div
                      className="num"
                      style={{
                        fontSize: 17,
                        fontWeight: 700,
                        color: i === 2 ? 'var(--interactive)' : 'var(--text-primary)',
                      }}
                    >
                      {k[0]}
                    </div>
                    <div className="muted" style={{ fontSize: 10 }}>
                      {k[1]}
                    </div>
                  </div>
                ))}
              </div>
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                Deterministic gates — re-checked server-side on commit
              </div>
              <div className="card" style={{ overflow: 'hidden' }}>
                {GATES.map((g, i) => (
                  <div
                    key={g[0]}
                    className="between"
                    style={{ padding: '8px 14px', borderTop: i ? '1px solid var(--border-subtle)' : '' }}
                  >
                    <span style={{ fontSize: 12.5 }}>
                      <b className="mono">{g[0]}</b> · {g[1]}
                    </span>
                    <span className="chip soft">re-gated on commit</span>
                  </div>
                ))}
              </div>
              {failed && (
                <div className="banner warn mt16">
                  <Icon n="alert" s={14} />
                  Commit blocked: {failed}
                </div>
              )}
              <div className="banner info mt16">
                <Icon n="branch" s={14} />
                Commits are transactional and versioned — this creates a snapshot you can revert
                from the Version timeline.
              </div>
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: '18px 0' }}>
              <div
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: 12,
                  background: 'var(--surface-overlay)',
                  color: 'var(--interactive)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  margin: '0 auto 12px',
                }}
              >
                <Icon n="check" s={24} />
              </div>
              <div className="h2" style={{ marginBottom: 4 }}>
                Committed under version control
              </div>
              <div className="muted" style={{ fontSize: 12.5, maxWidth: 360, margin: '0 auto' }}>
                A new snapshot was created and the audit trail updated. Inspect or revert it on the
                Version timeline.
              </div>
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
          {!done ? (
            <>
              <button
                className="btn ghost sm"
                onClick={() => {
                  if (payload.onRejectInstead) payload.onRejectInstead();
                  else toast('Discarded — nothing written');
                  onClose();
                }}
              >
                {payload.onRejectInstead ? 'Reject with reason' : 'Cancel'}
              </button>
              <button className="btn primary sm" onClick={() => void commit()} disabled={committing}>
                {committing ? (
                  <>
                    <Icon n="refresh" s={14} cls="spin" /> Committing…
                  </>
                ) : (
                  <>
                    Commit under version control <Icon n="arrowR" s={14} />
                  </>
                )}
              </button>
            </>
          ) : (
            <button
              className="btn ghost sm"
              onClick={() => {
                go('versions');
                onClose();
              }}
            >
              Go to Version timeline
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
