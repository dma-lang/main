// Vendor logo — renders the bundled brand mark when we have one (frontend/public/vendor-logos),
// else a deterministic colored-initial avatar. Public marks only (D6); the asset set covers the
// major vendors and every other vendor gracefully falls back to its initial.
import { useState } from 'react';

const LOGOS: Record<string, string> = {
  AWS: 'AWS.png',
  Collibra: 'Collibra.png',
  Databricks: 'Databricks.svg',
  Google: 'Google.svg',
  Microsoft: 'Microsoft.png',
  MuleSoft: 'MuleSoft.png',
  Salesforce: 'Salesforce.png',
  Snowflake: 'Snowflake.svg',
  Tableau: 'Tableau.png',
  Twilio: 'Twilio.png',
  nCino: 'nCino.png',
};

function hashHue(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
  return h;
}

export function PlatVendorLogo({ vendor, size = 32 }: { vendor: string | null; size?: number }) {
  const [failed, setFailed] = useState(false);
  const name = vendor ?? '';
  const file = LOGOS[name];
  if (file && !failed) {
    return (
      <img
        src={`/vendor-logos/${file}`}
        alt={name}
        onError={() => setFailed(true)}
        style={{
          width: size,
          height: size,
          borderRadius: 7,
          objectFit: 'contain',
          background: 'var(--surface-base)',
          border: '1px solid var(--border-subtle)',
          padding: 3,
          flex: 'none',
        }}
      />
    );
  }
  return (
    <div
      title={name}
      style={{
        width: size,
        height: size,
        borderRadius: 7,
        flex: 'none',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: size * 0.42,
        fontWeight: 700,
        color: '#fff',
        background: `hsl(${hashHue(name)}, 42%, 52%)`,
      }}
    >
      {(name || '·').charAt(0).toUpperCase()}
    </div>
  );
}
