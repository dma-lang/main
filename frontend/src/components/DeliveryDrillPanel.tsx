// Delivery drilldown (shared by the C3 trace page + the A2 Delivery tab): underneath a subcap's
// story count sit (1) the CLIENTS — Jira project keys, the corpus' client/engagement proxy — and
// (2) deterministic STORY CLUSTERS (token-overlap, no model call) that group stories with similar
// characteristics and list the related clients delivering into the same theme. Every figure comes
// from the same story_catalogue_link ∪ story join as n_stories and the mission-control heatmap,
// so the numbers reconcile exactly — that is the traceability contract.
import { useState } from 'react';

import type { StoryRow } from '../api/client';
import { useSubcapDelivery } from '../api/queries';
import { Icon } from '../lib/icons';
import { Bar } from './primitives';

function scoreColor(v: number): string {
  return v >= 3 ? 'var(--interactive)' : v >= 2 ? 'var(--z-blue)' : 'var(--z-orange)';
}

const SUBSCORES: [string, keyof Pick<StoryRow, 'ac_score' | 'sd_score' | 'story_score'>][] = [
  ['Acceptance criteria', 'ac_score'],
  ['Solution design', 'sd_score'],
  ['Story score', 'story_score'],
];

// One concrete story, expandable to its real sub-scores — the "specific story details".
function StoryLine({ st, showClient }: { st: StoryRow; showClient?: boolean }) {
  const [open, setOpen] = useState(false);
  const cs = st.composite_score ?? 0;
  const hasSub = st.ac_score != null || st.sd_score != null || st.story_score != null;
  return (
    <div className="card" style={{ overflow: 'hidden', background: 'var(--surface-base)' }}>
      <div
        className="between"
        style={{ padding: '7px 10px', cursor: 'pointer' }}
        onClick={() => setOpen(!open)}
      >
        <div className="row gap8" style={{ minWidth: 0 }}>
          <Icon n={open ? 'chevD' : 'chevR'} s={12} style={{ color: 'var(--text-tertiary)' }} />
          <span className="mono" style={{ fontSize: 10.5, flex: 'none' }}>
            {st.story_key}
          </span>
          {st.is_synthetic && (
            <span className="chip orange" style={{ fontSize: 8.5, flex: 'none' }} title="synthetic story (not real Jira delivery)">
              synthetic
            </span>
          )}
          {showClient && st.project_key && (
            <span className="chip soft" style={{ fontSize: 9, flex: 'none' }}>
              {st.project_key}
            </span>
          )}
          <span
            className="muted"
            style={{
              fontSize: 10.5,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {st.summary}
          </span>
        </div>
        <b className="num" style={{ fontSize: 11.5, flex: 'none', color: scoreColor(cs) }}>
          {cs.toFixed(1)}
        </b>
      </div>
      {open && (
        <div
          className="fade-in"
          style={{ padding: '8px 12px 12px', borderTop: '1px solid var(--border-subtle)' }}
        >
          <div className="muted" style={{ fontSize: 11, marginBottom: hasSub ? 8 : 0 }}>
            {st.project_key ? (
              <>
                Delivered under Jira project <b>{st.project_key}</b>
              </>
            ) : (
              'No Jira project recorded'
            )}
            {st.story_sv_code ? ` · ${st.story_sv_code}` : ''}
            {st.confidence_level ? ` · confidence ${st.confidence_level}` : ''}
          </div>
          {hasSub && (
            <div className="row gap12" style={{ maxWidth: 420 }}>
              {SUBSCORES.map(([label, key]) => {
                const v = st[key];
                return (
                  <div key={key} style={{ flex: 1 }}>
                    <div className="between" style={{ fontSize: 10.5, marginBottom: 3 }}>
                      <span className="muted">{label}</span>
                      <b className="num">{v != null ? v.toFixed(1) : 'n/a'}</b>
                    </div>
                    <Bar v={v ?? 0} max={5} color={scoreColor(v ?? 0)} />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function DeliveryDrillPanel({
  version,
  id,
  synthetic,
}: {
  version: string;
  id: string;
  synthetic?: boolean; // controlled by the parent (workbench tab); uncontrolled => own toggle
}) {
  const [ownSyn, setOwnSyn] = useState(false);
  const syn = synthetic ?? ownSyn;
  const controlled = synthetic !== undefined;
  const drill = useSubcapDelivery(version, id, syn);
  const [openClient, setOpenClient] = useState<string | null>(null);
  const [openCluster, setOpenCluster] = useState<number | null>(null);
  const d = drill.data;

  // Own toggle only when NOT controlled by a parent (e.g. on the Trace page). In the workbench the
  // Delivery tab owns one toggle for both the story list and this panel.
  const toggle = !controlled && (
    <div className="row gap8" style={{ marginBottom: 12 }}>
      <button
        className={'btn xs ' + (!syn ? 'primary' : 'ghost')}
        onClick={() => setOwnSyn(false)}
      >
        Jira only
      </button>
      <button
        className={'btn xs ' + (syn ? 'primary' : 'ghost')}
        onClick={() => setOwnSyn(true)}
        title="Include the labelled synthetic stories"
      >
        + synthetic
      </button>
    </div>
  );

  if (drill.isLoading) {
    return (
      <div>
        {toggle}
        <div className="muted" style={{ fontSize: 12 }}>
          Parsing clients and clustering stories…
        </div>
      </div>
    );
  }
  if (!d || d.total_stories === 0) {
    return (
      <div>
        {toggle}
        <div className="banner info" style={{ fontSize: 11.5 }}>
          <Icon n="book" s={13} />
          No {syn ? '' : 'real Jira '}delivery carries onto this subcap in {version}
          {syn ? ' (Jira or synthetic)' : ''} — nothing to parse into clients or clusters.
          {!syn && ' Toggle “+ synthetic” to include synthetic stories.'}
        </div>
      </div>
    );
  }

  return (
    <div>
      {toggle}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: 14,
          alignItems: 'start',
        }}
      >
      <div className="card pad" style={{ padding: 14 }}>
        <div className="between" style={{ marginBottom: 4 }}>
          <div className="h3">Clients · {d.n_clients}</div>
          <span className="muted" style={{ fontSize: 10 }}>
            {d.total_stories.toLocaleString()} stories
          </span>
        </div>
        <div className="muted" style={{ fontSize: 11, marginBottom: 10, lineHeight: 1.45 }}>
          Parsed from the Jira <b>project key</b> (the corpus' client/engagement proxy). Click one
          for its strongest stories.
        </div>
        <div style={{ display: 'grid', gap: 6 }}>
          {d.clients.map((c) => {
            const open = openClient === c.project_key;
            return (
              <div key={c.project_key} className="card" style={{ overflow: 'hidden' }}>
                <div
                  className="between"
                  style={{ padding: '9px 11px', cursor: 'pointer' }}
                  onClick={() => setOpenClient(open ? null : c.project_key)}
                >
                  <div className="row gap8" style={{ minWidth: 0 }}>
                    <Icon
                      n={open ? 'chevD' : 'chevR'}
                      s={13}
                      style={{ color: 'var(--text-tertiary)' }}
                    />
                    <b className="mono" style={{ fontSize: 12 }}>
                      {c.project_key}
                    </b>
                    {c.subverticals.slice(0, 3).map((sv) => (
                      <span key={sv} className="chip soft" style={{ fontSize: 9 }}>
                        {sv}
                      </span>
                    ))}
                  </div>
                  <div className="row gap10" style={{ flex: 'none' }}>
                    {c.avg_composite != null && (
                      <span
                        className="num"
                        style={{ fontSize: 11, color: scoreColor(c.avg_composite) }}
                        title="average composite score"
                      >
                        ø {c.avg_composite.toFixed(1)}
                      </span>
                    )}
                    <b className="num" style={{ fontSize: 12 }}>
                      {c.stories.toLocaleString()}
                    </b>
                    <span className="muted num" style={{ fontSize: 10 }}>
                      {Math.round(c.share * 100)}%
                    </span>
                  </div>
                </div>
                {open && (
                  <div
                    className="fade-in"
                    style={{
                      padding: '8px 10px 10px',
                      borderTop: '1px solid var(--border-subtle)',
                      display: 'grid',
                      gap: 5,
                    }}
                  >
                    {c.top.map((st) => (
                      <StoryLine key={st.story_key} st={st} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        {d.n_clients > d.clients.length && (
          <div className="muted" style={{ fontSize: 10.5, marginTop: 8 }}>
            Top {d.clients.length} of {d.n_clients} clients shown (by delivered stories).
          </div>
        )}
      </div>

      <div className="card pad" style={{ padding: 14 }}>
        <div className="between" style={{ marginBottom: 4 }}>
          <div className="h3">Story clusters · {d.clusters.length}</div>
          <span className="muted" style={{ fontSize: 10 }} title="deterministic token overlap ≥ 0.5">
            deterministic
          </span>
        </div>
        <div className="muted" style={{ fontSize: 11, marginBottom: 10, lineHeight: 1.45 }}>
          Stories with similar characteristics, grouped by shared terms over the top{' '}
          {d.clustered_over.toLocaleString()} by composite — each cluster lists the{' '}
          <b>related clients</b> delivering the same theme.
        </div>
        {d.clusters.length === 0 && (
          <div className="banner info" style={{ fontSize: 11.5 }}>
            <Icon n="layers" s={13} />
            No theme reaches 3+ similar stories — the delivery here is heterogeneous, not thin.
          </div>
        )}
        <div style={{ display: 'grid', gap: 6 }}>
          {d.clusters.map((cl) => {
            const open = openCluster === cl.cluster_id;
            return (
              <div key={cl.cluster_id} className="card" style={{ overflow: 'hidden' }}>
                <div
                  style={{ padding: '9px 11px', cursor: 'pointer' }}
                  onClick={() => setOpenCluster(open ? null : cl.cluster_id)}
                >
                  <div className="between">
                    <div className="row gap8" style={{ minWidth: 0 }}>
                      <Icon
                        n={open ? 'chevD' : 'chevR'}
                        s={13}
                        style={{ color: 'var(--text-tertiary)' }}
                      />
                      <b style={{ fontSize: 12.5 }}>{cl.label}</b>
                    </div>
                    <div className="row gap10" style={{ flex: 'none' }}>
                      {cl.avg_composite != null && (
                        <span
                          className="num"
                          style={{ fontSize: 11, color: scoreColor(cl.avg_composite) }}
                          title="average composite score"
                        >
                          ø {cl.avg_composite.toFixed(1)}
                        </span>
                      )}
                      <b className="num" style={{ fontSize: 12 }}>
                        {cl.stories}
                      </b>
                    </div>
                  </div>
                  <div className="row wrap gap6" style={{ marginTop: 6, paddingLeft: 21 }}>
                    {cl.clients.slice(0, 6).map((pk) => (
                      <span key={pk} className="chip blue" style={{ fontSize: 9.5 }}>
                        {pk}
                      </span>
                    ))}
                    {cl.clients.length > 6 && (
                      <span className="muted" style={{ fontSize: 10 }}>
                        +{cl.clients.length - 6} more
                      </span>
                    )}
                    {cl.clients.length > 1 && (
                      <span className="muted" style={{ fontSize: 10 }}>
                        · {cl.clients.length} related clients
                      </span>
                    )}
                  </div>
                </div>
                {open && (
                  <div
                    className="fade-in"
                    style={{
                      padding: '8px 10px 10px',
                      borderTop: '1px solid var(--border-subtle)',
                      display: 'grid',
                      gap: 5,
                    }}
                  >
                    {cl.sample.map((st) => (
                      <StoryLine key={st.story_key} st={st} showClient />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        {d.unclustered > 0 && (
          <div className="muted" style={{ fontSize: 10.5, marginTop: 8 }}>
            {d.unclustered.toLocaleString()} stories don't share a 3+-story theme and stay
            unclustered — counted, never hidden.
          </div>
        )}
        </div>
      </div>
    </div>
  );
}
