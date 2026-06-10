// Quarterly digest (E1) — the strategic synthesis over the quarter's GATED substrate. Quarter
// selector, the executive summary (claim label + reasoning backlink — the digest is an AI value
// and carries its envelope), the cross-pillar theme, collapsible pillar priority cards each with
// its ADVERSARIAL line (corroborated signal survives, thin signal is caveated — never hidden),
// and the signed export (F12): HMAC over the canonical JSON, verification state shown; a digest
// regenerated after signing invalidates the old signature — tamper-evident.
import { useState } from 'react';

import { useDigest, useDigestActions } from '../api/queries';
import { Claim, Dropdown, Empty, Page, PillarDot } from '../components/primitives';
import { openReasoning, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

function fmtTs(s: string | null): string {
  if (!s) return '—';
  const d = new Date(s.replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return s.slice(0, 16);
  return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

export function Digest() {
  const isAdmin = useUi((s) => s.adminView);
  const [quarter, setQuarter] = useState('latest');
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const q = useDigest(quarter);
  const { generate, exportIt } = useDigestActions();
  const d = q.data;

  const quarters = d?.quarters ?? [];
  const options = [
    { v: 'latest', l: 'Latest' },
    ...quarters.map((x) => ({ v: x, l: x })),
  ];

  return (
    <Page
      eyebrow="E · Strategic synthesis"
      title="Quarterly digest"
      width="narrow"
      intro="The quarter's strategic read-out, synthesized only from gated evidence — news impacts, earned trends, adversarially-reviewed benchmarks and typed vendor developments. Exports are HMAC-signed and verifiable; regeneration invalidates earlier signatures."
      actions={
        <div className="row gap8">
          <Dropdown value={quarter} icon="filter" options={options} onChange={setQuarter} />
          {isAdmin ? (
            <button
              className="btn ghost sm"
              disabled={generate.isPending}
              onClick={() =>
                generate.mutate(quarter === 'latest' ? undefined : quarter, {
                  onSuccess: (r) =>
                    toast(
                      r.generated
                        ? `Digest generated for ${r.quarter}`
                        : (r.reason ?? 'Not generated'),
                    ),
                })
              }
            >
              <Icon n="refresh" s={14} /> Generate
            </button>
          ) : null}
        </div>
      }
    >
      {d?.cadence && (
        <div className="row gap8" style={{ marginBottom: 16 }}>
          <Icon n="clock" s={13} style={{ color: 'var(--text-tertiary)' }} />
          <span className="muted" style={{ fontSize: 11.5 }}>
            Quarterly synthesis · next {fmtTs(d.cadence.next_run)}{' '}
            <span className="mono">({d.cadence.cron} UTC)</span> — composed from the stored gated
            substrate, never from model memory.
          </span>
        </div>
      )}

      {d?.generated ? (
        <>
          <div className="card pad fade-in" style={{ marginBottom: 14 }}>
            <div className="row gap8" style={{ marginBottom: 10, flexWrap: 'wrap' }}>
              <span className="chip teal">{d.quarter}</span>
              <Claim label={d.claim_label} />
              <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
                generated {fmtTs(d.created_at)}
              </span>
            </div>
            <div className="eyebrow" style={{ marginBottom: 6 }}>
              Executive summary
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 10 }}>{d.summary}</div>
            <div
              className="card"
              style={{ padding: '9px 12px', background: 'var(--surface-raised)', marginBottom: 10 }}
            >
              <div className="row gap8">
                <Icon n="trend" s={13} style={{ color: 'var(--interactive)', flex: 'none' }} />
                <span style={{ fontSize: 12 }}>{d.theme}</span>
              </div>
            </div>
            <div className="between">
              {d.chain ? (
                <button className="linkbtn" onClick={() => d.chain && openReasoning(d.chain)}>
                  <Icon n="eye" s={13} /> Reasoning
                </button>
              ) : (
                <span />
              )}
              <div className="row gap8">
                {d.export && (
                  <span
                    className={'chip ' + (d.export.valid ? 'teal' : 'orange')}
                    title={'signed ' + fmtTs(d.export.signed_at)}
                  >
                    <Icon n="shield" s={11} /> {d.export.valid ? 'export verified' : 'export stale'}
                  </span>
                )}
                <button
                  className="btn primary xs"
                  disabled={exportIt.isPending}
                  onClick={() =>
                    exportIt.mutate(quarter === 'latest' ? undefined : quarter, {
                      onSuccess: (r) =>
                        toast(
                          r.exported
                            ? `Signed export ${r.export_id?.slice(0, 8)}… · HMAC ${r.hmac_sig?.slice(0, 12)}…`
                            : (r.reason ?? 'Export failed'),
                        ),
                    })
                  }
                >
                  <Icon n="ext" s={13} /> Export signed
                </button>
              </div>
            </div>
          </div>

          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Pillar priorities
          </div>
          <div style={{ display: 'grid', gap: 10 }}>
            {d.priorities.map((p) => (
              <div key={p.pillar} className="card pad fade-in">
                <div
                  className="row gap8"
                  style={{ cursor: 'pointer' }}
                  onClick={() => setOpen((o) => ({ ...o, [p.pillar]: !o[p.pillar] }))}
                >
                  <PillarDot p={p.pillar} s={9} />
                  <b style={{ fontSize: 13 }}>{p.title}</b>
                  <Icon
                    n={open[p.pillar] ? 'chevD' : 'chevR'}
                    s={13}
                    style={{ marginLeft: 'auto', color: 'var(--text-tertiary)' }}
                  />
                </div>
                {open[p.pillar] !== false && (
                  <>
                    <div className="muted" style={{ fontSize: 12, lineHeight: 1.6, marginTop: 9 }}>
                      {p.body}
                    </div>
                    <div
                      className="row gap8"
                      style={{
                        marginTop: 9,
                        paddingTop: 9,
                        borderTop: '1px solid var(--border-subtle)',
                      }}
                    >
                      <Icon
                        n="shield"
                        s={13}
                        style={{
                          color: p.adversary_verdict.startsWith('Survives')
                            ? 'var(--z-teal)'
                            : 'var(--z-orange)',
                          flex: 'none',
                          marginTop: 1,
                        }}
                      />
                      <span className="muted" style={{ fontSize: 11.5, fontStyle: 'italic' }}>
                        {p.adversary_verdict}
                      </span>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        </>
      ) : (
        <Empty
          icon="brief"
          title="No digest for this quarter yet"
          desc="The quarterly job synthesizes the digest from the quarter's gated evidence. An admin can generate it now — an empty quarter is refused honestly, never padded."
          cta={isAdmin ? 'Generate now' : undefined}
          onCta={
            isAdmin
              ? () =>
                  generate.mutate(quarter === 'latest' ? undefined : quarter, {
                    onSuccess: (r) =>
                      toast(
                        r.generated
                          ? `Digest generated for ${r.quarter}`
                          : (r.reason ?? 'Not generated'),
                      ),
                  })
              : undefined
          }
        />
      )}
    </Page>
  );
}
