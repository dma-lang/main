import { APP_VERSION } from './version';

// Stage 0 placeholder shell. The real shell (header + 9-group sidebar A–I, version toggle,
// the 6 propagating filters, trust components, and the 30 surfaces) is built in Stage 1+ (F10),
// matching docs/specs/prototype/Capability_Intelligence_Agent.html.
export default function App() {
  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        padding: 'var(--sp-8)',
      }}
    >
      <div style={{ maxWidth: 560 }}>
        <h1 style={{ color: 'var(--text-primary)' }}>Capability Intelligence Agent</h1>
        <p style={{ color: 'var(--text-secondary)' }}>
          Scaffold (Stage&nbsp;0). Surfaces are built in reviewable increments — see CLAUDE.md and the
          approved plan. App version {APP_VERSION}.
        </p>
      </div>
    </main>
  );
}
