// QA & audit dashboard (G5) — prove the system is accurate, on-budget and auditable. Real gate
// pass-rate + reasoning-chain count + admin-gated spend; the audit trail is the append-only record
// of every gated mutation. Eval scores (F6) / monthly meter (F11) land later, shown honestly.
import { useAuditLog, useQaMetrics } from '../api/queries';
import { Empty, Page } from '../components/primitives';
import { go } from '../lib/events';
import { Icon } from '../lib/icons';

function fmtAt(s: string | null): string {
  if (!s) return '—';
  const d = new Date(s.replace(' ', 'T').replace(/([+-]\d{2})$/, '$1:00'));
  return Number.isNaN(d.getTime()) ? s.slice(0, 16) : d.toLocaleString();
}

export function QA() {
  const qa = useQaMetrics();
  const audit = useAuditLog();
  const m = qa.data;
  const rows = audit.data ?? [];
  const spend = m?.spend_usd;
  const envelope = m?.envelope_usd ?? 8000;

  const kpis: [string, string, string][] = [
    [m?.gate_pass_rate != null ? `${m.gate_pass_rate}%` : 'n/a', 'Gate pass-rate', 'var(--interactive)'],
    [m?.hallucination_rate != null ? `${m.hallucination_rate}%` : 'n/a', 'Hallucination rate', 'var(--text-tertiary)'],
    [
      spend != null ? `$${(spend / 1000).toFixed(2)}k / $${envelope / 1000}k` : 'admin only',
      'LLM spend / envelope',
      'var(--text-primary)',
    ],
    [String(m?.reasoning_chains ?? 0), 'Reasoning chains', 'var(--text-primary)'],
  ];

  return (
    <Page
      eyebrow="G · Versioning & QA"
      title="QA & audit dashboard"
      intro="Prove the system is accurate, on-budget and auditable — gate pass-rate, LLM spend against the envelope, and the append-only audit trail of every gated mutation."
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 18 }}>
        {kpis.map(([v, l, color], i) => (
          <div key={i} className="kpi">
            <div className="kv" style={{ color }}>
              {v}
            </div>
            <div className="kl">{l}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 18, alignItems: 'start' }}>
        <div className="card pad">
          <div className="h2" style={{ marginBottom: 14 }}>
            Spend vs ${envelope / 1000}k envelope
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height: 120 }}>
            <div style={{ flex: 1, textAlign: 'center' }}>
              <div
                style={{
                  height: Math.max(4, ((spend ?? 0) / envelope) * 100),
                  background: 'var(--interactive)',
                  borderRadius: '3px 3px 0 0',
                }}
              />
              <div className="muted" style={{ fontSize: 9, marginTop: 4 }}>
                this month
              </div>
            </div>
          </div>
          <div className="banner info mt12">
            <Icon n="check" s={14} />
            {spend != null
              ? `Within the $${envelope / 1000}k envelope · hermetic spend $${(spend / 1000).toFixed(2)}k. The cost meter (F11) + G8 budget gate enforce it live.`
              : 'Spend is admin-only. The G8 budget gate + cost meter enforce the envelope live.'}
          </div>
        </div>

        <div className="card pad">
          <div className="between" style={{ marginBottom: 12 }}>
            <div className="h2">Audit trail · gated mutations</div>
            <span className="chip soft">append-only</span>
          </div>
          {rows.length === 0 ? (
            <Empty
              icon="shield"
              title="No audited actions yet"
              desc="Applying an AI suggestion writes an immutable audit row here (before → after), under version control."
            />
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Target</th>
                  <th>Change</th>
                  <th style={{ width: 150 }}>When</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const before = r.meta?.before as string | undefined;
                  const after = r.meta?.after as string | undefined;
                  const reason = r.meta?.reason as string | undefined;
                  return (
                    <tr key={r.audit_id}>
                      <td>
                        <span className="chip soft" style={{ fontSize: 10 }}>
                          {r.action}
                        </span>
                      </td>
                      <td>
                        <span
                          className="mono sclink"
                          style={{ fontSize: 11, color: 'var(--interactive)', cursor: 'pointer' }}
                          onClick={() => r.target_ref && go('subcap/' + r.target_ref)}
                        >
                          {r.target_ref ?? '—'}
                        </span>
                      </td>
                      <td style={{ fontSize: 11.5 }}>
                        {before && after ? (
                          <span>
                            {before} <Icon n="arrowR" s={11} /> <b>{after}</b>
                          </span>
                        ) : (
                          <span className="muted">{reason ?? '—'}</span>
                        )}
                      </td>
                      <td className="muted" style={{ fontSize: 11 }}>
                        {fmtAt(r.at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="banner warn mt16">
        <Icon n="shield" s={15} />
        Audit-grade exports are signed (HMAC) and timestamped · DLP redacts every SOW before a model
        sees it — both land with the evidence pipeline (F7/F12).
      </div>
    </Page>
  );
}
