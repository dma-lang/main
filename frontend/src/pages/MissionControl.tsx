// Mission control (A1) — refined prototype: pillar tiles + a concentration heatmap that reframes by
// the active lens (columns = composite-score quality bands). Clicking a lens-grouped row opens an
// in-place DRILL DRAWER listing that group's subcaps (delivery-ranked, peekable) with an
// "Open in <page>" hand-off; pillar-lens rows are subcaps and peek directly.
import { useState } from 'react';

import {
  useChangeFlags,
  useHeatmap,
  useHeatmapDrill,
  useSuggestions,
  useSummary,
  useVersions,
} from '../api/queries';
import { Bar, Drawer, Empty, Page, PillarDot, SC } from '../components/primitives';
import { go, openPeek, toast } from '../lib/events';
import { heatBg, PILLAR_COLORS } from '../lib/helpers';
import { Icon, type IconName } from '../lib/icons';
import { type Pillar, useUi } from '../state/store';

const QUICK: [string, string, IconName][] = [
  ['explorer', 'Capability workbench', 'compass'],
  ['stories', 'Story library', 'book'],
  ['digest', 'Quarterly digest', 'brief'],
  ['versions', 'Version timeline', 'clock'],
];

const LENS_TITLE: Record<string, string> = {
  pillar: 'most-delivered subcaps',
  'value-chain': 'value-chain clusters',
  subvertical: 'subverticals',
  vendor: 'platform vendors',
  maturity: 'tier coverage',
};

// where a lens-group's drill drawer hands off to — [route, page label]
const LENS_CTA: Record<string, [string, string]> = {
  'value-chain': ['value-chain', 'Value chain atlas'],
  subvertical: ['value-chain', 'Value chain atlas'],
  vendor: ['platforms', 'Platform catalog'],
  maturity: ['explorer', 'Capability workbench'],
};

interface DrillTarget {
  key: string;
  label: string;
  subtitle: string;
}

