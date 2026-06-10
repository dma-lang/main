// Settings — per-user preferences for everyone (theme · default lens · persona, persisted to
// control.users.preferences) and, for admins, the INGESTION SOURCE REGISTRY: every source the
// pipelines pull from, with the ACTIVE origin (database fixture vs online, per LLM_MODE), tier,
// cadence, last poll and health — a stale or erroring source is warned, never hidden — plus the
// persisted enable switch the scan jobs enforce. Upload entry routes into onboarding (F4).
import { type SourceRow } from '../api/client';
import { usePatchPreferences, useSourceActions, useSources } from '../api/queries';
import { Dropdown, Page, Switch, Tier } from '../components/primitives';
import { toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

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
  const persist = (extra: Record<string, unknown>) =>
    patch.mutate({ theme: ui.theme, lens: ui.lens, persona: ui.persona, ...extra });

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

      {isAdmin && (
        <>
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
