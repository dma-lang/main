// Change flags inbox (G3) — the human-review choke-point. The anomalies a pillar lead must resolve
// before trusting the queue: lifecycle-vs-delivery contradictions the gates (G6) caught. Approve
// re-gates the proposed correction G1–G8 server-side and, on pass, mutates cat_<v> + writes an
// audit row; Reject needs a reason; Defer snoozes. Wired to GET /api/change-flags. Ported from the
// prototype ChangeFlags.
import { useState } from 'react';

import type { ChangeFlag } from '../api/client';
import { useChangeFlags, useFlagActions } from '../api/queries';
import { Empty, Page } from '../components/primitives';
import { go, openCommit, openReasoning, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const SEV_ORDER = ['BLOCKING', 'HIGH', 'MED', 'LOW'];
const sevColor: Record<string, string> = {
  BLOCKING: 'orange',
  HIGH: 'orange',
  MED: 'soft',
  LOW: 'soft',
};

// Human labels for the flag kinds, used by the kind filter (decay scans can raise hundreds of
// "no delivery" candidates, so being able to narrow by kind keeps the inbox usable).
const KIND_LABEL: Record<string, string> = {
  contradicted_evidence: 'Lifecycle contradictions',
  decay_no_delivery: 'Decay · no Jira delivery',
  decay_missing_subcap: 'Decay · removed from a previous version',
  evidence_gate_failure: 'Evidence gate failures',
  unscoped_subvertical: 'New subvertical proposals',
  kg_edge_proposal: 'Knowledge-graph edge proposals',
  use_case_gap: 'New use-case proposals',
};
const RENDER_CAP = 120;

export function ChangeFlags() {
  const version = useUi((s) => s.version);
  const isAdmin = useUi((s) => s.adminView);
  const q = useChangeFlags('open');
  const { scan, approve, reject, defer } = useFlagActions();
  const allFlags = q.data?.flags ?? [];
  const counts = q.data?.counts ?? { BLOCKING: 0, HIGH: 0, MED: 0, LOW: 0 };
  const [kind, setKind] = useState<string>('all');
  const [sev, setSev] = useState<string>('all');
  const kinds = [...new Set(allFlags.map((f) => f.kind))];
  // Kind + severity compose client-side (both narrow the same list; counts come from the API).
  const flags = allFlags.filter(
    (f) => (kind === 'all' || f.kind === kind) && (sev === 'all' || f.sev === sev),
  );

  const onReject = (id: string) => {
    const reason = window.prompt('Reason for rejecting this flag?')?.trim();
    if (!reason) return;
    reject.mutate({ id, reason }, { onSuccess: () => toast('Rejected — reason logged to audit') });
  };
  // Approve a flag through the CommitModal: the modal's run executes the real approve mutation,
  // which re-gates server-side before correcting the catalogue and writing the audit row. If the
  // re-gate fails the flag stays open with the failing gate named — surfaced honestly in the modal.
  const onApprove = (f: ChangeFlag) =>
    openCommit({
      title: f.title,
      kind: f.kind.replace(/_/g, ' '),
      summary: f.body,
      target: f.target,
      onRejectInstead: () => onReject(f.id),
      run: async () => {
        const r = await approve.mutateAsync(f.id);
        // R7: an approved use case fans out to every other version where it belongs — surface the
        // saved/skipped summary so one approval visibly propagates (or reports where it did not).
        const p = r.propagated;
        if (r.resolved && p && (p.saved.length || p.skipped.length)) {
          const parts: string[] = [];
          if (p.saved.length) parts.push(`saved to ${p.saved.map((s) => s.version).join(', ')}`);
          if (p.skipped.length)
            parts.push(`skipped ${p.skipped.map((s) => s.version).join(', ')}`);
          toast(`Escalated · ${parts.join(' · ')}`);
        }
        return { ok: r.resolved, detail: r.gate_failed };
      },
    });
  const onDefer = (id: string) =>
    defer.mutate(id, { onSuccess: () => toast('Deferred — snoozed from the inbox') });

  return (
    <Page
      eyebrow="G · Versioning & QA"
      title="Change flags inbox"
      width="narrow"
      intro="The anomalies a pillar lead must resolve before trusting the queue. Each names the gate that caught it; Approve re-gates the fix server-side and writes an audit row, Reject needs a reason, nothing auto-acts."
      actions={
        isAdmin && version ? (
          <button
            className="btn ghost sm"
            disabled={scan.isPending}
            onClick={() =>
              scan.mutate(version, {
                onSuccess: (r) => toast(`Scan ran · ${r.created} new flag(s) from ${r.candidates}`),
              })
            }
          >
            <Icon n="refresh" s={14} /> Scan for anomalies
          </button>
        ) : null
      }
    >
      {/* Severity toggle — the counts double as filters; composes with the kind filter below. The
          active chip is highlighted with an outline so the current severity reads at a glance. */}
      <div className="row wrap gap8" style={{ marginBottom: 12 }}>
        <button
          className={'chip ' + (sev === 'all' ? 'teal' : 'soft')}
          style={{ padding: '6px 11px', fontSize: 12, cursor: 'pointer', border: 'none' }}
          aria-pressed={sev === 'all'}
          onClick={() => setSev('all')}
        >
          {allFlags.length} All
        </button>
        {SEV_ORDER.map((k) => {
          const on = sev === k;
          return (
            <button
              key={k}
              className={'chip ' + (k === 'BLOCKING' || k === 'HIGH' ? 'orange' : 'soft')}
              style={{
                padding: '6px 11px',
                fontSize: 12,
                cursor: 'pointer',
                border: on ? '1px solid var(--border-focus)' : '1px solid transparent',
                outline: on ? '1px solid var(--border-focus)' : 'none',
              }}
              aria-pressed={on}
              onClick={() => setSev(on ? 'all' : k)}
            >
              {counts[k] ?? 0} {k}
            </button>
          );
        })}
      </div>

      {/* kind filter — a decay scan can raise hundreds of "no delivery" candidates; narrow by kind */}
      {kinds.length > 1 && (
        <div className="row wrap gap6" style={{ marginBottom: 16 }}>
          <button
            className={'btn xs ' + (kind === 'all' ? 'primary' : 'ghost')}
            onClick={() => setKind('all')}
          >
            All · {allFlags.length}
          </button>
          {kinds.map((k) => (
            <button
              key={k}
              className={'btn xs ' + (kind === k ? 'primary' : 'ghost')}
              onClick={() => setKind(k)}
            >
              {KIND_LABEL[k] ?? k} · {allFlags.filter((f) => f.kind === k).length}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: 'grid', gap: 12 }}>
        {flags.slice(0, RENDER_CAP).map((f) => (
          <div key={f.id} className="card pad fade-in">
            <div className="row gap8" style={{ marginBottom: 8 }}>
              <span className={'chip ' + (sevColor[f.sev] ?? 'soft')}>{f.sev}</span>
              <span className="chip slate">{f.kind}</span>
              {f.gate_failed && (
                <span className="chip orange mono" style={{ fontSize: 10.5 }}>
                  <Icon n="shield" s={11} /> {f.gate_failed.split('_')[0]}
                </span>
              )}
              <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
                {f.age}
              </span>
            </div>
            <div className="h2" style={{ fontSize: 14.5, marginBottom: 6 }}>
              {f.title}
            </div>
            <div
              className="muted"
              style={{ fontSize: 12.5, marginBottom: 12, lineHeight: 1.5 }}
            >
              {f.body}
            </div>

            {f.before && f.after && (
              <div
                className="card"
                style={{ background: 'var(--surface-raised)', padding: '10px 12px', marginBottom: 12 }}
              >
                <div className="eyebrow" style={{ marginBottom: 6 }}>
                  Resolution · proposed correction
                </div>
                <div className="row gap8" style={{ fontSize: 12.5, marginBottom: 4 }}>
                  <span className="muted">lifecycle</span>
                  <span className="mono">{f.before}</span>
                  <Icon n="arrowR" s={12} />
                  <b className="mono" style={{ color: 'var(--interactive)' }}>
                    {f.after}
                  </b>
                </div>
                <div className="muted" style={{ fontSize: 11.5 }}>
                  Approve re-gates G1–G8 server-side and applies it to {version || 'the version'}{' '}
                  under version control ·{' '}
                  {f.kind === 'decay_no_delivery'
                    ? 'grounded in the corpus scan (zero real Jira delivery). If delivery has since appeared, G6 blocks the change.'
                    : `${f.stories} delivered stories ground the fix.`}
                </div>
              </div>
            )}

            <div className="between" style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 12 }}>
              <div className="row gap12">
                {f.chain && (
                  <button className="linkbtn" onClick={() => openReasoning(f.chain)}>
                    <Icon n="eye" s={13} /> Reasoning
                  </button>
                )}
                {f.target && !f.target.includes(':') && f.kind !== 'unscoped_subvertical' && (
                  <button className="linkbtn" onClick={() => f.target && go('subcap/' + f.target)}>
                    Open subcap
                  </button>
                )}
                {f.kind === 'unscoped_subvertical' && (
                  <button className="linkbtn" onClick={() => go('mission-control')}>
                    View on mission control
                  </button>
                )}
                {f.target?.startsWith('news:') && (
                  <button className="linkbtn" onClick={() => go('news')}>
                    Open news watch
                  </button>
                )}
              </div>
              <div className="row gap8">
                <button
                  className="btn ghost sm"
                  disabled={defer.isPending}
                  onClick={() => onDefer(f.id)}
                >
                  Defer
                </button>
                <button
                  className="btn ghost sm"
                  disabled={reject.isPending}
                  onClick={() => onReject(f.id)}
                >
                  Reject
                </button>
                {f.kind !== 'evidence_gate_failure' && (
                  <button
                    className="btn primary sm"
                    disabled={approve.isPending}
                    onClick={() => onApprove(f)}
                  >
                    Approve <Icon n="arrowR" s={14} />
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
        {flags.length > RENDER_CAP && (
          <div className="card pad muted" style={{ fontSize: 12, textAlign: 'center' }}>
            Showing the first {RENDER_CAP} of {flags.length} {sev === 'all' ? '' : sev + ' '}
            {kind === 'all' ? '' : KIND_LABEL[kind] ?? ''} flags (highest severity first). Resolve or
            filter by kind or severity to see more — none are dropped.
          </div>
        )}
        {!flags.length && (
          <Empty
            icon="flag"
            title="Inbox zero"
            desc="No anomalies need a pillar lead right now. The scan routes any gate failure here — it never auto-acts."
            cta="Back to mission control"
            onCta={() => go('mission-control')}
          />
        )}
      </div>
    </Page>
  );
}
