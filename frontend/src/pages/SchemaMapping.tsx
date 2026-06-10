// Schema mapping (Header surface · admin) — the APPLIED mapping for each provisioned version,
// wired to GET /api/admin/mapping/{version}: every source-field -> canonical-field row the
// provisioner wrote (confidence + status) and the relations it materialized as FKs/link tables
// (control.relation_def). What this page shows IS what ran — nothing invented. Re-provision and
// carry-forward are runnable from here (admin, idempotent).
import { useState } from 'react';

import { useMapping, useProvisionActions } from '../api/queries';
import { Empty, Page, Seg } from '../components/primitives';
import { go, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

export function SchemaMapping() {
  const isAdmin = useUi((s) => s.adminView);
  const active = useUi((s) => s.version) || 'v7';
  const [ver, setVer] = useState(active);
  const mapping = useMapping(isAdmin ? ver : null);
  const { provision, carry } = useProvisionActions();
  const m = mapping.data;

  return (
    <Page
      eyebrow="Header surface · admin"
      title="Schema mapping"
      intro="Admin control over how each catalogue version maps to the canonical model. The table below is the APPLIED mapping — every row traces to the provisioning run that loaded this version; relations are the FKs and link tables it materialized."
      actions={
        <Seg
          options={[
            { v: 'v5', l: 'v5 workbook' },
            { v: 'v7', l: 'v7 workbook' },
          ]}
          value={ver}
          onChange={setVer}
        />
      }
    >
      {!isAdmin ? (
        <div className="banner warn">
          <Icon n="lock" s={15} />
          Schema mapping is admin-only. Enable the is_admin toggle to confirm field mappings, add
          custom fields and provision a catalogue version.
        </div>
      ) : (
        <>
          {mapping.isError && (
            <div className="card pad" style={{ marginBottom: 16 }}>
              <Empty
                icon="layers"
                title={`${ver} is not provisioned`}
                desc={
                  ver === 'v5'
                    ? 'The legacy v5 workbooks have not been ingested — upload them via onboarding and the applied mapping renders here.'
                    : 'Provision this version and its applied mapping renders here.'
                }
                cta="Open onboarding studio"
                onCta={() => go('onboarding')}
              />
            </div>
          )}
          {m && (
            <div
              style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 18, alignItems: 'start' }}
            >
              <div>
                <div className="card pad" style={{ marginBottom: 16 }}>
                  <div className="between" style={{ marginBottom: 8 }}>
                    <div className="h3">Field mapping · applied</div>
                    <span className="chip teal">{m.fields.length} fields</span>
                  </div>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Source field</th>
                        <th>Canonical</th>
                        <th style={{ width: 80 }}>Conf.</th>
                        <th style={{ width: 90 }}>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {m.fields.map((f, i) => (
                        <tr key={i}>
                          <td className="mono" style={{ fontSize: 11.5 }}>
                            {f.source_field}
                          </td>
                          <td className="mono" style={{ fontSize: 11.5 }}>
                            {f.canonical_entity}.{f.canonical_field}
                          </td>
                          <td className="num">{f.confidence.toFixed(2)}</td>
                          <td>
                            <span className={'chip ' + (f.status === 'confirmed' ? 'teal' : 'orange')}>
                              {f.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="card pad">
                  <div className="h3" style={{ marginBottom: 6 }}>
                    Re-apply mapping
                  </div>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 14, lineHeight: 1.5 }}>
                    Re-provisioning rebuilds cat_{ver} transactionally from the seed and re-registers
                    this mapping. Idempotent; control-plane data (stories, evidence, matches) survives.
                  </div>
                  <div className="row gap8">
                    <button
                      className="btn primary sm"
                      disabled={provision.isPending}
                      onClick={() =>
                        provision.mutate(ver, {
                          onSuccess: (r) => toast(`Provisioned ${ver} · ${r.subcaps} subcaps`),
                        })
                      }
                    >
                      Re-apply &amp; provision <Icon n="arrowR" s={14} />
                    </button>
                  </div>
                </div>
              </div>
              <div style={{ display: 'grid', gap: 14 }}>
                <div className="card pad">
                  <div className="between" style={{ marginBottom: 8 }}>
                    <div className="h3">
                      Backend relations ·{' '}
                      <span className="mono" style={{ fontWeight: 500, fontSize: 10.5 }}>
                        control.relation_def
                      </span>
                    </div>
                    <span className="chip soft">{m.relations.length}</span>
                  </div>
                  <div style={{ display: 'grid', gap: 6 }}>
                    {m.relations.map((r, i) => (
                      <div key={i} className="card" style={{ padding: '8px 10px', fontSize: 11.5 }}>
                        <span className="mono">{r.from_entity}</span>
                        <span className="muted"> —{r.rel_type}→ </span>
                        <span className="mono">{r.to_entity}</span>
                        <span className="chip soft" style={{ marginLeft: 8 }}>
                          {r.card.replace(/_/g, '·')}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="card pad" style={{ borderColor: 'var(--border-medium)' }}>
                  <div className="h3" style={{ marginBottom: 8 }}>
                    Story carry-forward
                  </div>
                  <div className="muted" style={{ fontSize: 11.5, marginBottom: 12, lineHeight: 1.5 }}>
                    Canonical Jira mappings carried onto {ver}: native links first, crosswalk next,
                    nearest-neighbour to confirm; borderline routes to review.
                  </div>
                  <button
                    className="btn ghost sm"
                    style={{ width: '100%', justifyContent: 'center' }}
                    disabled={carry.isPending}
                    onClick={() =>
                      carry.mutate(ver, {
                        onSuccess: () => toast('Carry-forward complete'),
                      })
                    }
                  >
                    {carry.isPending ? 'Carrying forward…' : 'Run carry-forward'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </Page>
  );
}
