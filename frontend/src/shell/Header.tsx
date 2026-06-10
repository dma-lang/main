// Header — ported from the prototype shell.jsx, wired to live state/APIs.
// pillar/sv/lens/version are filter+context; theme/lens persist to control.users.preferences.
import { useChangeFlags, useMe, usePatchPreferences, useQaMetrics, useVersions } from '../api/queries';
import { Dropdown } from '../components/primitives';
import { go, toast } from '../lib/events';
import { PILLAR_COLORS } from '../lib/helpers';
import { Icon } from '../lib/icons';
import { type Pillar, useUi } from '../state/store';

const PILLARS: [Pillar, string][] = [
  ['all', 'All'],
  ['P1', 'P1'],
  ['P2', 'P2'],
  ['P3', 'P3'],
  ['P4', 'P4'],
];

const LENSES = [
  { v: 'pillar', l: 'Lens: Pillar' },
  { v: 'value-chain', l: 'Lens: Value chain' },
  { v: 'subvertical', l: 'Lens: Subvertical' },
  { v: 'maturity', l: 'Lens: Maturity' },
  { v: 'vendor', l: 'Lens: Vendor' },
  { v: 'lifecycle', l: 'Lens: Lifecycle' },
];

// 9 canonical subverticals (PRD D3).
const SUBVERTICALS = [
  { code: 'BK', name: 'Retail banking' },
  { code: 'CL', name: 'Commercial lending' },
  { code: 'CIB', name: 'Corporate & investment banking' },
  { code: 'FC', name: 'Consumer finance' },
  { code: 'CU', name: 'Credit unions' },
  { code: 'WM', name: 'Wealth & asset management' },
  { code: 'RIA', name: 'Registered investment advisors' },
  { code: 'IC', name: 'Insurance carriers' },
  { code: 'IB', name: 'Insurance brokerages' },
];

function initials(email?: string): string {
  if (!email) return 'CI';
  const name = email.split('@')[0].replace(/[._-]/g, ' ').trim();
  const parts = name.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? parts[0]?.[1] ?? '')).toUpperCase() || 'CI';
}

export function Header() {
  const ui = useUi();
  const me = useMe();
  const versionsQ = useVersions();
  const patch = usePatchPreferences();
  const flagsQ = useChangeFlags('open');
  const qa = useQaMetrics(ui.adminView);
  const c = flagsQ.data?.counts;
  const flagBadge = c ? (c.BLOCKING ?? 0) + (c.HIGH ?? 0) : 0;
  // Live monthly LLM spend vs the budget envelope (G8) — admin-only, like the prototype meter.
  const spend = qa.data?.spend_usd;
  const envelope = qa.data?.envelope_usd ?? 8000;
  const costVal = spend != null ? '$' + (spend / 1000).toFixed(2) + 'k' : '$—';
  const costPct = spend != null ? Math.min(100, (spend / envelope) * 100) : 0;

  const persist = (extra: Record<string, unknown>) =>
    patch.mutate({ theme: ui.theme, lens: ui.lens, persona: ui.persona, ...extra });

  const svOpts = [
    { v: 'all', l: 'All SV' },
    ...SUBVERTICALS.map((s) => ({ v: s.code, l: `${s.code} · ${s.name}` })),
  ];
  const versions = versionsQ.data ?? [];
  const versionOpts = versions.length
    ? versions.map((v) => ({ v: v.version_id, l: `${v.version_id} · ${v.status}` }))
    : [{ v: '', l: 'no catalogue yet' }];

  return (
    <div className="header">
      <div className="pillseg">
        {PILLARS.map(([v, l]) => (
          <button key={v} className={ui.pillar === v ? 'on' : ''} onClick={() => ui.setPillar(v)}>
            {v !== 'all' && <span className="dot" style={{ background: PILLAR_COLORS[v] }} />}
            {l}
          </button>
        ))}
      </div>
      <Dropdown label="All SV" value={ui.sv} options={svOpts} onChange={ui.setSv} />
      <Dropdown
        label="Lens"
        value={ui.lens}
        options={LENSES}
        onChange={(l) => {
          ui.setLens(l);
          persist({ lens: l });
        }}
      />
      <span className="spring" />
      <Dropdown
        value={ui.version}
        icon="branch"
        options={versionOpts}
        onChange={(v) => {
          ui.setVersion(v);
          toast('Active catalogue version: ' + (v || 'none'));
        }}
      />
      <button
        className="hdrsel"
        style={ui.adminView ? { borderColor: 'var(--border-focus)', color: 'var(--interactive)' } : {}}
        onClick={() => {
          ui.setAdminView(!ui.adminView);
          toast(ui.adminView ? 'is_admin off — power-user view' : 'is_admin on — admin view');
        }}
        title="Toggle is_admin flag"
      >
        <Icon n={ui.adminView ? 'shield' : 'lock'} s={14} />
        {ui.adminView ? 'Admin' : 'User'}
      </button>
      <button
        className="hicon"
        style={{ position: 'relative' }}
        onClick={() => go('change-flags')}
        title="Change flags"
      >
        <Icon n="bell" s={16} />
        {flagBadge > 0 && <span className="hbadge">{flagBadge}</span>}
      </button>
      {ui.adminView && (
        <div className="costmeter" title="Monthly LLM spend vs envelope">
          <span className="lbl">Cost</span>
          <span className="val">{costVal}</span>
          <span className="track">
            <span className="fill" style={{ width: costPct + '%' }} />
          </span>
        </div>
      )}
      <button
        className="hicon"
        onClick={() => {
          const t = ui.theme === 'dark' ? 'light' : 'dark';
          ui.setTheme(t);
          persist({ theme: t });
        }}
        title="Toggle theme"
      >
        <Icon n={ui.theme === 'dark' ? 'sun' : 'moon'} s={16} />
      </button>
      <button className="hicon" onClick={() => go('settings')} title="Settings">
        <Icon n="gear" s={16} />
      </button>
      <div className="avatar" title={ui.persona} onClick={() => go('settings')}>
        {initials(me.data?.email)}
      </div>
    </div>
  );
}
