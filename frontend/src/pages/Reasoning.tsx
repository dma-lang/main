// Reasoning chain viewer (H2) — the core trust surface. The prototype lists a few demo chains;
// ours lists the REAL recent chains from GET /api/reasoning (newest first). Clicking one opens the
// universal ReasoningModal (cia-reason) with the steps, evidence, gate checks and verdict.
import { useReasoningList } from '../api/queries';
import { Claim, Empty, Page } from '../components/primitives';
import { openReasoning } from '../lib/events';
import { Icon } from '../lib/icons';

export function Reasoning() {
  const chains = useReasoningList(50);

  return (
    <Page
      eyebrow="H · Reasoning & RAG"
      title="Reasoning chain viewer"
      width="narrow"
      intro="The core trust surface. Every AI output can be opened as a plain-language chain that reads top to bottom — the question, the steps in order, the evidence with readable source descriptions, contradictions, the conclusion, an adversarial self-review, and the checks it ran."
    >
      {chains.isLoading && <div className="muted">Loading reasoning chains…</div>}
      {chains.isError && (
        <Empty
          icon="sparkles"
          title="Reasoning chains unavailable"
          desc="The reasoning store could not be read. Once AI surfaces (chat, news, suggestions) run, their chains appear here."
        />
      )}
      {chains.data && chains.data.length === 0 && (
        <Empty
          icon="sparkles"
          title="No reasoning chains yet"
          desc="Reasoning chains are written whenever an AI surface produces a value — ask the AI chat a question, or run a news/vendor scan, and they show up here."
        />
      )}
      {chains.data && chains.data.length > 0 && (
        <div style={{ display: 'grid', gap: 10 }}>
          {chains.data.map((c) => (
            <div
              key={c.chain_id}
              className="card pad hov"
              style={{ cursor: 'pointer' }}
              onClick={() => openReasoning(c.chain_id)}
            >
              <div className="between">
                <div className="row gap10">
                  <div
                    style={{
                      width: 34,
                      height: 34,
                      borderRadius: 8,
                      background: 'var(--surface-overlay)',
                      color: 'var(--z-teal)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flex: 'none',
                    }}
                  >
                    <Icon n="sparkles" s={16} />
                  </div>
                  <div>
                    <div style={{ fontSize: 13.5, fontWeight: 600 }}>{c.title}</div>
                    <div className="row gap6 mt8">
                      {c.claim_label && <Claim label={c.claim_label} />}
                      {c.verdict && (
                        <span className={'chip ' + (c.verdict === 'pass' ? 'teal' : 'orange')}>
                          {c.verdict}
                        </span>
                      )}
                      <span className="muted" style={{ fontSize: 11 }}>
                        {c.steps} steps · {c.cost}
                        {c.model ? ' · ' + c.model : ''}
                      </span>
                    </div>
                  </div>
                </div>
                <Icon n="arrowR" s={16} style={{ color: 'var(--text-tertiary)' }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </Page>
  );
}
