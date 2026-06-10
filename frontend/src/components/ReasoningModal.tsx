// Reasoning chain viewer (H2) — the universal audit window. Mounted by the Shell on the `cia-reason`
// event; fetches GET /api/reasoning/{id} and shows the ordered steps, evidence rows, and the gate
// checks the system ran before showing the answer. Focus-trapped (UIUX: the core trust surface is
// "a focus-trapped modal"); Escape closes; focus returns to the opening element.
import { useReasoning } from '../api/queries';
import { Icon } from '../lib/icons';
import { useFocusTrap } from '../lib/useFocusTrap';
import { Claim } from './primitives';

export function ReasoningModal({ chainId, onClose }: { chainId: string; onClose: () => void }) {
  const q = useReasoning(chainId);
  const ch = q.data;
  const ref = useFocusTrap<HTMLDivElement>(onClose);

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
            {ch ? (
              <>
                <div className="row gap8" style={{ marginBottom: 7 }}>
                  {ch.claim_label && <Claim label={ch.claim_label} />}
                  <span className="chip soft">
                    <Icon n="eye" s={12} /> verdict: {ch.verdict ?? '—'}
                  </span>
                  <span className="muted" style={{ fontSize: 11 }}>
                    cost {ch.cost} · reproducible
                  </span>
                </div>
                <div className="h1" style={{ fontSize: 19 }}>
                  {ch.title}
                </div>
              </>
            ) : (
              <div className="h1" style={{ fontSize: 19 }}>
                {q.isError ? 'Reasoning chain unavailable' : 'Loading reasoning…'}
              </div>
            )}
          </div>
          <button className="modal-x" onClick={onClose}>
            <Icon n="x" s={16} />
          </button>
        </div>
        <div className="modal-body">
          {ch && (
            <>
              <div className="muted" style={{ fontSize: 12, marginBottom: 16 }}>
                Every step the model took to reach this, in order. Nothing is hidden behind a code.
              </div>
              {ch.steps.map((s, i) => (
                <div className="rstep" key={i}>
                  <span className="rnum">{i + 1}</span>
                  <div className="rh">
                    Step {i + 1} · {s.kind}
                  </div>
                  <div className="rt">{s.text}</div>
                  {s.evidence.map((e, j) => (
                    <div className="evrow" key={j}>
                      <Claim label={e.claim_label} />
                      <span className="tierchip">{e.tier}</span>
                      <span style={{ flex: 1 }}>{e.text}</span>
                    </div>
                  ))}
                </div>
              ))}
              <div className="divider" />
              <div className="h3" style={{ marginBottom: 12 }}>
                Checks the system ran before showing this
              </div>
              <div style={{ display: 'grid', gap: 10 }}>
                {ch.checks.map((c, i) => (
                  <div
                    key={i}
                    className="card pad"
                    style={{ padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 14 }}
                  >
                    <span
                      className={'chip ' + (c.state === 'Passed' ? 'teal' : 'orange')}
                      style={{ minWidth: 96, justifyContent: 'center' }}
                    >
                      <Icon n={c.state === 'Passed' ? 'check' : 'alert'} s={12} /> {c.state}
                    </span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 600 }}>{c.name}</div>
                      <div className="muted" style={{ fontSize: 11 }}>
                        {c.detail}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
