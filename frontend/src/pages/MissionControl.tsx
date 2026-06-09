// Mission control (A1) — ported from the prototype, wired to /api/catalogue/{v}/summary.
// Pillar tiles render real counts/completeness/decay; the concentration heatmap + flag/suggestion
// KPIs light up once their data lands (F5 stories / F7 evidence).
import { useSummary } from '../api/queries';
import { Bar, Empty, Page, PillarDot } from '../components/primitives';
import { go, toast } from '../lib/events';
import { PILLAR_COLORS } from '../lib/helpers';
import { Icon, type IconName } from '../lib/icons';
import { type Pillar, useUi } from '../state/store';

const QUICK: [string, string, IconName][] = [
  ['explorer', 'Capability workbench', 'compass'],
  ['stories', 'Story library', 'book'],
  ['digest', 'Quarterly digest', 'brief'],
  ['versions', 'Version timeline', 'clock'],
];

export function MissionControl() {
  const version = useUi((s) => s.version);
  const pillar = useUi((s) => s.pillar);
  const setPillar = useUi((s) => s.setPillar);
  const summary = useSummary(version);
  const pillars = summary.data?.pillars ?? [];
  const total = summary.data?.total_subcaps ?? 0;

  return (
    <Page
      eyebrow="A · Explore"
      title="Mission control"
      intro="Is the system healthy, and what needs me right now — answered in one glance."
      actions={
        <button className="btn primary sm" onClick={() => toast('Pulling all sources…')}>
          <Icon n="refresh" s={14} /> Pull all sources
        </button>
      }
    >
      <div
        style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 14, marginBottom: 18 }}
      >
        {pillars.map((t) => {
          const comp = Math.round(t.completeness * 100);
          return (
            <div
              key={t.pillar_id}
              className="card"
              style={{
                padding: '16px 18px',
                borderTop: '3px solid ' + PILLAR_COLORS[t.pillar_id],
                opacity: pillar === 'all' || pillar === t.pillar_id ? 1 : 0.5,
                cursor: 'pointer',
              }}
              onClick={() => {
                setPillar(t.pillar_id as Pillar);
                go('explorer');
              }}
            >
              <div className="between">
                <div className="row gap8">
                  <PillarDot p={t.pillar_id} />
                  <span className="h3">{t.pillar_id}</span>
                </div>
                <Icon
                  n={comp >= 80 ? 'check' : 'flag'}
                  s={15}
                  style={{ color: comp >= 80 ? 'var(--interactive)' : 'var(--z-orange)' }}
                />
              </div>
              <div
                className="kv num"
                style={{ fontSize: 30, fontWeight: 700, marginTop: 8, color: 'var(--text-primary)' }}
              >
                {t.subcap_count}
              </div>
              <div className="muted" style={{ fontSize: 11.5 }}>
                subcaps · {t.name}
              </div>
              <div className="mt12">
                <div className="between" style={{ fontSize: 11, marginBottom: 4 }}>
                  <span className="muted">{comp}% complete</span>
                  <span className="muted">{t.decay} decay</span>
                </div>
                <Bar v={comp} max={100} color={PILLAR_COLORS[t.pillar_id]} />
              </div>
            </div>
          );
        })}
      </div>

      <div
        style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 18, alignItems: 'start' }}
      >
        <div className="card pad">
          <div className="between" style={{ marginBottom: 4 }}>
            <div className="h2">Concentration · subcaps</div>
            <span className="chip soft">
              <Icon n="book" s={12} />
              {version || '—'} catalog
            </span>
          </div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 14 }}>
            Cell intensity = real delivery volume per quarter, grouped by the active lens.
          </div>
          <Empty
            icon="trend"
            title="Delivery heatmap lands with the story corpus"
            desc="Carry-forward (F5) links the Jira delivery corpus to subcaps; the per-quarter concentration heatmap lights up then."
          />
        </div>

        <div style={{ display: 'grid', gap: 14 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <div className="kpi" style={{ padding: '14px 15px', cursor: 'pointer' }} onClick={() => go('change-flags')}>
              <div className="kv" style={{ fontSize: 24, color: 'var(--z-orange)' }}>0</div>
              <div className="kl">High flags</div>
            </div>
            <div className="kpi" style={{ padding: '14px 15px', cursor: 'pointer' }} onClick={() => go('suggestions')}>
              <div className="kv" style={{ fontSize: 24 }}>0</div>
              <div className="kl">Suggestions pending</div>
            </div>
            <div className="kpi" style={{ padding: '14px 15px' }}>
              <div className="kv" style={{ fontSize: 24 }}>{version ? '1/1' : '—'}</div>
              <div className="kl">Versions provisioned</div>
            </div>
            <div className="kpi" style={{ padding: '14px 15px' }}>
              <div className="kv" style={{ fontSize: 24 }}>{total}</div>
              <div className="kl">Subcaps queryable</div>
            </div>
          </div>
          <div className="card pad">
            <div className="h3" style={{ marginBottom: 10 }}>
              Quick links
            </div>
            <div style={{ display: 'grid', gap: 7 }}>
              {QUICK.map(([r, label, icon]) => (
                <button
                  key={r}
                  className="btn subtle sm"
                  style={{ justifyContent: 'flex-start' }}
                  onClick={() => go(r)}
                >
                  <Icon n={icon} s={14} />
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Page>
  );
}
