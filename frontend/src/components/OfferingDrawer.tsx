// OfferingDrawer — the productized-offering drilldown. Opened by `cia-offering` (openOffering) from
// any offering chip (Workbench Overview, Lifecycle, KG node). Shows the offering's GTM capabilities
// + the subcaps the semantic matcher mapped to it BY MEANING: each scored, with its matching
// capability (the trust basis) and delivered-story count, peekable.
import { useOfferingDetail } from '../api/queries';
import { openPeek } from '../lib/events';
import { PILLAR_COLORS } from '../lib/helpers';
import { Icon } from '../lib/icons';

import { Bar, Drawer, Empty, PillarDot } from './primitives';

export function OfferingDrawer({
  version,
  id,
  onClose,
}: {
  version: string;
  id: string;
  onClose: () => void;
}) {
  const q = useOfferingDetail(version, id);
  const d = q.data;
  const pmax = d ? Math.max(1, ...Object.values(d.pillars)) : 1;
  return (
    <Drawer
      open
      onClose={onClose}
      sub={d?.family === 'data_product' ? 'Data product' : 'Productized offering'}
      title={d?.name ?? id}
      width={500}
    >
      {q.isLoading && (
        <div className="muted" style={{ fontSize: 12 }}>
          Loading offering…
        </div>
      )}
      {d && (
        <>
          {d.summary && (
            <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.55, marginBottom: 12 }}>
              {d.summary}
            </div>
          )}
          {d.platforms.length > 0 && (
            <div className="row wrap gap6" style={{ marginBottom: 14 }}>
              {d.platforms.map((p) => (
                <span key={p} className="chip soft" style={{ fontSize: 10.5 }}>
                  <Icon n="database" s={11} />
                  {p}
                </span>
              ))}
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 14 }}>
            <div className="card" style={{ padding: '10px 12px', textAlign: 'center' }}>
              <div
                className="num"
                style={{ fontSize: 20, fontWeight: 700, color: 'var(--interactive)' }}
              >
                {d.n_subcaps}
              </div>
              <div className="muted" style={{ fontSize: 10 }}>
                matched subcaps
              </div>
            </div>
            <div className="card" style={{ padding: '10px 12px', textAlign: 'center' }}>
              <div className="num" style={{ fontSize: 20, fontWeight: 700 }}>
                {d.stories.toLocaleString()}
              </div>
              <div className="muted" style={{ fontSize: 10 }}>
                delivered stories
              </div>
            </div>
          </div>

          {Object.values(d.pillars).some((v) => v > 0) && (
            <div style={{ marginBottom: 14 }}>
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                Pillar spread
              </div>
              {(['P1', 'P2', 'P3', 'P4'] as const).map((pk) =>
                d.pillars[pk] ? (
                  <div key={pk} className="row gap8" style={{ marginBottom: 6 }}>
                    <span className="row gap6" style={{ minWidth: 40 }}>
                      <PillarDot p={pk} s={7} />
                      <span className="muted" style={{ fontSize: 11 }}>
                        {pk}
                      </span>
                    </span>
                    <div style={{ flex: 1 }}>
                      <Bar v={d.pillars[pk]} max={pmax} color={PILLAR_COLORS[pk]} />
                    </div>
                    <b className="num" style={{ fontSize: 11 }}>
                      {d.pillars[pk]}
                    </b>
                  </div>
                ) : null,
              )}
            </div>
          )}

          {d.capabilities.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                Core capabilities
              </div>
              <div style={{ display: 'grid', gap: 4 }}>
                {d.capabilities.map((c, i) => (
                  <div
                    key={i}
                    className="muted"
                    style={{ fontSize: 11.5, lineHeight: 1.4, paddingLeft: 14, position: 'relative' }}
                  >
                    <span style={{ position: 'absolute', left: 0, color: 'var(--z-teal)' }}>·</span>
                    {c.length > 140 ? c.slice(0, 139) + '…' : c}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Matched subcaps · semantic score
          </div>
          {d.subcaps.length === 0 ? (
            <Empty
              icon="layers"
              title="No matches yet"
              desc="Run the offerings matcher (admin) once embeddings exist on this version."
            />
          ) : (
            <div style={{ display: 'grid', gap: 6 }}>
              {d.subcaps.map((s) => (
                <div
                  key={s.id}
                  className="card hov"
                  style={{ padding: '9px 12px', cursor: 'pointer' }}
                  onClick={() => openPeek(s.id)}
                  title={s.capability ? 'matched on: ' + s.capability : undefined}
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
                      <span className="chip soft" style={{ fontSize: 9.5 }} title="semantic match score">
                        {s.score.toFixed(2)}
                      </span>
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
        </>
      )}
    </Drawer>
  );
}
