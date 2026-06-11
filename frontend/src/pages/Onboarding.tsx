// First-run setup (J1) — the REAL automap pipeline, all four steps honoured:
//   1 Upload workbooks   -> POST /api/admin/catalogue/upload/{v} parses FAST and PERSISTS the load
//                           (catalogue_version row 'uploaded' + a full ingest_run audit record)
//   2 Detect schema      -> review what the automap detected: per-workbook sheet, column->field
//                           mapping, unmapped headers, per-book counts, ID-governance results
//   3 Confirm mapping    -> the human gate: nothing is provisioned until YOU apply
//   4 Carry forward      -> map the canonical 14,406-row Jira corpus onto the new version
// Nothing auto-advances past a review step; every state is honest (parse errors, conflicts).
import { useRef, useState } from 'react';

import type { UploadManifest } from '../api/client';
import { api } from '../api/client';
import { useMe, useVersions } from '../api/queries';
import { go, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const STEPS = ['Upload workbooks', 'Detect schema', 'Confirm mapping', 'Carry forward stories'];

export function Onboarding() {
  const me = useMe();
  const ui = useUi();
  const versions = useVersions();
  const [step, setStep] = useState(0); // 0..3 = STEPS; 4 = done
  const [target, setTarget] = useState('v7');
  const [busy, setBusy] = useState<string | null>(null); // the in-flight action label
  const [manifest, setManifest] = useState<UploadManifest | null>(null);
  const [report, setReport] = useState<Record<string, number | string> | null>(null);
  const [carry, setCarry] = useState<Record<string, number | string> | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const isAdmin = me.data?.is_admin ?? false;

  const onUpload = async (f: File | null) => {
    if (!f) return;
    setBusy('Parsing workbooks…');
    try {
      const out = await api.uploadCatalogue(target, f);
      setManifest(out);
      setStep(1); // -> Detect schema review (never auto-provisions)
      toast(`Parsed ${out.subcaps_parsed} subcaps from ${out.workbooks.length} workbook(s)`);
    } catch (e) {
      toast('Upload failed: ' + String((e as Error)?.message ?? e).slice(0, 90));
    } finally {
      setBusy(null);
    }
  };

  const provision = async () => {
    setBusy('Provisioning cat_' + target + ' — creating schema + seeding subcaps…');
    try {
      const r = await api.provisionVersion(target);
      setReport(r);
      setStep(3);
      toast(`Provisioned ${target} · ${r.subcaps ?? ''} subcaps`);
      await versions.refetch();
      ui.setVersion(target);
    } catch (e) {
      toast('Provision failed: ' + String((e as Error)?.message ?? e).slice(0, 80));
    } finally {
      setBusy(null);
    }
  };

  const carryForward = async () => {
    setBusy('Carrying the 14,406-row corpus onto ' + target + '…');
    try {
      const r = await api.carryForward(target);
      setCarry(r);
      setStep(4);
      toast('Carry-forward complete — stories committed to the database');
    } catch (e) {
      toast('Carry-forward failed: ' + String((e as Error)?.message ?? e).slice(0, 80));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ minHeight: '100%', display: 'flex', flexDirection: 'column', background: 'var(--surface-sunken)' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '14px 28px',
          background: 'var(--surface-base)',
          borderBottom: '1px solid var(--border-subtle)',
        }}
      >
        <img src="/brand/logo-mark-teal.png" style={{ width: 24, height: 24 }} alt="Zennify" />
        <b style={{ fontSize: 14 }}>First-time setup</b>
        <span className="chip teal">
          <Icon n="shield" s={12} />
          Admin
        </span>
        <span className="grow" />
        <button className="linkbtn" onClick={() => go('mission-control')}>
          Skip to mission control <Icon n="arrowR" s={13} />
        </button>
      </div>

      {/* stepper */}
      <div style={{ display: 'flex', padding: '0 28px', background: 'var(--surface-base)', borderBottom: '1px solid var(--border-subtle)' }}>
        {STEPS.map((s, i) => {
          const state = i < step ? 'done' : i === step ? 'on' : 'todo';
          return (
            <div key={s} className="row gap8" style={{ flex: 1, padding: '14px 0', alignItems: 'center' }}>
              <div
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: '50%',
                  flex: 'none',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 11,
                  fontWeight: 700,
                  background: state === 'todo' ? 'var(--surface-raised)' : 'var(--surface-overlay)',
                  color: state === 'todo' ? 'var(--text-disabled)' : 'var(--interactive)',
                  border: state === 'on' ? '1.5px solid var(--interactive)' : '1.5px solid transparent',
                }}
              >
                {state === 'done' ? <Icon n="check" s={12} /> : i + 1}
              </div>
              <span style={{ fontSize: 12.5, fontWeight: state === 'on' ? 700 : 500, color: state === 'todo' ? 'var(--text-tertiary)' : 'var(--text-primary)' }}>
                {s}
              </span>
              {i < STEPS.length - 1 && <span className="grow" style={{ borderTop: '1px solid var(--border-subtle)' }} />}
            </div>
          );
        })}
      </div>

      <div className="content narrow fade-in" style={{ flex: 1 }}>
        {!isAdmin && (
          <div className="banner warn" style={{ marginBottom: 16 }}>
            <Icon n="alert" s={14} />
            Catalogue setup is admin-only. Ask an admin to provision the first version, or skip to
            mission control.
          </div>
        )}
        {busy && (
          <div className="banner info" style={{ marginBottom: 16 }}>
            <Icon n="refresh" s={14} cls="spin" /> {busy}
          </div>
        )}

        {/* ------------------------------------------------ 1 · Upload */}
        {step === 0 && (
          <>
            <div className="h1" style={{ marginBottom: 8 }}>
              Upload the pillar workbooks
            </div>
            <div className="muted" style={{ fontSize: 13, marginBottom: 20, maxWidth: 640, lineHeight: 1.5 }}>
              A .zip of the four pillar .xlsx files (or a single .xlsx). The parse is committed to
              the database immediately — the version is registered as <i>uploaded</i> and the full
              detection result is recorded as an ingest run — then you review the detected schema
              before anything is provisioned.
            </div>
            <div
              className="card"
              style={{ border: '1.5px dashed var(--border-medium)', padding: 36, textAlign: 'center', marginBottom: 18 }}
            >
              <div
                style={{
                  width: 54,
                  height: 54,
                  borderRadius: 14,
                  background: 'var(--surface-overlay)',
                  color: 'var(--interactive)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  margin: '0 auto 14px',
                }}
              >
                <Icon n="upload" s={26} />
              </div>
              <div className="row gap8" style={{ justifyContent: 'center', marginBottom: 14 }}>
                <span className="muted" style={{ fontSize: 12 }}>
                  Target version
                </span>
                <input
                  className="mono"
                  value={target}
                  disabled={!isAdmin || !!busy}
                  onChange={(e) => setTarget(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
                  style={{
                    width: 72,
                    padding: '4px 8px',
                    fontSize: 12,
                    background: 'var(--surface-raised)',
                    border: '1px solid var(--border-medium)',
                    borderRadius: 6,
                    color: 'var(--text-primary)',
                  }}
                  aria-label="Target catalogue version"
                />
                <span className="muted" style={{ fontSize: 11 }}>
                  e.g. v5, v7, v8 — newest becomes the default
                </span>
              </div>
              <input
                ref={fileRef}
                type="file"
                accept=".zip,.xlsx"
                style={{ display: 'none' }}
                onChange={(e) => void onUpload(e.target.files?.[0] ?? null)}
              />
              <button
                className="btn primary"
                disabled={!isAdmin || !!busy}
                onClick={() => fileRef.current?.click()}
              >
                <Icon n="upload" s={16} /> {busy ?? 'Choose workbooks (.zip / .xlsx)'}
              </button>
              <div className="muted" style={{ fontSize: 11, marginTop: 12 }}>
                Already shipped as committed seeds: v5 · v7 —{' '}
                <button className="linkbtn" disabled={!isAdmin || !!busy} onClick={() => setStep(2)}>
                  provision from a committed seed instead
                </button>
              </div>
            </div>
          </>
        )}

        {/* ------------------------------------------------ 2 · Detect schema (review) */}
        {step === 1 && manifest && (
          <>
            <div className="h1" style={{ marginBottom: 8 }}>
              Detected schema — review before anything is applied
            </div>
            <div className="muted" style={{ fontSize: 13, marginBottom: 16, maxWidth: 640, lineHeight: 1.5 }}>
              {manifest.workbooks.length} workbook(s) · pillars {manifest.pillars_recognised.join(', ') || '—'} ·{' '}
              <b>{manifest.subcaps_parsed} subcaps parsed</b>
              {manifest.synthetic_stories_found > 0 && (
                <> · {manifest.synthetic_stories_found} embedded synthetic stories (labelled, never analysis)</>
              )}
              {manifest.skipped_rows > 0 && <> · {manifest.skipped_rows} unparseable rows skipped</>}
              {manifest.duplicate_rows > 0 && <> · {manifest.duplicate_rows} exact duplicates dropped</>}
            </div>

            <div style={{ display: 'grid', gap: 10, marginBottom: 14 }}>
              {manifest.workbooks_detail.map((d) => (
                <div key={d.file} className="card pad">
                  <div className="between" style={{ marginBottom: 8, flexWrap: 'wrap', gap: 6 }}>
                    <div className="row gap8">
                      <Icon n="file" s={14} style={{ color: 'var(--interactive)' }} />
                      <b style={{ fontSize: 13 }}>{d.file}</b>
                    </div>
                    <span className="muted" style={{ fontSize: 11 }}>
                      sheet <span className="mono">{d.sheet}</span> · {d.subcaps_parsed} subcaps
                    </span>
                  </div>
                  <div className="row wrap gap6">
                    {d.columns.map((c) => (
                      <span key={c.source} className="chip soft" style={{ fontSize: 10.5 }}>
                        <span className="mono">{c.source}</span>
                        <Icon n="arrowR" s={10} />
                        <b>{c.field}</b>
                      </span>
                    ))}
                  </div>
                  {d.unmapped_headers.length > 0 && (
                    <div className="muted" style={{ fontSize: 10.5, marginTop: 8 }}>
                      <Icon n="alert" s={11} /> not mapped (kept out, never guessed):{' '}
                      {d.unmapped_headers.join(' · ')}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {manifest.id_reconciliations.length > 0 && (
              <div className="banner info" style={{ marginBottom: 10 }}>
                <Icon n="branch" s={14} />
                ID governance: {manifest.id_reconciliations.length} colliding id(s) reconciled
                against the governing register (ids are never reused or recycled) —{' '}
                {manifest.id_reconciliations
                  .slice(0, 3)
                  .map((r) => `${r.source_id} → ${r.assigned_id} (“${r.name}”)`)
                  .join('; ')}
                {manifest.id_reconciliations.length > 3 ? ' …' : ''}
              </div>
            )}
            {manifest.id_conflicts.length > 0 && (
              <div className="banner warn" style={{ marginBottom: 10 }}>
                <Icon n="alert" s={14} />
                {manifest.id_conflicts.length} id conflict(s) need a human decision (kept out of
                the seed):{' '}
                {manifest.id_conflicts
                  .slice(0, 3)
                  .map((c) => `${c.source_id} “${c.name}” in ${c.file}`)
                  .join('; ')}
                {manifest.id_conflicts.length > 3 ? ' …' : ''}
              </div>
            )}

            <div className="row gap8" style={{ marginTop: 8 }}>
              <button className="btn ghost" disabled={!!busy} onClick={() => setStep(0)}>
                <Icon n="chevL" s={14} /> Back
              </button>
              <button className="btn primary" disabled={!!busy} onClick={() => setStep(2)}>
                Looks right — confirm mapping <Icon n="arrowR" s={14} />
              </button>
            </div>
          </>
        )}

        {/* ------------------------------------------------ 3 · Confirm mapping (human gate) */}
        {step === 2 && (
          <>
            <div className="h1" style={{ marginBottom: 8 }}>
              Confirm &amp; provision {target}
            </div>
            <div className="muted" style={{ fontSize: 13, marginBottom: 16, maxWidth: 640, lineHeight: 1.5 }}>
              {manifest ? (
                <>
                  Applying commits <b>{manifest.subcaps_parsed} subcaps</b> into a new versioned
                  schema <span className="mono">cat_{target}</span> — transactionally (a half-apply
                  is impossible), registered in the version timeline, persisted for every user.
                </>
              ) : (
                <>
                  Provision <span className="mono">{target}</span> from its committed seed into a
                  new versioned schema <span className="mono">cat_{target}</span> — transactional,
                  persisted for every user. (Upload workbooks instead to review a fresh parse.)
                </>
              )}
            </div>
            {report ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginBottom: 16 }}>
                {Object.entries(report)
                  .filter(([, v]) => typeof v === 'number')
                  .slice(0, 6)
                  .map(([k, v]) => (
                    <div key={k} className="card pad" style={{ textAlign: 'center' }}>
                      <div className="num" style={{ fontSize: 22, fontWeight: 700, color: 'var(--interactive)' }}>
                        {v}
                      </div>
                      <div className="muted" style={{ fontSize: 10.5 }}>
                        {k.replace(/_/g, ' ')}
                      </div>
                    </div>
                  ))}
              </div>
            ) : null}
            <div className="row gap8">
              <button className="btn ghost" disabled={!!busy} onClick={() => setStep(manifest ? 1 : 0)}>
                <Icon n="chevL" s={14} /> Back
              </button>
              <button className="btn primary" disabled={!isAdmin || !!busy} onClick={() => void provision()}>
                {busy ? (
                  <>
                    <Icon n="refresh" s={16} cls="spin" /> Provisioning…
                  </>
                ) : (
                  <>Apply &amp; provision {target}</>
                )}
              </button>
            </div>
          </>
        )}

        {/* ------------------------------------------------ 4 · Carry forward */}
        {step === 3 && (
          <>
            <div className="h1" style={{ marginBottom: 8 }}>
              Carry forward the story corpus
            </div>
            <div className="muted" style={{ fontSize: 13, marginBottom: 20, maxWidth: 640, lineHeight: 1.5 }}>
              The canonical 14,406-row Jira corpus is committed into the database and mapped onto{' '}
              {target}: native links where the subcap id is unchanged, the version crosswalk next,
              then a banded nearest-neighbour fallback — each gated to confirmed / review /
              unmapped, never dropped. Synthetic workbook stories ingest alongside, labelled.
            </div>
            <button className="btn primary" disabled={!isAdmin || !!busy} onClick={() => void carryForward()}>
              {busy ? (
                <>
                  <Icon n="refresh" s={16} cls="spin" /> Carrying forward…
                </>
              ) : (
                <>
                  <Icon n="branch" s={16} /> Run carry-forward
                </>
              )}
            </button>
          </>
        )}

        {/* ------------------------------------------------ done */}
        {step === 4 && (
          <div style={{ textAlign: 'center', padding: '40px 0', maxWidth: 480, margin: '0 auto' }}>
            <div
              style={{
                width: 56,
                height: 56,
                borderRadius: 14,
                background: 'var(--surface-overlay)',
                color: 'var(--interactive)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 14px',
              }}
            >
              <Icon n="check" s={28} />
            </div>
            <div className="h1" style={{ marginBottom: 8 }}>
              {target} is live
            </div>
            <div className="muted" style={{ fontSize: 13, marginBottom: 8, lineHeight: 1.5 }}>
              {carry
                ? Object.entries(carry)
                    .filter(([, v]) => typeof v === 'number')
                    .map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`)
                    .join(' · ')
                : 'The catalogue is provisioned and the corpus is mapped.'}
            </div>
            <button className="btn primary" style={{ marginTop: 12 }} onClick={() => go('mission-control')}>
              Go to mission control <Icon n="arrowR" s={14} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
