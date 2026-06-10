// Validation gates log (G4) — transparency into how the 8 deterministic gates run: the per-gate
// pass / warn / fail distribution from every reasoning chain's gate run. Read-only. Ported from the
// prototype, wired to GET /api/gates (aggregated over control.validation_gate_run).
import { useGates } from '../api/queries';
import { Empty, Page } from '../components/primitives';
import { Icon } from '../lib/icons';

export function Gates() {
  const q = useGates();
  const gates = q.data?.gates ?? [];

  return (
    <Page
      eyebrow="G · Versioning & QA"
      title="Validation gates log"
      intro="Transparency into how the 8 deterministic gates are running — the pass / warn / fail distribution across every reasoning chain, computed from the stored gate runs. Each gate is code, not a prompt."
    >
      {gates.length === 0 ? (
        <Empty
          icon="shield"
          title="No gate runs yet"
          desc="The gates run on every grounded answer and AI suggestion. Ask the AI chat something or run the suggestion cycle, and the distribution appears here."
        />
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 18 }}>
            {gates.map((g) => (
              <div key={g.id} className="card" style={{ padding: '10px 14px' }}>
                <div className="row gap8">
                  <span className="chip soft mono">{g.id}</span>
                  <span style={{ fontSize: 12.5, fontWeight: 600 }}>{g.name}</span>
                  <span className="chip teal" style={{ marginLeft: 'auto' }}>
                    <Icon n="check" s={11} /> active
                  </span>
                </div>
              </div>
            ))}
          </div>
          <div className="card pad">
            <div className="between" style={{ marginBottom: 14 }}>
              <div className="h2">Pass / warn / fail · all reasoning chains</div>
              <span className="chip soft">
                {q.data?.pass_runs}/{q.data?.total_runs} runs passed
              </span>
            </div>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Gate</th>
                  <th style={{ width: '40%' }}>Distribution</th>
                  <th style={{ width: 70 }}>Pass</th>
                  <th style={{ width: 70 }}>Score</th>
                </tr>
              </thead>
              <tbody>
                {gates.map((g) => (
                  <tr key={g.id} style={{ cursor: 'default' }}>
                    <td>
                      <b>
                        {g.id} {g.name}
                      </b>
                    </td>
                    <td>
                      <div style={{ display: 'flex', height: 10, borderRadius: 4, overflow: 'hidden' }}>
                        <div style={{ width: g.pass_pct + '%', background: 'var(--interactive)' }} />
                        <div style={{ width: g.warn_pct + '%', background: 'var(--z-orange-lt)' }} />
                        <div style={{ width: g.fail_pct + '%', background: 'var(--z-orange)' }} />
                      </div>
                    </td>
                    <td>
                      <b className="num">{g.pass_pct}%</b>
                    </td>
                    <td>
                      <span
                        className="mono"
                        style={{
                          fontWeight: 700,
                          color: g.score >= 0.8 ? 'var(--interactive)' : 'var(--z-orange)',
                        }}
                      >
                        {g.score.toFixed(2)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="row gap16 mt12" style={{ fontSize: 11 }}>
              <span className="row gap6">
                <span className="pilldot" style={{ background: 'var(--interactive)' }} /> pass
              </span>
              <span className="row gap6">
                <span className="pilldot" style={{ background: 'var(--z-orange-lt)' }} /> warn
              </span>
              <span className="row gap6">
                <span className="pilldot" style={{ background: 'var(--z-orange)' }} /> fail
              </span>
            </div>
          </div>
        </>
      )}
    </Page>
  );
}
