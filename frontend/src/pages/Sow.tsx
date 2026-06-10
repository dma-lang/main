// SOW library (Stage C · Project validation) — every ingested statement of work, read by an
// ontology-tuned model and matched to the subcaps it actually delivered. There is no SOW endpoint yet,
// so the page renders its master-detail chrome — search, status/SV filters and the DLP-redaction
// banner — with an honest Empty state for the roster and matched-subcap region. Ported from the
// prototype SOW.
import { useState } from 'react';

import { Dropdown, Empty, Page } from '../components/primitives';
import { go } from '../lib/events';
import { Icon } from '../lib/icons';

const SOW_SVS = ['all', 'CU', 'BK', 'IC', 'WM'];

export function Sow() {
  const [q, setQ] = useState('');
  const [statusF, setStatusF] = useState('all');
  const [svF, setSvF] = useState('all');

  return (
    <Page
      eyebrow="C · Project validation"
      title="SOW library"
      intro="Every ingested statement of work, read by an ontology-tuned model and matched to the subcaps it actually delivered. Pick a SOW to review its extracted scope, confirm or route each match, and commit the confirmed set."
      actions={
        <div className="row gap8">
          <Dropdown
            value={statusF}
            icon="filter"
            options={[
              { v: 'all', l: 'All status' },
              { v: 'matched', l: 'Matched' },
              { v: 'review', l: 'Needs review' },
              { v: 'ingesting', l: 'Ingesting' },
            ]}
            onChange={setStatusF}
          />
          <Dropdown
            value={svF}
            options={SOW_SVS.map((v) => ({ v, l: v === 'all' ? 'All SV' : v }))}
            onChange={setSvF}
          />
        </div>
      }
    >
      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 18, alignItems: 'start' }}>
        <div style={{ display: 'grid', gap: 8 }}>
          <div className="searchbox" style={{ marginBottom: 2 }}>
            <Icon n="search" s={15} />
            <input
              placeholder="Search client or SOW id…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <div className="card pad">
            <Empty
              icon="file"
              title="No SOWs"
              desc="The statement-of-work roster is not yet wired to a backend endpoint. Once SOW ingestion lands, every ingested SOW lists here with its client, value and match count."
            />
          </div>
        </div>
        <div className="card" style={{ overflow: 'hidden' }}>
          <div className="banner info" style={{ borderRadius: 0 }}>
            <Icon n="shield" s={15} />
            Redaction confirmed · DLP passed before model access — every SOW is DLP-scanned and redacted
            before any model reads it, and matched subcaps are confirmed or routed to a human before they
            are committed to the delivery graph.
          </div>
          <div style={{ padding: 18 }}>
            <Empty
              icon="file"
              title="Select a SOW"
              desc="Pick a statement of work to review its extracted scope and matched subcaps. Matching and commit appear here once SOW ingestion is connected."
              cta="Open the story library"
              onCta={() => go('stories')}
            />
          </div>
        </div>
      </div>
    </Page>
  );
}
