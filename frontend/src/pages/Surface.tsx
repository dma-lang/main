// Generic surface placeholder. The shell renders these for every route; each one is replaced by its
// live, data-wired implementation in Stage 2 (per the per-surface specs in the plan).
import { Empty, Page } from '../components/primitives';
import { NAV } from '../shell/nav';

const TITLES: Record<string, string> = {
  ...Object.fromEntries(NAV.flatMap((g) => g.items.map((it) => [it.r, it.t]))),
  settings: 'Settings',
  'schema-mapping': 'Schema mapping studio',
  onboarding: 'First-run onboarding',
  subcap: 'Capability workbench',
};

export function Surface({ id }: { id: string }) {
  const title = TITLES[id] ?? id;
  return (
    <Page
      eyebrow="Surface"
      title={title}
      intro="The shell, auth, and version-aware API are live. This surface renders real backend data in Stage 2."
    >
      <Empty
        icon="database"
        title="Lights up in this build phase"
        desc="Its foundations (F4 provisioning through F8 gates) and a provisioned catalogue version bring this surface online with live data and the trust envelope."
      />
    </Page>
  );
}
