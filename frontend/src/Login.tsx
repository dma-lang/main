// Login — the only pre-auth route. Google sign-in restricted to @zennify.com (fails closed). Firebase
// is wired live in Stage 4; in hermetic dev the API auto-authenticates, so this is shown only when
// /api/me is unauthorized.
import { Icon } from './lib/icons';

export function Login({ onRetry }: { onRetry?: () => void }) {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        background: 'var(--surface-sunken)',
      }}
    >
      <div className="card" style={{ width: 380, padding: 32, textAlign: 'center' }}>
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 12,
            background: 'var(--z-teal)',
            margin: '0 auto 16px',
          }}
        />
        <div className="h1" style={{ fontSize: 22 }}>
          Capability Intelligence
        </div>
        <p className="muted" style={{ fontSize: 13, margin: '8px 0 22px' }}>
          Internal workbench for Zennify. Sign in with your @zennify.com account.
        </p>
        <button
          className="btn primary"
          style={{ width: '100%', justifyContent: 'center' }}
          onClick={onRetry}
        >
          <Icon n="google" s={16} /> Sign in with Google
        </button>
        <p className="muted" style={{ fontSize: 11, marginTop: 14 }}>
          Access is restricted and fails closed.
        </p>
      </div>
    </div>
  );
}
