// Vendor logo — renders the bundled brand mark when the vendor name matches a known brand (the
// catalogue labels some vendors compositely, e.g. "Salesforce / MuleSoft" or "AWS Bedrock", so we
// match on brand TOKENS rather than an exact key), else a deterministic colored-initial avatar.
// Sub-brands (MuleSoft, Tableau) are matched BEFORE their umbrella (Salesforce) so a composite name
// resolves to the more specific mark. Public marks only (D6); assets in public/vendor-logos.
import { useState } from 'react';

const BRANDS: { file: string; aliases: string[] }[] = [
  // specific sub-brands first so "Salesforce / MuleSoft" → MuleSoft, not the Salesforce umbrella
  { file: 'MuleSoft.png', aliases: ['mulesoft', 'mule'] },
  { file: 'Tableau.png', aliases: ['tableau'] },
  { file: 'nCino.png', aliases: ['ncino'] },
  { file: 'Databricks.svg', aliases: ['databricks'] },
  { file: 'Snowflake.svg', aliases: ['snowflake'] },
  { file: 'Collibra.png', aliases: ['collibra'] },
  { file: 'Twilio.png', aliases: ['twilio'] },
  { file: 'Salesforce.png', aliases: ['salesforce'] },
  { file: 'Microsoft.png', aliases: ['microsoft', 'azure'] },
  { file: 'Google.svg', aliases: ['google'] },
  { file: 'AWS.png', aliases: ['aws', 'amazon'] },
];

function logoFor(vendor: string): string | null {
  const v = vendor.toLowerCase();
  for (const b of BRANDS) if (b.aliases.some((a) => v.includes(a))) return b.file;
  return null;
}

function hashHue(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
  return h;
}

export function PlatVendorLogo({ vendor, size = 32 }: { vendor: string | null; size?: number }) {
  const [failed, setFailed] = useState(false);
  const name = vendor ?? '';
  const file = logoFor(name);
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
