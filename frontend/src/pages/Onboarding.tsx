// First-run setup (J1) — the prototype's 4-step onboarding, wired to the REAL admin pipeline.
// Upload (mock dropzone, since a real workbook upload UI is a later increment) → Provision the
// version (POST /api/admin/provision/{v}, bring_version_online) → Carry forward the canonical
// story corpus (POST /api/admin/carry-forward/{v}). Admin-only, always skippable. The first
// successful provision persists for every user (no re-upload), exactly as the copy promises.
import { useRef, useState } from 'react';

import { api } from '../api/client';
import { useMe, useVersions } from '../api/queries';
import { go, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const PILLARS: [string, string, string][] = [
  ['P1', 'Strategy, governance & culture', '205'],
  ['P2', 'Customer experience & engagement', '292'],
  ['P3', 'Process automation & operations', '164'],
  ['P4', 'Data & AI enablement', '190'],
];
const STEPS = ['Upload workbooks', 'Detect schema', 'Confirm mapping', 'Carry forward stories'];

export function Onboarding() {
  const me = useMe();
  const ui = useUi();
  const versions = useVersions();
  const [step, setStep] = useState(0);
  const [target] = useState('v7');
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<Record<string, number | string> | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploaded, setUploaded] = useState<Awaited<
    ReturnType<typeof api.uploadCatalogue>
  > | null>(null);

  const onUpload = async (f: File | null) => {
    if (!f) return;
    setBusy(true);
    try {
      const out = await api.uploadCatalogue(target, f);
      setUploaded(out);
      toast(`Received ${out.workbooks.length} workbook(s) — pillars ${out.pillars_recognised.join(', ') || '—'}`);
    } catch (e) {
      toast('Upload failed: ' + String((e as Error)?.message ?? e).slice(0, 90));
    } finally {
      setBusy(false);
    }
  };
  const [carry, setCarry] = useState<Record<string, number | string> | null>(null);
  const isAdmin = me.data?.is_admin ?? false;

  const provision = async () => {
    setBusy(true);
    try {
      const r = await api.provisionVersion(target);
      setReport(r);
      setStep(2);
      toast(`Provisioned ${target} · ${r.subcaps ?? ''} subcaps`);
      await versions.refetch();
      ui.setVersion(target);
    } catch (e) {
      toast('Provision failed: ' + String((e as Error)?.message ?? e).slice(0, 80));
    } finally {
      setBusy(false);
    }
  };

  const carryForward = async () => {
    setBusy(true);
    try {
      const r = await api.carryForward(target);
      setCarry(r);
      setStep(4);
      toast('Carry-forward complete');
    } catch (e) {
      toast('Carry-forward failed: ' + String((e as Error)?.message ?? e).slice(0, 80));
    } finally {
      setBusy(false);
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

        {step <= 1 && (
          <>
            <div className="h1" style={{ marginBottom: 8 }}>
              Upload the four pillar workbooks
            </div>
            <div className="muted" style={{ fontSize: 13, marginBottom: 20, maxWidth: 620, lineHeight: 1.5 }}>
              The v7 pillar workbooks ship with the catalogue seed. Provisioning brings the version
              online from that seed and writes its own <span className="mono">cat_{target}</span>{' '}
              schema. The first successful ingest persists for every user — no re-upload.
            </div>
            <div
              className="card"
              style={{ border: '1.5px dashed var(--border-medium)', padding: 40, textAlign: 'center', marginBottom: 18 }}
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
              <div className="h3" style={{ marginBottom: 4 }}>
                Provision {target} from the catalogue seed
              </div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 16 }}>
                P1 Strategy · P2 Experience · P3 Operations · P4 Data &amp; AI · .xlsx
              </div>
              <input
                ref={fileRef}
                type="file"
                accept=".zip,.xlsx"
                style={{ display: 'none' }}
                onChange={(e) => void onUpload(e.target.files?.[0] ?? null)}
              />
              <div className="row gap8" style={{ justifyContent: 'center' }}>
                <button
                  className="btn ghost"
                  disabled={!isAdmin || busy}
                  onClick={() => fileRef.current?.click()}
                >
                  <Icon n="upload" s={16} /> Upload workbooks (.zip / .xlsx)
                </button>
                <button
                  className="btn primary"
                  disabled={!isAdmin || busy}
                  onClick={() => void provision()}
                >
                  {busy ? (
                    <>
                      <Icon n="refresh" s={16} cls="spin" /> Provisioning…
                    </>
                  ) : (
                    <>Provision {target}</>
                  )}
                </button>
              </div>
              {uploaded && (
                <div className="banner info" style={{ marginTop: 14, textAlign: 'left' }}>
                  <Icon n="check" s={14} />
                  {uploaded.workbooks.length} workbook(s) received
                  {uploaded.pillars_recognised.length
                    ? ` — pillars ${uploaded.pillars_recognised.join(', ')}`
                    : ''}{' '}
                  · recorded in the source registry. {uploaded.note}
                </div>
              )}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12 }}>
              {PILLARS.map(([p, name, n]) => (
                <div key={p} className="card pad" style={{ padding: '12px 14px' }}>
                  <div className="mono" style={{ fontSize: 11, color: 'var(--z-slate)', fontWeight: 700 }}>
                    {p}
                  </div>
                  <div style={{ fontSize: 12, marginTop: 4, lineHeight: 1.3 }}>{name}</div>
                  <div className="muted" style={{ fontSize: 10.5, marginTop: 6 }}>
                    {n} subcaps
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {step === 2 && report && (
          <>
            <div className="h1" style={{ marginBottom: 8 }}>
              Schema mapped · {target} is online
            </div>
            <div className="muted" style={{ fontSize: 13, marginBottom: 20 }}>
              The version provisioned transactionally and its catalogue schema is live. Review the
              counts, then carry the canonical story corpus onto it.
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginBottom: 20 }}>
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
            <button className="btn primary" disabled={busy} onClick={() => setStep(3)}>
              Continue to carry-forward <Icon n="arrowR" s={14} />
            </button>
          </>
        )}

        {step === 3 && (
          <>
            <div className="h1" style={{ marginBottom: 8 }}>
              Carry forward the story corpus
            </div>
            <div className="muted" style={{ fontSize: 13, marginBottom: 20, maxWidth: 620, lineHeight: 1.5 }}>
              The canonical 14,406-row delivery corpus is mapped onto {target}: native links where
              the subcap id is unchanged, the version crosswalk next, and an embedding
              nearest-neighbour fallback — each gated to confirmed / review / unmapped.
            </div>
            <button className="btn primary" disabled={!isAdmin || busy} onClick={() => void carryForward()}>
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
