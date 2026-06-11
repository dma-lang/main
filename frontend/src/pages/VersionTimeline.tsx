// Version timeline (G1) — every catalogue snapshot, inspectable and reversible. Ported from the
// prototype, wired to GET /api/versions (the snapshots) + /api/catalogue/{v}/summary (per-pillar
// counts). Re-ingesting a newer version creates a new versioned schema rather than overwriting
// history (PRD D10). Revert is admin-gated; Diff opens the diff viewer.
import type { VersionInfo } from '../api/client';
import { useProvisionActions, useSummary, useVersions } from '../api/queries';
import { Page, PillarDot } from '../components/primitives';
import { go, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

function fmtWhen(s: string | null): string {
  if (!s) return 'unknown date';
  // Postgres timestamptz text ("2026-06-09 14:41:18.7+00") -> ISO ("...T...+00:00").
  const iso = s.replace(' ', 'T').replace(/([+-]\d{2})$/, '$1:00');
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return s.slice(0, 10);
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function VersionCard({ v, current }: { v: VersionInfo; current: boolean }) {
  const isAdmin = useUi((s) => s.adminView);
  const uploaded = v.status === 'uploaded'; // parsed + committed, awaiting Apply & provision
  const summary = useSummary(uploaded ? '' : v.version_id); // no cat_<v> schema to read yet
  const { provision } = useProvisionActions();
  const total = summary.data?.total_subcaps ?? 0;
  const pillars = summary.data?.pillars ?? [];

  return (
    <div
      className="card pad"
      style={{ borderColor: current ? 'var(--border-medium)' : 'var(--border-subtle)' }}
    >
      <div className="between" style={{ marginBottom: 8 }}>
        <div className="row gap8">
          <div
            style={{
              width: 30,
              height: 30,
              borderRadius: 8,
              background: current ? 'var(--surface-overlay)' : 'var(--surface-raised)',
              color: current ? 'var(--interactive)' : 'var(--text-tertiary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Icon n="clock" s={15} />
          </div>
          <div>
            <div className="row gap8">
              <b style={{ fontSize: 14 }}>{v.label}</b>
              {current && <span className="chip teal">current</span>}
            </div>
            <div className="muted" style={{ fontSize: 11 }}>
              {fmtWhen(v.created_at)} · {v.status}
            </div>
          </div>
        </div>
        <div className="row gap8">
          {uploaded ? (
            <button
              className="btn primary xs"
              disabled={!isAdmin || provision.isPending}
              title={isAdmin ? 'Parse is committed — provision brings it online' : 'Admin only'}
              onClick={() =>
                provision.mutate(v.version_id, {
                  onSuccess: () => toast(`${v.version_id} provisioned and live`),
                  onError: (e) => toast('Provision failed: ' + String(e).slice(0, 80)),
                })
              }
            >
              {provision.isPending ? (
                <Icon n="refresh" s={11} cls="spin" />
              ) : (
                <Icon n="upload" s={11} />
              )}
              Apply &amp; provision
            </button>
          ) : (
            <>
              <button className="btn ghost xs" onClick={() => go('diff')}>
                Diff
              </button>
              {!current && (
                <button
                  className="btn ghost xs"
                  disabled={!isAdmin}
                  title={isAdmin ? '' : 'Admin only'}
                  onClick={() => toast('Reverting to ' + v.version_id + ' — cascade preview…')}
                >
                  {!isAdmin && <Icon n="lock" s={11} />}
                  Revert
                </button>
              )}
            </>
          )}
        </div>
      </div>
      <div className="muted" style={{ fontSize: 12.5, marginBottom: 12, lineHeight: 1.5 }}>
        {uploaded ? (
          <>
            Workbooks parsed and committed (ingest run recorded) — awaiting{' '}
            <b>Apply &amp; provision</b> to build schema <span className="mono">{v.schema_name}</span>.
          </>
        ) : (
          <>
            {total} subcaps across {pillars.length || 4} pillars · schema{' '}
            <span className="mono">{v.schema_name}</span>.
          </>
        )}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8 }}>
        {pillars.map((p) => (
          <div key={p.pillar_id} className="card" style={{ padding: '8px 10px' }}>
            <div className="row gap6">
              <PillarDot p={p.pillar_id} s={7} />
              <span className="muted" style={{ fontSize: 10.5 }}>
                {p.pillar_id}
              </span>
            </div>
            <div className="num" style={{ fontSize: 17, fontWeight: 700 }}>
              {p.subcap_count}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function VersionTimeline() {
  const versions = useVersions();
  const active = useUi((s) => s.version);
  const isAdmin = useUi((s) => s.adminView);
  const rows = versions.data ?? [];

  return (
    <Page
      eyebrow="G · Versioning & QA"
      title="Version timeline"
      width="narrow"
      intro="Every catalogue snapshot, inspectable and reversible. Re-ingesting a newer version creates a new versioned database rather than overwriting history."
      actions={
        <button
          className="btn primary sm"
          disabled={!isAdmin}
          title={isAdmin ? 'Upload & provision a new catalogue version' : 'Admin only'}
          onClick={() => go('onboarding')}
        >
          {!isAdmin && <Icon n="lock" s={12} />}
          <Icon n="upload" s={14} /> Upload new version
        </button>
      }
    >
      {rows.length === 0 ? (
        <div className="card pad">
          <div className="muted" style={{ fontSize: 12.5, marginBottom: 12 }}>
            No catalogue version is provisioned yet. Upload the pillar-wise workbooks (a .zip of the
            four pillar .xlsx files, or a single .xlsx) — the app parses them, provisions a new{' '}
            <span className="mono">cat_&lt;version&gt;</span> schema, carries the story corpus
            forward, and commits it to the dashboard for every user.
          </div>
          <button className="btn primary" disabled={!isAdmin} onClick={() => go('onboarding')}>
            <Icon n="upload" s={15} /> Upload & provision a catalogue
          </button>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 12 }}>
          {rows.map((v) => {
            const fallback = rows[rows.length - 1]?.version_id;
            return (
              <VersionCard
                key={v.version_id}
                v={v}
                current={v.version_id === (active || fallback)}
              />
            );
          })}
        </div>
      )}
    </Page>
  );
}
