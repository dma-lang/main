// Lifecycle manager (F1) — trace subcaps through delivery and check the most-delivered against our
// productized offerings; high-delivery subcaps with no offering are the opportunity gaps. Ported from
// the prototype, wired to GET /api/catalogue/{v}/lifecycle. The AI-named proposal that bundles gap
// subcaps into a new offering is a gated consultant-loop suggestion (F8) — shown as a HYPOTHESIS.
import { useLifecycle } from '../api/queries';
import { Bar, Claim, Empty, Page, PillarDot } from '../components/primitives';
import { go } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

export function Lifecycle() {
  const version = useUi((s) => s.version);
  const lc = useLifecycle(version);
  const data = lc.data;
  const top = data?.top ?? [];
  const maxStories = Math.max(1, ...top.map((t) => t.stories));
  const gaps = top.filter((t) => !t.offering_id);

  const kpis: [string | number, string][] = [
    [data?.subcaps_delivered ?? 0, 'Subcaps delivered'],
    [data?.offerings ?? 0, 'Productized offerings'],
    [(data?.covered_pct ?? 0) + '%', 'Top subcaps covered'],
    [data?.gaps ?? 0, 'High-delivery gaps'],
  ];

  return (
    <Page
      eyebrow="F · Lifecycle & competition"
      title="Lifecycle manager"
      intro="Trace subcaps through delivery, check the most-delivered against our productized offerings, and let AI bundle high-delivery subcaps that have no offering into a proposed new one."
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 18 }}>
        {kpis.map(([v, l], i) => (
          <div key={i} className="kpi">
            <div className="kv">{v}</div>
            <div className="kl">{l}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 18, alignItems: 'start' }}>
        <div className="card pad">
          <div className="h2" style={{ marginBottom: 4 }}>
            Most-delivered subcaps, mapped to offerings
          </div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 14 }}>
            Delivery volume from the canonical story catalog. The right side shows whether each one is
            already packaged.
          </div>
          {top.length ? (
            <div style={{ display: 'grid', gap: 8 }}>
              {top.map((s) => (
                <div
                  key={s.id}
                  className="card hov"
                  style={{ padding: '11px 14px', cursor: 'pointer' }}
                  onClick={() => go('subcap/' + s.id)}
                >
                  <div className="between">
                    <div className="row gap8" style={{ minWidth: 0 }}>
                      <PillarDot p={s.pillar} s={7} />
                      <div style={{ minWidth: 0 }}>
                        <div className="sclink" style={{ fontSize: 12.5 }}>
                          {s.name}
                        </div>
                        <div className="mono muted" style={{ fontSize: 10.5 }}>
                          {s.id}
                        </div>
                      </div>
                    </div>
                    {s.offering_id ? (
                      <span className="chip teal" style={{ flex: 'none' }} title={s.offering_name ?? ''}>
                        <Icon n="package" s={11} /> {s.offering_id.replace('OFF-', '')}
                      </span>
                    ) : (
                      <span className="chip orange" style={{ flex: 'none' }}>
                        no offering
                      </span>
                    )}
                  </div>
                  <div className="row gap8 mt8">
                    <div style={{ flex: 1 }}>
                      <Bar
                        v={s.stories}
                        max={maxStories}
                        color={s.offering_id ? 'var(--interactive)' : 'var(--z-orange)'}
                      />
                    </div>
                    <b className="num" style={{ fontSize: 12, flex: 'none' }}>
                      {s.stories.toLocaleString()} stories
                    </b>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty
              icon="package"
              title="No delivery yet"
              desc="Run carry-forward to link the story corpus, then the most-delivered subcaps appear here."
            />
          )}
        </div>

        <div className="card pad" style={{ borderColor: 'var(--border-medium)', background: 'var(--surface-overlay)' }}>
          <div className="row gap8" style={{ marginBottom: 10 }}>
            <Claim label="HYPOTHESIS" />
            <span className="chip blue">
              <Icon n="sparkles" s={11} /> AI-named
            </span>
          </div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
            Suggested new offering · bundles the high-delivery subcaps that have no current offering.
          </div>
          <div className="h1" style={{ fontSize: 20, marginBottom: 10 }}>
            {data?.gaps ?? 0} gap{(data?.gaps ?? 0) === 1 ? '' : 's'} found
          </div>
          <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.55, marginBottom: 12 }}>
            The consultant loop bundles these gap subcaps into an AI-named offering, runs it through
            the G1–G8 gates and routes the suggestion for approval — that path lands with the
            intelligence layer (F8). The grounded basis is already here:
          </div>
          {gaps.length ? (
            <div className="row wrap gap8">
              {gaps.map((s) => (
                <div key={s.id} className="card" style={{ padding: '6px 9px' }}>
                  <div className="row gap6">
                    <PillarDot p={s.pillar} s={6} />
                    <span className="mono" style={{ fontSize: 10.5, color: 'var(--interactive)', fontWeight: 600 }}>
                      {s.id}
                    </span>
                    <span className="muted" style={{ fontSize: 10.5 }}>
                      {s.stories.toLocaleString()} stories
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <span className="muted" style={{ fontSize: 12 }}>
              No high-delivery gaps in the current top set — coverage is healthy.
            </span>
          )}
        </div>
      </div>
    </Page>
  );
}
