// Schema mapping (Header surface · admin) — admin control over how each catalogue version maps to the
// canonical model: confirm auto-mapped fields, add custom fields and relations, cascade compatible
// relations across versions, and carry the canonical story mappings forward. The field-mapping and
// carry-forward data have no backend endpoint yet, so the page renders its admin-gated chrome with
// honest Empty/banner states for those regions. Ported from the prototype SchemaMapping.
import { useState } from 'react';

import { Empty, Page, Seg } from '../components/primitives';
import { go, toast } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

export function SchemaMapping() {
  const isAdmin = useUi((s) => s.adminView);
  const [ver, setVer] = useState('v5');

  return (
    <Page
      eyebrow="Header surface · admin"
      title="Schema mapping"
      intro="Give an admin control over how each catalogue version maps to the canonical model — confirm auto-mapped fields, add custom fields and relations, cascade compatible relations across versions, and carry the canonical story mappings forward."
      actions={
        <Seg
          options={[
            { v: 'v5', l: 'v5 workbook' },
            { v: 'v7', l: 'v7 workbook' },
          ]}
          value={ver}
          onChange={setVer}
        />
      }
    >
      {!isAdmin ? (
        <div className="banner warn">
          <Icon n="lock" s={15} />
          Schema mapping is admin-only. Enable the is_admin toggle to confirm field mappings, add custom
          fields and provision a catalogue version.
        </div>
      ) : (
        <>
          <div className="banner info" style={{ marginBottom: 16 }}>
            <Icon n="branch" s={15} />
            <b style={{ marginRight: 4 }}>Detected:</b> the proposed field mapping for the {ver} workbook
            populates here once the mapping pipeline is connected. Confirm fields, add custom fields, then
            apply.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 18, alignItems: 'start' }}>
            <div>
              <div className="card pad" style={{ marginBottom: 16 }}>
                <Empty
                  icon="layers"
                  title="Field mapping pipeline pending"
                  desc="The auto-mapped source-to-canonical field table — with per-field confidence and confirm / review status — is not yet wired to a backend endpoint. Once mapping lands, confirm each field and add custom fields here."
                />
              </div>
              <div className="card pad">
                <div className="h3" style={{ marginBottom: 6 }}>
                  Apply mapping
                </div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 14, lineHeight: 1.5 }}>
                  Applying writes this mapping to the backend schema and provisions the persistent
                  relational database for the {ver} catalogue. Stored per version; re-runnable.
                </div>
                <div className="row gap8">
                  <button className="btn ghost sm" onClick={() => toast('Previewing tables…')}>
                    Preview tables
                  </button>
                  <button
                    className="btn primary sm"
                    onClick={() => toast(ver + ' provisioning is admin-confirmed before it runs')}
                  >
                    Apply &amp; provision
                    <Icon n="arrowR" s={14} />
                  </button>
                </div>
              </div>
            </div>
            <div style={{ display: 'grid', gap: 14 }}>
              <div className="card pad">
                <div className="between" style={{ marginBottom: 8 }}>
                  <div className="h3">
                    Backend relations ·{' '}
                    <span className="mono" style={{ fontWeight: 500, fontSize: 10.5 }}>
                      control.relation_def
                    </span>
                  </div>
                </div>
                <Empty
                  icon="branch"
                  title="No relations yet"
                  desc="Canonical join definitions appear here once the mapping is applied. Edit them in the onboarding studio."
                  cta="Open onboarding studio"
                  onCta={() => go('onboarding')}
                />
              </div>
              <div className="card pad" style={{ borderColor: 'var(--border-medium)' }}>
                <div className="h3" style={{ marginBottom: 8 }}>
                  Story carry-forward
                </div>
                <div className="muted" style={{ fontSize: 11.5, marginBottom: 12, lineHeight: 1.5 }}>
                  Canonical Jira mappings carried forward and similarity-confirmed before they are
                  maintained. Crosswalk first, embeddings to confirm, borderline to review.
                </div>
                <Empty
                  icon="route"
                  title="Carry-forward pipeline pending"
                  desc="Story carry-forward counts — stories, subcaps mapped, confirmed and review — and the borderline review queue appear here once the mapping is applied for this version."
                />
              </div>
            </div>
          </div>
        </>
      )}
    </Page>
  );
}