export function MissionControl() {
  const version = useUi((s) => s.version);
  const pillar = useUi((s) => s.pillar);
  const sv = useUi((s) => s.sv);
  const lens = useUi((s) => s.lens);
  const setPillar = useUi((s) => s.setPillar);
  const summary = useSummary(version, sv);
  const heat = useHeatmap(version, lens, pillar, sv);
  const flagsQ = useChangeFlags('open');
  const pendingQ = useSuggestions('pending');
  const versionsQ = useVersions();
  const liveVersions = (versionsQ.data ?? []).filter(
    (v) => v.status === 'provisioned' || v.status === 'active',
  );
  const pillars = summary.data?.pillars ?? [];
  const total = summary.data?.total_subcaps ?? 0;
  const fc = flagsQ.data?.counts;
  const highFlags = fc ? (fc.BLOCKING ?? 0) + (fc.HIGH ?? 0) : 0;
  const pendingCount = pendingQ.data?.length ?? 0;

  const [drill, setDrill] = useState<DrillTarget | null>(null);
  const drillQ = useHeatmapDrill(version, lens, drill?.key ?? null, pillar, sv);
  const isPillar = lens === 'pillar';
  const cta = LENS_CTA[lens];

  return (
    <Page
      eyebrow="A · Explore"
      title="Mission control"
      intro={
        <>
          Is the system healthy, and what needs me right now — answered in one glance. The headline{' '}
          <b>concentration heatmap</b> reframes by the active lens — change the <b>Lens</b> in the
          header to regroup, then click a row to drill into its subcaps.
        </>
      }
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
            <div className="h2">Concentration · {LENS_TITLE[lens] ?? 'subcaps'}</div>
            <span className="chip soft">
              <Icon n="book" s={12} />
              {version || '—'} catalog
            </span>
          </div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 14 }}>
            Cell intensity = delivered stories by quality band (composite score), grouped by the
            active lens — change the Lens in the header to regroup.{' '}
            {isPillar ? 'Click a subcap to peek it.' : 'Click a row to drill into its subcaps.'}
          </div>
          {heat.isLoading && (
            <div className="muted" style={{ fontSize: 12 }}>
              Loading delivery concentration…
            </div>
          )}
          {heat.data && heat.data.rows.length === 0 && (
            <Empty
              icon="trend"
              title="No delivery mapped yet"
              desc="Once the Jira story corpus is carried onto this version, the concentration heatmap lights up here."
              cta="Run carry-forward"
              onCta={() => go('onboarding')}
            />
          )}
          {heat.data && heat.data.rows.length > 0 && (
            <table className="tbl" style={{ tableLayout: 'fixed' }}>
              <thead>
                <tr>
                  <th style={{ width: '38%' }}>{isPillar ? 'Subcap' : LENS_TITLE[lens]}</th>
                  {heat.data.axis.map((q) => (
                    <th
                      key={q}
                      title={q + ' composite'}
                      style={{ textAlign: 'center', padding: '9px 2px', fontSize: 10 }}
                    >
                      {q.split('–')[0]}
                    </th>
                  ))}
                  <th style={{ width: 64, textAlign: 'right' }}>Stories</th>
                </tr>
              </thead>
              <tbody>
                {heat.data.rows.map((r) => {
                  // Pillar-lens rows ARE subcaps -> peek; every other lens row opens the drill drawer.
                  const onRow = () =>
                    isPillar
                      ? openPeek(r.key)
                      : setDrill({ key: r.key, label: r.label, subtitle: r.subtitle });
                  return (
                    <tr key={r.key} style={{ cursor: 'pointer' }} onClick={onRow}>
                      <td>
                        <div className="row gap8">
                          {r.pillar && <PillarDot p={r.pillar} s={7} />}
                          <div style={{ minWidth: 0 }}>
                            {isPillar ? (
                              <SC id={r.key}>{r.label}</SC>
                            ) : (
                              <div
                                className="sclink"
                                style={{
                                  fontSize: 12.5,
                                  whiteSpace: 'nowrap',
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                }}
                              >
                                {r.label}
                              </div>
                            )}
                          </div>
                          {!isPillar && (
                            <Icon
                              n="branch"
                              s={11}
                              style={{ flex: 'none', color: 'var(--text-disabled)' }}
                            />
                          )}
                        </div>
                      </td>
                      {r.cells.map((c, i) => (
                        <td key={i} style={{ padding: '6px 3px' }}>
                          <div
                            className="heatcell"
                            title={`${c} stories · ${heat.data!.axis[i]} composite`}
                            style={{ height: 26, background: heatBg(c / (heat.data!.max || 1)) }}
                          />
                        </td>
                      ))}
                      <td
                        className="num"
                        style={{ textAlign: 'right', fontSize: 12, fontWeight: 600 }}
                      >
                        {r.total.toLocaleString()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <div style={{ display: 'grid', gap: 14 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <div
              className="kpi"
              style={{ padding: '14px 15px', cursor: 'pointer' }}
              onClick={() => go('change-flags')}
            >
              <div
                className="kv"
                style={{ fontSize: 24, color: highFlags ? 'var(--z-orange)' : 'var(--text-primary)' }}
              >
                {highFlags}
              </div>
              <div className="kl">High flags</div>
            </div>
            <div
              className="kpi"
              style={{ padding: '14px 15px', cursor: 'pointer' }}
              onClick={() => go('suggestions')}
            >
              <div className="kv" style={{ fontSize: 24 }}>
                {pendingCount}
              </div>
              <div className="kl">Suggestions pending</div>
            </div>
            <div
              className="kpi"
              style={{ padding: '14px 15px', cursor: 'pointer' }}
              onClick={() => go('versions')}
            >
              <div className="kv" style={{ fontSize: 24 }}>
                {versionsQ.data ? liveVersions.length : '—'}
              </div>
              <div className="kl">Versions provisioned</div>
            </div>
            <div className="kpi" style={{ padding: '14px 15px' }}>
              <div className="kv" style={{ fontSize: 24 }}>
                {total}
              </div>
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

      {/* Lens-group drill drawer — the subcaps behind a heatmap row, delivery-ranked + peekable,
          with a hand-off to the lens's full page (vendor→platforms, stage→value-chain, …). */}
      {drill && (
        <Drawer
          open
          onClose={() => setDrill(null)}
          sub={LENS_TITLE[lens]}
          title={drill.label}
          width={460}
          foot={
            cta && (
              <button
                className="btn primary sm"
                style={{ width: '100%', justifyContent: 'center' }}
                onClick={() => {
                  setDrill(null);
                  go(cta[0]);
                }}
              >
                Open in {cta[1]}
                <Icon n="arrowR" s={14} />
              </button>
            )
          }
        >
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 8,
              marginBottom: 14,
            }}
          >
            <div className="card" style={{ padding: '10px 12px', textAlign: 'center' }}>
              <div className="num" style={{ fontSize: 20, fontWeight: 700, color: 'var(--interactive)' }}>
                {drillQ.data?.total_subcaps ?? '—'}
              </div>
              <div className="muted" style={{ fontSize: 10 }}>
                subcaps
              </div>
            </div>
            <div className="card" style={{ padding: '10px 12px', textAlign: 'center' }}>
              <div className="num" style={{ fontSize: 20, fontWeight: 700 }}>
                {(drillQ.data?.total_stories ?? 0).toLocaleString()}
              </div>
              <div className="muted" style={{ fontSize: 10 }}>
                delivered stories
              </div>
            </div>
          </div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 12, lineHeight: 1.5 }}>
            {drill.subtitle}
          </div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Subcaps in this group · top by delivery
          </div>
          {drillQ.isLoading && (
            <div className="muted" style={{ fontSize: 12 }}>
              Loading subcaps…
            </div>
          )}
          {drillQ.data && drillQ.data.subcaps.length === 0 && (
            <Empty
              icon="layers"
              title="No subcaps"
              desc="No delivered subcaps fall in this group for the current filters."
            />
          )}
          {drillQ.data && drillQ.data.subcaps.length > 0 && (
            <div style={{ display: 'grid', gap: 6 }}>
              {drillQ.data.subcaps.map((s) => (
                <div
                  key={s.id}
                  className="card hov"
                  style={{ padding: '9px 12px', cursor: 'pointer' }}
                  onClick={() => {
                    setDrill(null);
                    openPeek(s.id);
                  }}
                >
                  <div className="between">
                    <div className="row gap8" style={{ minWidth: 0 }}>
                      <PillarDot p={s.pillar} s={6} />
                      <span
                        style={{
                          fontSize: 12.5,
                          fontWeight: 500,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {s.name}
                      </span>
                    </div>
                    <div className="row gap8" style={{ flex: 'none' }}>
                      <span className="mono sclink" style={{ fontSize: 10.5 }}>
                        {s.id}
                      </span>
                      <b className="num" style={{ fontSize: 11, color: 'var(--interactive)' }}>
                        {s.stories}
                      </b>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Drawer>
      )}
    </Page>
  );
}
