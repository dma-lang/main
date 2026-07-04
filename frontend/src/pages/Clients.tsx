// Client journey atlas (F3, FR-19) — entity-resolved clients wired to GET /api/clients +
// /clients/{key}/journey. A client is the deterministic key join of the SOW corpus
// (account_key) and the Jira delivery corpus (project_key) — never a fuzzy auto-merge. The
// journey lists dated SOW signings + their gated scope matches (trust envelope + reasoning per
// match) and the delivery footprint (top subcaps by story volume).
import { useState } from 'react';

import { useClientJourney, useClients } from '../api/queries';
import { Claim, Empty, Page, SC } from '../components/primitives';
import { go, openReasoning, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

// Entity-resolution confidence for the client identity — text, not colour-only (WCAG). Absent when
// the key carries no resolved-client confidence (e.g. a SOW-only account).
function ConfChip({ v }: { v: number | null | undefined }) {
  if (v == null) return null;
  const pct = Math.round(v * 100);
  const cls = v >= 0.8 ? 'teal' : v >= 0.5 ? 'soft' : 'orange';
  return (
    <span className={'chip ' + cls} style={{ fontSize: 10 }} title="entity-resolution confidence for this client identity">
      match {pct}%
    </span>
  );
}

export function Clients() {
  const ui = useUi();
  const [sel, setSel] = useState<string | null>(null);
  const roster = useClients(ui.version);
  const active = sel ?? roster.data?.[0]?.key ?? null;
  const journey = useClientJourney(active, ui.version);
  const j = journey.data;

  return (
    <Page
      eyebrow="F · Lifecycle & competition"
      title="Client journey atlas"
      intro="A unified, entity-resolved view of each client, and the packet you hand to the DMA team — exported as validated, signed JSON. Resolution is a deterministic key join across the SOW and delivery corpora; an ambiguous identity stays separate until a human merges it."
      actions={
        <button
          className="btn ghost sm"
          onClick={() => toast('DMA packet export reuses the signed-export path (F12) — soon')}
        >
          <Icon n="file" s={14} /> Export DMA packet
        </button>
      }
    >
      {roster.data && roster.data.length === 0 && (
        <div className="card pad">
          <Empty
            icon="route"
            title="No clients resolved yet"
            desc="Clients appear when the SOW corpus is scanned or the story corpus is carried forward — run the SOW scan in the SOW library, or carry-forward in onboarding."
            cta="Open SOW library"
            onCta={() => go('sow')}
          />
        </div>
      )}

      {roster.data && roster.data.length > 0 && (
        <div
          style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 18, alignItems: 'start' }}
        >
          <div style={{ display: 'grid', gap: 8 }}>
            {roster.data.map((c) => (
              <div
                key={c.key}
                className="card hov"
                onClick={() => setSel(c.key)}
                style={{
                  padding: '11px 13px',
                  cursor: 'pointer',
                  borderColor: active === c.key ? 'var(--border-strong)' : 'var(--border-subtle)',
                  background: active === c.key ? 'var(--surface-overlay)' : 'var(--surface-base)',
                }}
              >
                <div className="row gap8" style={{ minWidth: 0 }}>
                  {/* the resolved client NAME is the prominent title; the key/project is secondary */}
                  <b
                    style={{ fontSize: 12.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {c.client_name ?? c.key}
                  </b>
                  <span className="muted" style={{ fontSize: 10.5, marginLeft: 'auto', flex: 'none' }}>
                    {c.last_sow ?? ''}
                  </span>
                </div>
                {c.client_name && c.client_name !== c.key && (
                  <div className="mono muted" style={{ fontSize: 10, marginTop: 2 }}>
                    {c.key}
                  </div>
                )}
                <div className="row wrap gap8 mt8" style={{ fontSize: 10.5 }}>
                  <span className="chip soft">{c.sows} SOWs</span>
                  <span className="chip soft">{c.stories.toLocaleString()} stories</span>
                  <span className="chip teal">{c.subcaps_touched} subcaps</span>
                  {c.projects > 1 && <span className="chip soft">{c.projects} projects</span>}
                </div>
              </div>
            ))}
          </div>

          <div style={{ display: 'grid', gap: 14 }}>
            {journey.isLoading && (
              <div className="card pad muted" style={{ fontSize: 12 }}>
                Resolving the journey…
              </div>
            )}
            {j && (
              <>
                <div className="card pad">
                  <div className="between" style={{ marginBottom: 10 }}>
                    <div style={{ minWidth: 0 }}>
                      {/* the resolved client name is the journey title + its match-confidence chip */}
                      <div className="row gap8" style={{ flexWrap: 'wrap' }}>
                        <div className="h2">{j.client_name ?? j.key}</div>
                        <ConfChip v={j.client_match_confidence} />
                      </div>
                      <div className="row gap8 mt8" style={{ flexWrap: 'wrap' }}>
                        {j.client_name && j.client_name !== j.key && (
                          <span className="mono muted" style={{ fontSize: 11 }}>
                            {j.key}
                          </span>
                        )}
                        {j.salesforce_account_id && (
                          <span className="chip soft mono" style={{ fontSize: 9.5 }} title="Salesforce account id">
                            SFDC {j.salesforce_account_id}
                          </span>
                        )}
                      </div>
                    </div>
                    <span className="chip soft" style={{ flex: 'none' }}>
                      {j.stories.toLocaleString()} delivered stories
                    </span>
                  </div>
                  <div className="eyebrow" style={{ marginBottom: 8 }}>
                    Engagement timeline
                  </div>
                  {j.sows.length === 0 && (
                    <div className="muted" style={{ fontSize: 12 }}>
                      No SOW on file for this key — the journey shows delivery only.
                    </div>
                  )}
                  <div style={{ display: 'grid', gap: 8 }}>
                    {j.sows.map((s) => (
                      <div
                        key={s.sow_id}
                        className="card"
                        style={{ padding: '10px 12px', borderLeft: '3px solid var(--z-blue)' }}
                      >
                        <div className="row gap8">
                          <Icon n="file" s={13} style={{ color: 'var(--z-blue)' }} />
                          <b style={{ fontSize: 12.5 }}>{s.title}</b>
                          <span className="muted" style={{ fontSize: 10.5, marginLeft: 'auto' }}>
                            signed {s.signed_date ?? '—'}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {j.matches.length > 0 && (
                  <div className="card pad">
                    <div className="eyebrow" style={{ marginBottom: 8 }}>
                      Scoped capabilities (gated matches)
                    </div>
                    <div style={{ display: 'grid', gap: 6 }}>
                      {j.matches.map((m, i) => (
                        <div key={i} className="row gap8" style={{ fontSize: 12, flexWrap: 'wrap' }}>
                          <SC id={m.subcap_id} />
                          <span
                            className="muted"
                            style={{
                              fontSize: 11.5,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              maxWidth: 230,
                            }}
                          >
                            {m.subcap_name}
                          </span>
                          <span className={'chip ' + (m.status === 'confirmed' ? 'teal' : 'orange')}>
                            {m.status}
                          </span>
                          <Claim label={m.claim_label} />
                          {m.chain_id && (
                            <button className="linkbtn" onClick={() => openReasoning(m.chain_id)}>
                              <Icon n="eye" s={12} /> Reasoning
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="card pad">
                  <div className="eyebrow" style={{ marginBottom: 8 }}>
                    Delivery footprint · top subcaps
                  </div>
                  {j.top_delivery.length === 0 ? (
                    <div className="muted" style={{ fontSize: 12 }}>
                      No carried stories for this key yet — run carry-forward to light this up.
                    </div>
                  ) : (
                    <div style={{ display: 'grid', gap: 6 }}>
                      {j.top_delivery.map((t) => (
                        <div key={t.subcap_id} className="row gap8" style={{ fontSize: 12 }}>
                          <SC id={t.subcap_id} />
                          <span
                            className="muted"
                            style={{
                              fontSize: 11.5,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {t.subcap_name}
                          </span>
                          <span className="num" style={{ marginLeft: 'auto', fontWeight: 600, fontSize: 12 }}>
                            {t.stories.toLocaleString()}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </Page>
  );
}
