// Settings — per-user preferences for everyone (theme · default lens · persona, persisted to
// control.users.preferences) and, for admins, the INGESTION SOURCE REGISTRY: every source the
// pipelines pull from, with the ACTIVE origin (database fixture vs online, per LLM_MODE), tier,
// cadence, last poll and health — a stale or erroring source is warned, never hidden — plus the
// persisted enable switch the scan jobs enforce. Upload entry routes into onboarding (F4).
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { type SourceRow } from '../api/client';
import {
  useAdminActions,
  useAdmins,
  useMe,
  usePatchPreferences,
  useProvisionActions,
  useSourceActions,
  useSources,
  useVersions,
} from '../api/queries';
import { Dropdown, Page, Switch, Tier } from '../components/primitives';
import { signOutUser } from '../lib/auth';
import { toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

// First-run catalogue setup — one-click provisioning so a fresh deployment needs no CLI. Both
// actions are admin-only and idempotent; the version comes from the active version selector.
function CatalogueSetup() {
  const version = useUi((s) => s.version);
  const versions = useVersions();
  const { provision, carry } = useProvisionActions();
  const provisioned = (versions.data ?? []).some((v) => v.version_id === version);

  return (
    <>
      <div className="row gap8" style={{ marginBottom: 8 }}>
        <span className="eyebrow" style={{ margin: 0 }}>
          Catalogue setup
        </span>
        <span className="chip orange" style={{ fontSize: 9 }}>
          admin
        </span>
        <span className="muted" style={{ fontSize: 10.5, marginLeft: 'auto' }}>
          first-run, idempotent — re-running is safe
        </span>
      </div>
      <div className="card pad" style={{ marginBottom: 18 }}>
        <div className="row gap8" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
          <span
            className={'chip ' + (provisioned ? 'teal' : 'slate')}
            style={{ fontSize: 9.5 }}
          >
            {provisioned ? `${version} provisioned` : `${version} not provisioned`}
          </span>
          <span className="muted" style={{ fontSize: 11.5, flex: 1 }}>
            Seed the catalogue ({version}: ~851 subcaps + enrichment) then carry the canonical
            14,406-story delivery corpus onto it.
          </span>
          <button
            className="btn ghost sm"
            disabled={provision.isPending}
            onClick={() =>
              provision.mutate(version, {
                onSuccess: (r) =>
                  toast(`Provisioned ${version}: ${r.subcaps} subcaps, ${r.use_cases} use cases`),
                onError: (e) => toast(String(e).replace(/^Error:\s*\d+:\s*/, '')),
              })
            }
          >
            <Icon n="database" s={14} /> {provision.isPending ? 'Provisioning…' : '1 · Provision'}
          </button>
          <button
            className="btn primary sm"
            disabled={carry.isPending || !provisioned}
            onClick={() =>
              carry.mutate(version, {
                onSuccess: (r) =>
                  toast(
                    `Carried ${r.stories_ingested} stories · ${r.confirmed} confirmed · ${r.distinct_subcaps} subcaps`,
                  ),
                onError: (e) => toast(String(e).replace(/^Error:\s*\d+:\s*/, '')),
              })
            }
          >
            <Icon n="route" s={14} /> {carry.isPending ? 'Carrying…' : '2 · Carry stories'}
          </button>
        </div>
        <div className="muted" style={{ fontSize: 10.5, marginTop: 8 }}>
          After this, run each intelligence surface's “Scan now”, or let the weekly/monthly
          schedulers fill News, Trends, Benchmarks and Vendor automatically.
        </div>
      </div>
    </>
  );
}

function Administrators() {
  const admins = useAdmins(true);
  const { grant, revoke } = useAdminActions();
  const [email, setEmail] = useState('');
  const rows = admins.data ?? [];

  const add = () => {
    const e = email.trim().toLowerCase();
    if (!e) return;
    grant.mutate(
      { email: e },
      {
        onSuccess: (r) => {
          toast(r.status === 'granted' ? `${e} is now an admin` : `${e} (${r.status})`);
          setEmail('');
        },
        onError: (err) => toast(String(err).replace(/^Error:\s*\d+:\s*/, '')),
      },
    );
  };

  return (
    <>
      <div className="row gap8" style={{ marginBottom: 8 }}>
        <span className="eyebrow" style={{ margin: 0 }}>
          Administrators
        </span>
        <span className="chip orange" style={{ fontSize: 9 }}>
          admin
        </span>
        <span className="muted" style={{ fontSize: 10.5, marginLeft: 'auto' }}>
          grants persist and take effect on the member's next request — no redeploy
        </span>
      </div>
      <div className="card pad" style={{ marginBottom: 18 }}>
        <div className="row gap8" style={{ marginBottom: 12 }}>
          <input
            className="input"
            style={{ flex: 1, fontSize: 12.5, padding: '7px 10px' }}
            placeholder="name@zennify.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && add()}
          />
          <button className="btn primary sm" disabled={grant.isPending} onClick={add}>
            <Icon n="plus" s={13} /> Add admin
          </button>
        </div>
        <div style={{ display: 'grid', gap: 6 }}>
          {rows.map((a) => (
            <div
              key={a.email}
              className="row gap8 card"
              style={{ padding: '7px 11px', alignItems: 'center' }}
            >
              <Icon n="lock" s={12} style={{ color: 'var(--interactive)' }} />
              <b style={{ fontSize: 12 }}>{a.email}</b>
              <span
                className={'chip ' + (a.source === 'bootstrap' ? 'slate' : 'blue')}
                style={{ fontSize: 9 }}
              >
                {a.source === 'bootstrap' ? 'env bootstrap' : 'granted'}
              </span>
              {a.note ? (
                <span className="muted" style={{ fontSize: 10.5 }}>
                  {a.note}
                </span>
              ) : null}
              <span style={{ marginLeft: 'auto' }}>
                {a.removable ? (
                  <button
                    className="btn ghost xs"
                    disabled={revoke.isPending}
                    onClick={() =>
                      revoke.mutate(a.email, { onSuccess: () => toast(`${a.email} revoked`) })
                    }
                  >
                    <Icon n="x" s={12} /> Revoke
                  </button>
                ) : (
                  <span className="muted" style={{ fontSize: 10 }}>
                    config — not removable here
                  </span>
                )}
              </span>
            </div>
          ))}
          {!rows.length && (
            <div className="muted" style={{ fontSize: 11.5 }}>
              No administrators resolved — set ADMIN_EMAILS to bootstrap the first one.
            </div>
          )}
        </div>
      </div>
    </>
  );
}

const LENSES = [
  { v: 'pillar', l: 'Pillar' },
  { v: 'value-chain', l: 'Value chain' },
  { v: 'subvertical', l: 'Subvertical' },
  { v: 'maturity', l: 'Maturity' },
  { v: 'vendor', l: 'Vendor' },
  { v: 'lifecycle', l: 'Lifecycle' },
];
const PERSONAS = [
  { v: 'Pillar lead', l: 'Pillar lead' },
  { v: 'Account executive', l: 'Account executive' },
  { v: 'Delivery lead', l: 'Delivery lead' },
  { v: 'Solution architect', l: 'Solution architect' },
];

const STATUS_STYLE: Record<string, { color: string; label: string }> = {
  ok: { color: 'var(--z-teal)', label: 'Healthy' },
  stale: { color: 'var(--z-orange)', label: 'Stale' },
  never_run: { color: 'var(--text-tertiary)', label: 'Never run' },
  disabled: { color: 'var(--text-tertiary)', label: 'Disabled' },
};

function fmtTs(s: string | null): string {
  if (!s) return '—';
  const d = new Date(s.replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return s.slice(0, 16);
  return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

function SourceRowView({ s }: { s: SourceRow }) {
  const { toggle } = useSourceActions();
  const st = STATUS_STYLE[s.status] ?? STATUS_STYLE.ok;
  return (
    <div
      className="card"
      style={{ padding: '11px 14px', opacity: s.enabled ? 1 : 0.62 }}
    >
      <div className="row gap8" style={{ flexWrap: 'wrap' }}>
        <b style={{ fontSize: 12.5 }}>{s.name}</b>
        <span className="chip soft" style={{ fontSize: 9.5 }}>
          {s.type}
        </span>
        <Tier t={s.tier} />
        <span className="chip slate" style={{ fontSize: 9.5 }}>
          {s.cadence}
          {s.cron ? ` · ${s.cron}` : ''}
        </span>
        <span className="row gap6" style={{ marginLeft: 'auto', alignItems: 'center' }}>
          <span
            className="pilldot"
            style={{ width: 7, height: 7, borderRadius: '50%', background: st.color }}
          />
          <span style={{ fontSize: 11, color: st.color, fontWeight: 600 }}>{st.label}</span>
          <span className="muted" style={{ fontSize: 10.5 }}>
            · last poll {fmtTs(s.last_run)}
          </span>
          <Switch
            on={s.enabled}
            onChange={() =>
              toggle.mutate(
                { key: s.key, enabled: !s.enabled },
                {
                  onSuccess: (r) =>
                    toast(
                      r.enabled
                        ? `${s.name} enabled — the scheduled scan will run`
                        : `${s.name} disabled — scans refuse until re-enabled`,
                    ),
                },
              )
            }
          />
        </span>
      </div>
      <div className="row gap8" style={{ marginTop: 7, flexWrap: 'wrap' }}>
        <span className={'chip ' + (s.mode === 'recorded' ? 'blue' : 'teal')} style={{ fontSize: 9.5 }}>
          {s.mode === 'recorded' ? 'database · recorded' : 'online · live'}
        </span>
        <span
          className="mono muted"
          style={{
            fontSize: 10.5,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            maxWidth: 560,
          }}
          title={s.origin_active}
        >
          {s.origin_active}
        </span>
      </div>
      {s.notes && (
        <div className="muted" style={{ fontSize: 10.5, marginTop: 5 }}>
          {s.notes}
        </div>
      )}
    </div>
  );
}

export function Settings() {
  const ui = useUi();
  const isAdmin = useUi((s) => s.adminView);
  const patch = usePatchPreferences();
  const sources = useSources(isAdmin);
  const me = useMe();
  const qc = useQueryClient();
  const persist = (extra: Record<string, unknown>) =>
    patch.mutate({ theme: ui.theme, lens: ui.lens, persona: ui.persona, ...extra });
  // Sign out = drop the Google ID token AND every cached query (identity included) — the gate
  // sees the empty ['me'] cache, its refetch 401s (fails closed), and the Login page renders.
  // In dev mode the dev identity simply signs back in; the button still proves the transition.
  const signOut = () => {
    signOutUser();
    qc.clear();
    location.hash = '#/login';
  };

  return (
    <Page
      eyebrow="Access"
      title="Settings"
      width="narrow"
      intro="Preferences persist to your profile and follow you across sessions. The admin section manages the app's ingestion points."
    >
      <div className="card pad" style={{ marginBottom: 18 }}>
        <div className="eyebrow" style={{ marginBottom: 10 }}>
          Preferences
        </div>
        <div className="row gap8" style={{ marginBottom: 12, alignItems: 'center' }}>
          <span style={{ fontSize: 12.5, width: 130 }}>Dark theme</span>
          <Switch
            on={ui.theme === 'dark'}
            onChange={() => {
              const next = ui.theme === 'dark' ? 'light' : 'dark';
              ui.setTheme(next);
              persist({ theme: next });
            }}
          />
        </div>
        <div className="row gap8" style={{ marginBottom: 12, alignItems: 'center' }}>
          <span style={{ fontSize: 12.5, width: 130 }}>Default lens</span>
          <Dropdown
            value={ui.lens}
            options={LENSES}
            onChange={(l) => {
              ui.setLens(l);
              persist({ lens: l });
            }}
          />
        </div>
        <div className="row gap8" style={{ alignItems: 'center' }}>
          <span style={{ fontSize: 12.5, width: 130 }}>Persona</span>
          <Dropdown
            value={ui.persona}
            options={PERSONAS}
            onChange={(p) => {
              ui.setPersona(p);
              persist({ persona: p });
            }}
          />
        </div>
      </div>

      <div className="card pad" style={{ marginBottom: 18 }}>
        <div className="eyebrow" style={{ marginBottom: 10 }}>
          Session
        </div>
        <div className="row gap8" style={{ alignItems: 'center' }}>
          <span className="muted" style={{ fontSize: 12, flex: 1 }}>
            {me.data?.email ?? 'signed in'} · sessions are 1-hour Google ID tokens; signing out
            clears this device and all cached data.
          </span>
          <button className="btn ghost sm" onClick={signOut}>
            <Icon n="lock" s={14} /> Sign out
          </button>
        </div>
      </div>

      {isAdmin && (
        <>
          <CatalogueSetup />
          <Administrators />
          <div className="row gap8" style={{ marginBottom: 8 }}>
            <span className="eyebrow" style={{ margin: 0 }}>
              Ingestion source registry
            </span>
            <span className="chip orange" style={{ fontSize: 9 }}>
              admin
            </span>
            <span className="muted" style={{ fontSize: 10.5, marginLeft: 'auto' }}>
              the app picks each source's active origin by mode — recorded (database) in hermetic
              runs, online when live
            </span>
          </div>
          <div style={{ display: 'grid', gap: 8, marginBottom: 18 }}>
            {(sources.data ?? []).map((s) => (
              <SourceRowView key={s.key} s={s} />
            ))}
          </div>
          <div className="card" style={{ padding: '11px 14px', marginBottom: 8 }}>
            <div className="row gap8">
              <Icon n="upload" s={14} style={{ color: 'var(--interactive)' }} />
              <span style={{ fontSize: 12 }}>
                Catalogue upload routes through first-run onboarding (mapping studio, F4) — new
                versions create new snapshots, never overwrites.
              </span>
            </div>
          </div>
        </>
      )}
    </Page>
  );
}
