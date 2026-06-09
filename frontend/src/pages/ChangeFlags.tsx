// Change flags inbox (G3) — the human-review choke-point. The anomalies a pillar lead must resolve
// before trusting the queue: lifecycle-vs-delivery contradictions the gates (G6) caught. Approve
// re-gates the proposed correction G1–G8 server-side and, on pass, mutates cat_<v> + writes an
// audit row; Reject needs a reason; Defer snoozes. Wired to GET /api/change-flags. Ported from the
// prototype ChangeFlags.
import { useChangeFlags, useFlagActions } from '../api/queries';
import { Empty, Page } from '../components/primitives';
import { go, openReasoning, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const SEV_ORDER = ['BLOCKING', 'HIGH', 'MED', 'LOW'];
const sevColor: Record<string, string> = {
  BLOCKING: 'orange',
  HIGH: 'orange',
  MED: 'soft',
  LOW: 'soft',
};

export function ChangeFlags() {
  const version = useUi((s) => s.version);
  const isAdmin = useUi((s) => s.adminView);
  const q = useChangeFlags('open');
  const { scan, approve, reject, defer } = useFlagActions();
  const flags = q.data?.flags ?? [];
  const counts = q.data?.counts ?? { BLOCKING: 0, HIGH: 0, MED: 0, LOW: 0 };

  const onApprove = (id: string) =>
    approve.mutate(id, {
      onSuccess: (r) =>
        toast(
          r.resolved
            ? `Corrected ${r.before} → ${r.after} · logged to audit trail`
            : r.gate_failed
              ? `Re-gate blocked by ${r.gate_failed} — flag stays open`
              : `Already ${r.status}`,
        ),
    });
  const onReject = (id: string) => {
    const reason = window.prompt('Reason for rejecting this flag?')?.trim();
    if (!reason) return;
    reject.mutate({ id, reason }, { onSuccess: () => toast('Rejected — reason logged to audit') });
  };
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
      <div className="row gap8" style={{ marginBottom: 18 }}>
        {SEV_ORDER.map((k) => (
          <span
            key={k}
            className={'chip ' + (k === 'BLOCKING' ? 'orange' : 'soft')}
            style={{ padding: '6px 11px', fontSize: 12 }}
          >
            {counts[k] ?? 0} {k}
          </span>
        ))}
      </div>

      <div style={{ display: 'grid', gap: 12 }}>
        {flags.map((f) => (
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
                  under version control · {f.stories} delivered stories ground the fix.
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
                {f.target && (
                  <button className="linkbtn" onClick={() => f.target && go('subcap/' + f.target)}>
                    Open subcap
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
                <button
                  className="btn primary sm"
                  disabled={approve.isPending}
                  onClick={() => onApprove(f.id)}
                >
                  Approve <Icon n="arrowR" s={14} />
                </button>
              </div>
            </div>
          </div>
        ))}
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
