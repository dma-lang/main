// AI suggestions (D3) — the gated-mutation queue. Apply or reject AI-proposed catalogue edits with
// full evidence; Apply re-gates server-side, mutates cat_<v> and writes an audit row. Every card
// carries the trust envelope (tier · claim · ERS) + the gate verdict + a reasoning backlink.
import type { SuggestionOut } from '../api/client';
import { useSuggestionActions, useSuggestions } from '../api/queries';
import { Claim, Empty, Page, Tier } from '../components/primitives';
import { go, openCommit, openReasoning, toast } from '../lib/events';
import { passesTrustFloor } from '../lib/helpers';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

export function Suggestions() {
  const version = useUi((s) => s.version);
  const isAdmin = useUi((s) => s.adminView);
  const pending = useSuggestions('pending');
  const applied = useSuggestions('applied');
  const rejected = useSuggestions('rejected');
  const { propose, apply, reject } = useSuggestionActions();
  const claimF = useUi((s) => s.claim);
  const tierF = useUi((s) => s.tier);
  const live = (pending.data ?? []).filter((s) =>
    passesTrustFloor(s.claim_label, s.source_tier, claimF, tierF),
  );

  const onReject = (id: string) => {
    const reason = window.prompt('Reason for rejecting this suggestion?')?.trim();
    if (!reason) return;
    reject.mutate({ id, reason }, { onSuccess: () => toast('Rejected — reason logged') });
  };
  const onApply = (id: string) =>
    apply.mutate(id, {
      onSuccess: (r) =>
        toast(
          r.applied
            ? `Applied under version control · ${r.before} → ${r.after} · audit logged`
            : r.gate_failed
              ? `Blocked by ${r.gate_failed} on re-gate — routed to review`
              : `Already ${r.status}`,
        ),
    });
  // Breaking edits get the COMMIT-tier friction surface: the modal's run executes the same apply
  // mutation, which re-gates G1–G8 server-side and writes the snapshot + audit row.
  const onReviewCommit = (s: SuggestionOut) =>
    openCommit({
      title: s.title,
      kind: s.kind,
      summary: s.rationale,
      target: s.target_subcap,
      onRejectInstead: () => onReject(s.suggestion_id),
      run: async () => {
        const r = await apply.mutateAsync(s.suggestion_id);
        return { ok: r.applied, detail: r.gate_failed };
      },
    });

  return (
    <Page
      eyebrow="D · Public intelligence"
      title="AI suggestions"
      width="narrow"
      intro="Apply or reject AI-proposed catalogue edits with full evidence. Apply re-gates G1–G8 server-side, writes a versioned change and an append-only audit row; nothing commits ungated."
      actions={
        isAdmin && version ? (
          <button
            className="btn ghost sm"
            disabled={propose.isPending}
            onClick={() =>
              propose.mutate(version, {
                onSuccess: (r) => toast(`Suggestion cycle ran · ${r.created} proposed`),
              })
            }
          >
            <Icon n="sparkles" s={14} /> Run suggestion cycle
          </button>
        ) : null
      }
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginBottom: 18 }}>
        <div className="kpi">
          <div className="kv">{live.length}</div>
          <div className="kl">Pending</div>
        </div>
        <div className="kpi">
          <div className="kv">{applied.data?.length ?? 0}</div>
          <div className="kl">Applied</div>
        </div>
        <div className="kpi">
          <div className="kv">{rejected.data?.length ?? 0}</div>
          <div className="kl">Rejected</div>
        </div>
      </div>

      <div style={{ display: 'grid', gap: 12 }}>
        {live.map((s) => (
          <div key={s.suggestion_id} className="card pad fade-in">
            <div className="row gap8" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
              <span className="chip soft">pending</span>
              <span className={'chip ' + (s.verdict === 'pass' ? 'teal' : 'orange')}>
                <Icon n="shield" s={11} /> {(s.verdict ?? 'n/a').toUpperCase()}
              </span>
              {s.breaking && (
                <span className="chip orange">
                  <Icon n="alert" s={11} /> BREAKING
                </span>
              )}
              <span className="chip soft">{s.kind}</span>
              <span className="muted mono" style={{ fontSize: 11, marginLeft: 'auto' }}>
                {s.cost}
              </span>
            </div>
            <div className="h2" style={{ fontSize: 15, marginBottom: 6 }}>
              {s.title}
            </div>
            <div className="muted" style={{ fontSize: 12.5, marginBottom: 10 }}>
              Target:{' '}
              <span
                className="mono sclink"
                style={{ color: 'var(--interactive)', cursor: 'pointer' }}
                onClick={() => s.target_subcap && go('subcap/' + s.target_subcap)}
              >
                {s.target_subcap}
              </span>{' '}
              · {s.pillar} · monthly cycle. {s.rationale}
            </div>
            <div className="row gap6" style={{ marginBottom: 12 }}>
              {s.source_tier && <Tier t={s.source_tier} />}
              {s.claim_label && <Claim label={s.claim_label} />}
              <span className="muted" style={{ fontSize: 11 }}>
                ERS {s.ers}
              </span>
            </div>
            <div
              className="between"
              style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 12 }}
            >
              <div className="row gap12">
                {s.chain_id && (
                  <button className="linkbtn" onClick={() => openReasoning(s.chain_id)}>
                    <Icon n="eye" s={13} /> Reasoning
                  </button>
                )}
                {s.target_subcap && (
                  <button className="linkbtn" onClick={() => go('subcap/' + s.target_subcap)}>
                    Open subcap
                  </button>
                )}
              </div>
              <div className="row gap8">
                <button
                  className="btn ghost sm"
                  disabled={reject.isPending}
                  onClick={() => onReject(s.suggestion_id)}
                >
                  Reject
                </button>
                {s.breaking ? (
                  <button className="btn danger sm" onClick={() => onReviewCommit(s)}>
                    Review &amp; commit <Icon n="arrowR" s={14} />
                  </button>
                ) : (
                  <button
                    className="btn primary sm"
                    disabled={apply.isPending}
                    onClick={() => onApply(s.suggestion_id)}
                  >
                    Apply <Icon n="arrowR" s={14} />
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
        {!live.length && (
          <Empty
            icon="sparkles"
            title="No pending suggestions"
            desc="The monthly consultant cycle proposes evidence-backed catalogue edits. Run it to populate the queue."
          />
        )}
      </div>
    </Page>
  );
}
