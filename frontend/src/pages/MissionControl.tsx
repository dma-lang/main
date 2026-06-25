// Mission control (A1) — ported from the prototype, wired to /api/catalogue/{v}/summary.
// Pillar tiles render real counts/completeness/decay; the concentration heatmap + flag/suggestion
// KPIs light up once their data lands (F5 stories / F7 evidence).
import { Fragment, useState } from 'react';

import {
  useChangeFlags,
  useHeatmap,
  useSuggestions,
  useSummary,
  useUnscopedSubverticals,
  useVersions,
} from '../api/queries';
import { Bar, Empty, Page, PillarDot, SC } from '../components/primitives';
import { go, openReasoning, toast } from '../lib/events';
import { heatBg, PILLAR_COLORS } from '../lib/helpers';
import { Icon, type IconName } from '../lib/icons';
import { type Pillar, useUi } from '../state/store';

// orange intensity for the unscoped-subvertical heatmap (distinct from the teal delivery scale)
const orangeBg = (t: number) =>
  `rgba(234, 142, 56, ${(0.08 + 0.72 * Math.max(0, Math.min(1, t))).toFixed(3)})`;

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
  const unscoped = useUnscopedSubverticals(version);
  const unscopedCands = unscoped.data?.candidates ?? [];
  const [expanded, setExpanded] = useState<string | null>(null);

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
            <div className="h2">Concentration · {LENS_TITLE[lens] ?? 'subcaps'}</div>
            <span className="chip soft">
              <Icon n="book" s={12} />
              {version || '—'} catalog
            </span>
          </div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 14 }}>
            Cell intensity = delivered stories by quality band (composite score), grouped by the
            active lens — change the Lens in the header to regroup. Click a row to explore.
          </div>
          {heat.isLoading && <div className="muted" style={{ fontSize: 12 }}>Loading delivery concentration…</div>}
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
                  <th style={{ width: '38%' }}>{lens === 'pillar' ? 'Subcap' : LENS_TITLE[lens]}</th>
                  {heat.data.axis.map((q) => (
                    <th key={q} title={q + ' composite'} style={{ textAlign: 'center', padding: '9px 2px', fontSize: 10 }}>
                      {q.split('–')[0]}
                    </th>
                  ))}
                  <th style={{ width: 64, textAlign: 'right' }}>Stories</th>
                </tr>
              </thead>
              <tbody>
                {heat.data.rows.map((r) => {
                  // Pillar-lens rows are SUBCAPS — every part of the row drills to the trace
                  // specifics (clients, story details, clusters); the label still peeks.
                  const drill = lens === 'pillar' ? () => go('trace/' + r.key) : undefined;
                  return (
                    <tr key={r.key}>
                      <td>
                        <div className="row gap8">
                          {r.pillar && <PillarDot p={r.pillar} s={7} />}
                          <div style={{ minWidth: 0 }}>
                            {lens === 'pillar' ? (
                              <SC id={r.key}>{r.label}</SC>
                            ) : (
                              <div
                                className="sclink"
                                style={{ fontSize: 12.5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                                onClick={() => go('explorer')}
                              >
                                {r.label}
                              </div>
                            )}
                          </div>
                          {drill && (
                            <button
                              className="linkbtn"
                              style={{ flex: 'none', padding: 0 }}
                              title={'Trace ' + r.key + ' — clients, stories, clusters'}
                              onClick={drill}
                            >
                              <Icon n="branch" s={12} />
                            </button>
                          )}
                        </div>
                      </td>
                      {r.cells.map((c, i) => (
                        <td key={i} style={{ padding: '6px 3px' }}>
                          <div
                            className="heatcell"
                            title={`${c} stories · ${heat.data!.axis[i]} composite${drill ? ' — click to trace' : ''}`}
                            style={{
                              height: 26,
                              background: heatBg(c / (heat.data!.max || 1)),
                              cursor: drill ? 'pointer' : 'default',
                            }}
                            onClick={drill}
                          />
                        </td>
                      ))}
                      <td
                        className="num"
                        title={drill ? 'Open the delivery drilldown for ' + r.key : undefined}
                        style={{
                          textAlign: 'right',
                          fontSize: 12,
                          fontWeight: 600,
                          cursor: drill ? 'pointer' : 'default',
                        }}
                        onClick={drill}
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
            <div className="kpi" style={{ padding: '14px 15px', cursor: 'pointer' }} onClick={() => go('change-flags')}>
              <div className="kv" style={{ fontSize: 24, color: highFlags ? 'var(--z-orange)' : 'var(--text-primary)' }}>
                {highFlags}
              </div>
              <div className="kl">High flags</div>
            </div>
            <div className="kpi" style={{ padding: '14px 15px', cursor: 'pointer' }} onClick={() => go('suggestions')}>
              <div className="kv" style={{ fontSize: 24 }}>{pendingCount}</div>
              <div className="kl">Suggestions pending</div>
            </div>
            <div className="kpi" style={{ padding: '14px 15px' }}>
              <div className="kv" style={{ fontSize: 24 }}>
                {versionsQ.data ? liveVersions.length : '—'}
              </div>
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

      {/* Unscoped subverticals (B) — AI-identified candidates we have NOT scoped, rendered ORANGE
          with a drilldown. Gated proposals (claim HYPOTHESIS) from the unscoped-Jira detector;
          review/approve in Notifications. Only shows when the detector has found candidates. */}
      {unscopedCands.length > 0 && unscoped.data && (
        <div className="card pad" style={{ marginTop: 18 }}>
          <div className="between" style={{ marginBottom: 4 }}>
            <div className="h2" style={{ color: 'var(--z-orange)' }}>
              <Icon n="flag" s={15} /> Unscoped subverticals · {unscopedCands.length} identified
            </div>
            <span className="chip orange" style={{ fontSize: 11 }}>
              AI · gated proposal
            </span>
          </div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 14 }}>
            Clients delivering real Jira <b>outside</b> the nine modelled subverticals — each a gated
            proposal for a new subvertical (claim HYPOTHESIS), volume-stratified, overlap-checked.
            Orange = unscoped; click a row to drill in, then review/approve under Notifications.
          </div>
          <table className="tbl" style={{ tableLayout: 'fixed' }}>
            <thead>
              <tr>
                <th style={{ width: '40%' }}>Candidate subvertical · client</th>
                {unscoped.data.axis.map((q) => (
                  <th key={q} title={q + ' composite'} style={{ textAlign: 'center', padding: '9px 2px', fontSize: 10 }}>
                    {q.split('–')[0]}
                  </th>
                ))}
                <th style={{ width: 64, textAlign: 'right' }}>Stories</th>
              </tr>
            </thead>
            <tbody>
              {unscopedCands.map((c) => {
                const open = expanded === c.flag_id;
                const sevOrange = c.severity === 'BLOCKING' || c.severity === 'HIGH';
                return (
                  <Fragment key={c.flag_id}>
                    <tr>
                      <td>
                        <div className="row gap8">
                          <button
                            className="linkbtn"
                            style={{ flex: 'none', padding: 0 }}
                            title={open ? 'Collapse' : 'Drill into this candidate'}
                            onClick={() => setExpanded(open ? null : c.flag_id)}
                          >
                            <Icon n={open ? 'chevD' : 'chevR'} s={13} />
                          </button>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontWeight: 600, fontSize: 12.5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                              {c.name}
                            </div>
                            <div className="muted" style={{ fontSize: 10.5 }}>
                              client {c.client}
                              {c.code ? ' · ' + c.code : ''}
                            </div>
                          </div>
                          <span className={'chip ' + (sevOrange ? 'orange' : 'soft')} style={{ flex: 'none', fontSize: 9.5 }}>
                            {c.severity}
                          </span>
                        </div>
                      </td>
                      {c.cells.map((cell, i) => (
                        <td key={i} style={{ padding: '6px 3px' }}>
                          <div
                            className="heatcell"
                            title={`${cell} stories · ${unscoped.data!.axis[i]} composite`}
                            style={{ height: 26, background: orangeBg(cell / (unscoped.data!.max || 1)) }}
                          />
                        </td>
                      ))}
                      <td className="num" style={{ textAlign: 'right', fontSize: 12, fontWeight: 600 }}>
                        {c.stories.toLocaleString()}
                      </td>
                    </tr>
                    {open && (
                      <tr>
                        <td colSpan={unscoped.data!.axis.length + 2} style={{ background: 'var(--surface-raised)' }}>
                          <div className="row wrap gap6" style={{ marginBottom: 10 }}>
                            {c.claim_label && <span className="chip orange" style={{ fontSize: 10 }}>{c.claim_label}</span>}
                            {c.source_tier && <span className="chip soft" style={{ fontSize: 10 }}>{c.source_tier}</span>}
                            {c.ers != null && <span className="chip soft" style={{ fontSize: 10 }}>ERS {c.ers.toFixed(2)}</span>}
                            <span className="chip soft" style={{ fontSize: 10 }}>
                              closest {c.overlap_sv ?? 'none'} · {Math.round(c.overlap * 100)}%
                            </span>
                            {c.pillars.map((p) => (
                              <span key={p} className="chip soft" style={{ fontSize: 10 }}>{p}</span>
                            ))}
                          </div>
                          <div className="eyebrow" style={{ marginBottom: 5 }}>Top capabilities (unscoped delivery)</div>
                          <div className="row wrap gap6" style={{ marginBottom: 10 }}>
                            {c.top_capabilities.slice(0, 6).map((cap) => (
                              <span key={cap.name} className="chip soft" style={{ fontSize: 10.5 }}>
                                {cap.name} · {cap.n}
                              </span>
                            ))}
                          </div>
                          {c.samples.length > 0 && (
                            <>
                              <div className="eyebrow" style={{ marginBottom: 5 }}>Sample stories</div>
                              <ul className="muted" style={{ fontSize: 11.5, margin: '0 0 10px', paddingLeft: 16 }}>
                                {c.samples.slice(0, 4).map((s, i) => (
                                  <li key={i}>{s}</li>
                                ))}
                              </ul>
                            </>
                          )}
                          {c.status === 'detected' && (
                            <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>
                              Auto-detected from unscoped delivery. Run the subvertical scan
                              (Notifications → Scan for anomalies) to gate it as an approvable proposal.
                            </div>
                          )}
                          <div className="row gap12">
                            {c.chain_id && (
                              <button className="linkbtn" onClick={() => c.chain_id && openReasoning(c.chain_id)}>
                                <Icon n="eye" s={13} /> Reasoning
                              </button>
                            )}
                            <button className="linkbtn" onClick={() => go('change-flags')}>
                              <Icon n="flag" s={13} /> Review in Notifications
                            </button>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Page>
  );
}
