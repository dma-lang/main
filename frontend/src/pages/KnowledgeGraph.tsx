// Knowledge graph (Stage B · Catalogue tools · admin) — reveal the structural relationships the flat
// catalogue hides: deterministic (Layer A) edges plus AI-proposed (Layer B) edges gated in the Change
// flags inbox. The relationship graph has no backend endpoint yet, so the page renders its real chrome —
// admin gate, centre-subcap picker (live /api/catalogue subcaps), layer toggle and legend — with an
// honest Empty state in the graph body. Ported from the prototype KnowledgeGraph.
import { useState } from 'react';

import { useSubcaps } from '../api/queries';
import { Dropdown, Empty, Page, Seg } from '../components/primitives';
import { go } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const KIND_COLOR: Record<string, string> = {
  subcap: 'var(--p4)',
  offering: 'var(--interactive)',
  platform: 'var(--z-blue)',
  theme: 'var(--z-slate)',
};

export function KnowledgeGraph() {
  const ui = useUi();
  const isAdmin = useUi((s) => s.adminView);
  const subs = useSubcaps(ui.version);
  const [layer, setLayer] = useState('B');
  const [center, setCenter] = useState('');

  const options = (subs.data ?? []).slice(0, 40).map((x) => ({
    v: x.id,
    l: x.id + ' · ' + x.name.slice(0, 20),
  }));
  const cur = center || options[0]?.v || '';

  return (
    <Page
      eyebrow="B · Catalogue tools · admin"
      title="Knowledge graph"
      intro="Reveal the structural relationships the flat catalogue hides. Solid edges are deterministic (Layer A); dashed orange edges are AI-proposed (semantic-similarity / shared-feature), gated in the Change flags inbox before commit."
      actions={
        <div className="row gap8">
          <Dropdown
            value={cur}
            icon="branch"
            options={options}
            onChange={(v) => setCenter(v)}
          />
          <Seg
            options={[
              { v: 'A', l: 'Deterministic' },
              { v: 'B', l: '+ AI' },
              { v: 'full', l: 'Full' },
            ]}
            value={layer}
            onChange={setLayer}
          />
        </div>
      }
    >
      {!isAdmin ? (
        <div className="banner warn">
          <Icon n="lock" s={15} />
          The knowledge graph is admin-only. Enable the is_admin toggle to explore catalogue
          relationships.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 18, alignItems: 'start' }}>
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ padding: 18 }}>
              <Empty
                icon="graph"
                title="Graph pipeline pending"
                desc="The relationship graph — deterministic Layer A edges plus AI-proposed Layer B edges — is not yet wired to a backend endpoint. Once the knowledge-graph service lands, the structural map of platforms, offerings, themes and neighbour subcaps renders here."
                cta="Open change flags inbox"
                onCta={() => go('change-flags')}
              />
            </div>
            <div
              className="row gap16"
              style={{ padding: '10px 16px', borderTop: '1px solid var(--border-subtle)', fontSize: 11 }}
            >
              {Object.entries(KIND_COLOR).map(([k, c]) => (
                <span key={k} className="row gap6">
                  <span
                    className="pilldot"
                    style={{ borderRadius: '50%', width: 10, height: 10, background: c }}
                  />
                  {k}
                </span>
              ))}
              <span className="grow" />
              <span className="row gap6">
                <span style={{ width: 16, height: 0, borderTop: '2px dashed var(--z-orange)' }} />
                AI-proposed
              </span>
            </div>
          </div>
          <div style={{ display: 'grid', gap: 14 }}>
            <div className="card pad">
              <div className="h3" style={{ marginBottom: 8 }}>
                Centre: {cur || '—'}
              </div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
                Edge counts, AI-proposed edges and neighbour subcaps populate once the graph pipeline is
                connected.
              </div>
              <button
                className="btn ghost sm"
                style={{ width: '100%', justifyContent: 'center' }}
                onClick={() => go('subcap/' + cur)}
              >
                Open subcap
                <Icon n="arrowR" s={13} />
              </button>
            </div>
            <div className="card pad">
              <div className="h3" style={{ marginBottom: 8 }}>
                Community & centrality
              </div>
              <div className="muted" style={{ fontSize: 12 }}>
                Degree centrality, community and betweenness are derived from the graph and appear with the
                live edge data.
              </div>
            </div>
            <div className="card pad" style={{ borderColor: 'var(--border-medium)' }}>
              <div className="h3" style={{ marginBottom: 8 }}>
                Pending edges
              </div>
              <div className="muted" style={{ fontSize: 12 }}>
                AI-proposed edges queue here for review before commit. Resolve them in the Change flags
                inbox.
              </div>
              <button
                className="btn primary sm"
                style={{ width: '100%', justifyContent: 'center', marginTop: 10 }}
                onClick={() => go('change-flags')}
              >
                Review in change flags
                <Icon n="arrowR" s={14} />
              </button>
            </div>
          </div>
        </div>
      )}
    </Page>
  );
}
