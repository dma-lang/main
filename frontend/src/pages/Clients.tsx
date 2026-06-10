// Client journey atlas (Stage F · Lifecycle & competition) — a unified, entity-resolved view of each
// client and the signed-JSON packet handed to the DMA team. There is no clients endpoint yet, so the
// page renders its master-detail chrome with an honest Empty state for the roster and a banner for the
// detail pane rather than fabricated client names or DMA scores. Ported from the prototype Clients.
import { Empty, Page } from '../components/primitives';
import { go } from '../lib/events';
import { Icon } from '../lib/icons';

export function Clients() {
  return (
    <Page
      eyebrow="F · Lifecycle & competition"
      title="Client journey atlas"
      intro="A unified, entity-resolved view of each client, and the packet you hand to the DMA team — exported as validated, signed JSON."
    >
      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 18, alignItems: 'start' }}>
        <div className="card pad">
          <Empty
            icon="building"
            title="No clients yet"
            desc="The entity-resolved client roster — subcaps touched, vendor stack and last DMA score — is not yet wired to a backend endpoint."
          />
        </div>
        <div className="banner info">
          <Icon n="building" s={15} />
          Once the client-journey pipeline lands, pick a client to see its KPIs, vendor stack, engagement
          timeline and export its signed DMA packet. Until then, browse delivered work in the{' '}
          <a onClick={() => go('sow')} style={{ cursor: 'pointer' }}>
            SOW library
          </a>
          .
        </div>
      </div>
    </Page>
  );
}
