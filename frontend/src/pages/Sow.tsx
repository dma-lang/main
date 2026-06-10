// SOW library (C1, FR-7) — the contractual delivery corpus as gated subcap evidence, wired to
// GET /api/sow + /api/sow/{id}. Master-detail: roster with per-document match-band counts; detail
// with the DLP/redaction banner, scope clauses and the gated match table (similarity · status ·
// claim · tier · reasoning backlink). "Confirm" is the human attestation (review -> confirmed,
// claim -> FACT, audited). Admin can run the scan; a re-scan is idempotent.
import { useState } from 'react';

import type { SowItem } from '../api/client';
import { useSowActions, useSowDetail, useSows } from '../api/queries';
import { Claim, Empty, Page, SC, Tier } from '../components/primitives';
import { openReasoning, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

function MatchRow({ item, onConfirm }: { item: SowItem; onConfirm: (id: string) => void }) {
  const chip = item.status === 'confirmed' ? 'teal' : item.status === 'review' ? 'orange' : 'soft';
  return (
    <div className="card" style={{ padding: '10px 12px' }}>
      <div
        style={{ fontSize: 12.5, color: 'var(--text-primary)', lineHeight: 1.45, marginBottom: 7 }}
      >
        <span className="mono muted" style={{ fontSize: 10.5, marginRight: 8 }}>
          §{item.ordinal}
        </span>
        {item.clause}
      </div>
      <div className="row gap8" style={{ flexWrap: 'wrap' }}>
        {item.status && <span className={'chip ' + chip}>{item.status}</span>}
        {item.subcap_id && item.status !== 'unmapped' ? (
          <>
            <SC id={item.subcap_id} />
            <span
              className="muted"
              style={{
                fontSize: 11.5,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                maxWidth: 220,
              }}
            >
              {item.subcap_name}
            </span>
          </>
        ) : (
          <span className="muted" style={{ fontSize: 11.5 }}>
            no catalogue match above the floor — kept for review, never dropped
          </span>
        )}
        {item.similarity != null && (
          <span
            className="mono num"
            style={{ fontSize: 11, color: 'var(--interactive)', fontWeight: 600 }}
          >
            {item.similarity.toFixed(2)}
          </span>
        )}
        {item.claim_label && <Claim label={item.claim_label} />}
        {item.source_tier && <Tier t={item.source_tier} />}
        <span className="grow" />
        {item.chain_id && (
          <button className="linkbtn" onClick={() => openReasoning(item.chain_id)}>
            <Icon n="eye" s={12} /> Reasoning
          </button>
        )}
        {item.status === 'review' && item.match_id && (
          <button className="btn primary xs" onClick={() => onConfirm(item.match_id ?? '')}>
            Confirm <Icon n="check" s={12} />
          </button>
        )}
        {item.confirmed_by && (
          <span className="muted" style={{ fontSize: 10.5 }}>
            attested · {item.confirmed_by}
          </span>
        )}
      </div>
    </div>
  );
}

export function Sow() {
  const ui = useUi();
  const isAdmin = useUi((s) => s.adminView);
  const [sel, setSel] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const docs = useSows(ui.version);
  const { scan, confirm } = useSowActions();
  const list = (docs.data ?? []).filter(
    (d) =>
      !q ||
      d.account_key.toLowerCase().includes(q.toLowerCase()) ||
      d.title.toLowerCase().includes(q.toLowerCase()),
  );
  const active = sel ?? list[0]?.sow_id ?? null;
  const detail = useSowDetail(active, ui.version);

  const onConfirm = (matchId: string) =>
    confirm.mutate(matchId, {
      onSuccess: () => toast('Match confirmed — human-attested FACT, audit logged'),
    });

  return (
    <Page
      eyebrow="C · Project validation"
      title="SOW library"
      intro="The contractual corpus as gated subcap evidence. Every scope clause is DLP-redacted before matching, scored against the active catalogue, and lands in a confidence band — confirmed, review or unmapped — with its reasoning one click away. Nothing is dropped."
      actions={
        <div className="row gap8">
          <div className="searchbox">
            <Icon n="search" s={15} />
            <input
              placeholder="Search account or title…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          {isAdmin && ui.version && (
            <button
              className="btn ghost sm"
              disabled={scan.isPending}
              onClick={() =>
                scan.mutate(ui.version, {
                  onSuccess: (r) =>
                    toast(
                      `Scan ran · ${r.matched} matched (${r.confirmed} confirmed, ${r.review} review, ${r.unmapped} unmapped) · ${r.deduped} deduped`,
                    ),
                })
              }
            >
              <Icon n="refresh" s={14} /> Scan corpus
            </button>
          )}
        </div>
      }
    >
      <div className="banner info" style={{ marginBottom: 16 }}>
        <Icon n="shield" s={14} />
        Redaction confirmed — every document is DLP-redacted before any model-facing step reads a
        byte; the corpus below is the redacted form.
      </div>

      {docs.data && docs.data.length === 0 && (
        <div className="card pad">
          <Empty
            icon="file"
            title="No SOWs ingested yet"
            desc="Run the corpus scan to ingest the SOW library and match every scope clause against the active catalogue version."
            cta={isAdmin ? 'Scan corpus' : undefined}
            onCta={isAdmin ? () => scan.mutate(ui.version) : undefined}
          />
        </div>
      )}

      {list.length > 0 && (
        <div
          style={{ display: 'grid', gridTemplateColumns: '330px 1fr', gap: 18, alignItems: 'start' }}
        >
          <div style={{ display: 'grid', gap: 8 }}>
            {list.map((d) => (
              <div
                key={d.sow_id}
                className="card hov"
                onClick={() => setSel(d.sow_id)}
                style={{
                  padding: '11px 13px',
                  cursor: 'pointer',
                  borderColor:
                    active === d.sow_id ? 'var(--border-strong)' : 'var(--border-subtle)',
                  background: active === d.sow_id ? 'var(--surface-overlay)' : 'var(--surface-base)',
                }}
              >
                <div className="row gap8" style={{ marginBottom: 4 }}>
                  <b className="mono" style={{ fontSize: 11.5 }}>
                    {d.account_key}
                  </b>
                  {d.sv_code && <span className="chip soft">{d.sv_code}</span>}
                  <span className="muted" style={{ fontSize: 10.5, marginLeft: 'auto' }}>
                    {d.signed_date ?? '—'}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-primary)', lineHeight: 1.35 }}>
                  {d.title}
                </div>
                <div className="row gap6 mt8" style={{ fontSize: 10.5 }}>
                  <span className="chip teal">{d.confirmed} confirmed</span>
                  <span className="chip orange">{d.review} review</span>
                  <span className="chip soft">{d.unmapped} unmapped</span>
                </div>
              </div>
            ))}
          </div>

          <div className="card pad">
            {detail.isLoading && (
              <div className="muted" style={{ fontSize: 12 }}>
                Loading scope items…
              </div>
            )}
            {detail.data && (
              <>
                <div className="between" style={{ marginBottom: 4 }}>
                  <div className="h2">{detail.data.title}</div>
                  <span className="chip teal">
                    <Icon n="shield" s={11} /> DLP passed
                  </span>
                </div>
                <div className="muted" style={{ fontSize: 11.5, marginBottom: 14 }}>
                  {detail.data.account_key} · signed {detail.data.signed_date ?? '—'} · every match
                  re-checks G1/G3/G5/G7 and carries its chain.
                </div>
                <div style={{ display: 'grid', gap: 8 }}>
                  {detail.data.items.map((it) => (
                    <MatchRow key={it.scope_id} item={it} onConfirm={onConfirm} />
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </Page>
  );
}
