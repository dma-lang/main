// Project-subcap trace (Stage C · Project validation) — every event that ever touched a subcap (SOW
// matches, delivered stories, benchmark recomputes, news, vendor moves, suggestions) entity-resolved
// onto one timeline. Deep-linkable per subcap; reachable without an id (shows a picker). There is no
// timeline endpoint yet, so the page renders the subcap header, KPI strip and swimlane chrome with an
// honest Empty state for events. Ported from the prototype Trace.
import { useState } from 'react';
import { useParams } from 'react-router-dom';

import { useSubcaps } from '../api/queries';
import { Dropdown, Empty, Page, PillarDot } from '../components/primitives';
import { go, openPeek, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const TRACE_LANES: [string, string, string][] = [
  ['sow', 'SOW', 'var(--z-blue)'],
  ['story', 'Story', 'var(--interactive)'],
  ['news', 'News', 'var(--z-orange)'],
  ['vendor', 'Vendor', 'var(--z-slate)'],
  ['suggestion', 'Suggestion', 'var(--p4)'],
  ['benchmark', 'Benchmark', 'var(--z-teal-light)'],
];

export function Trace() {
  const ui = useUi();
  const { id } = useParams<{ id: string }>();
  const subs = useSubcaps(ui.version);
  const [pick, setPick] = useState('');

  const options = (subs.data ?? []).slice(0, 60).map((x) => ({
    v: x.id,
    l: x.id + ' · ' + x.name.slice(0, 22),
  }));
  const activeId = id || pick;
  const s = (subs.data ?? []).find((x) => x.id === activeId);

  return (
    <Page
      eyebrow="C · Project validation"
      title="Project-subcap trace"
      intro={
        <>
          Pick any subcap to see <b>every event that ever touched it</b> — SOW matches, delivered
          stories, benchmark recomputes, news, vendor moves and suggestions — entity-resolved onto one
          timeline. Click an event to read what it means and drill to its source.
        </>
      }
      actions={
        <div className="row gap8">
          <Dropdown
            value={activeId}
            icon="branch"
            options={options}
            onChange={(v) => (id ? go('trace/' + v) : setPick(v))}
          />
          <button className="btn ghost sm" onClick={() => toast('Exporting trace as CSV…')}>
            <Icon n="file" s={14} />
            Export CSV
          </button>
        </div>
      }
    >
      {!activeId ? (
        <div className="card pad">
          <Empty
            icon="branch"
            title="Pick a subcap to trace"
            desc="Choose a subcap above to assemble its cross-signal timeline. Every SOW match, delivered story, benchmark recompute, news item, vendor move and suggestion that touched it is entity-resolved onto one lane view."
            cta="Browse the catalogue"
            onCta={() => go('explorer')}
          />
        </div>
      ) : (
        <>
          <div className="card pad" style={{ marginBottom: 16 }}>
            <div className="between">
              <div className="row gap10">
                {s && <PillarDot p={s.pillar} />}
                <div>
                  <div className="h2">{s ? s.name : activeId}</div>
                  <div className="row gap8 mt8">
                    <span className="mono muted" style={{ fontSize: 11 }}>
                      {activeId}
                    </span>
                    {s && (
                      <span className="muted" style={{ fontSize: 11 }}>
                        {s.cat_name}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="row gap8">
                <button className="btn ghost xs" onClick={() => openPeek(activeId)}>
                  <Icon n="eye" s={13} />
                  Peek
                </button>
                <button className="btn ghost xs" onClick={() => go('subcap/' + activeId)}>
                  Deep dive
                </button>
              </div>
            </div>
            <div
              style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginTop: 16 }}
            >
              {[
                ['—', 'events'],
                ['— / 6', 'signal sources touched'],
                ['—', 'last activity'],
                ['—', 'avg confidence'],
              ].map((k, i) => (
                <div key={i} className="card" style={{ padding: '11px 14px' }}>
                  <div className="num" style={{ fontSize: 19, fontWeight: 700 }}>
                    {k[0]}
                  </div>
                  <div className="muted" style={{ fontSize: 10.5 }}>
                    {k[1]}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div
            style={{ display: 'grid', gridTemplateColumns: '1fr 330px', gap: 18, alignItems: 'start' }}
          >
            <div className="card pad">
              <div className="between" style={{ marginBottom: 4 }}>
                <div className="h3">Signal timeline</div>
                <span className="muted" style={{ fontSize: 11 }}>
                  6 quarters · click a dot
                </span>
              </div>
              <div className="muted" style={{ fontSize: 11.5, marginBottom: 10 }}>
                Each lane is a signal source; the bar above each quarter shows total activity that
                quarter.
              </div>
              <div className="row wrap gap8" style={{ marginBottom: 14 }}>
                {TRACE_LANES.map((l) => (
                  <span key={l[0]} className="row gap6" style={{ fontSize: 11 }}>
                    <span
                      className="pilldot"
                      style={{ borderRadius: '50%', width: 8, height: 8, background: l[2] }}
                    />
                    {l[1]}
                  </span>
                ))}
              </div>
              <Empty
                icon="route"
                title="Timeline pipeline pending"
                desc="The cross-signal event timeline is not yet wired to a backend endpoint. Once the trace service lands, every SOW, story, news, vendor, suggestion and benchmark event for this subcap renders on its lane here."
              />
            </div>
            <div className="card pad">
              <div className="h3" style={{ marginBottom: 8 }}>
                Event detail
              </div>
              <div className="muted" style={{ fontSize: 12 }}>
                Select an event on the timeline to read what it means, see its claim and confidence, and
                drill to its source.
              </div>
            </div>
          </div>
        </>
      )}
    </Page>
  );
}
