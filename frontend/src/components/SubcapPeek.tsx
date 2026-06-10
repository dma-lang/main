// SubcapPeek — the cia-peek quick-look drawer (prototype SubcapPeek), live-wired: detail,
// enrichment (offering, archetypes) and the latest mapped signal come from the catalogue APIs
// for the ACTIVE version. Unknown ids are an honest designed state, not a blank panel.
import { useSubcap, useSubcapConnections, useSubcapEnrichment } from '../api/queries';
import { go } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';
import { Claim, Drawer, LifeChip, PillarDot, Tier } from './primitives';

export function SubcapPeek({ id, onClose }: { id: string; onClose: () => void }) {
  const version = useUi((s) => s.version);
  const sub = useSubcap(version, id);
  const enrich = useSubcapEnrichment(version, id);
  const conn = useSubcapConnections(version, id);

  const s = sub.data;
  const off = enrich.data?.offerings?.[0] ?? null;
  const archs = [...new Set((enrich.data?.use_cases ?? []).map((u) => u.archetype || ''))]
    .filter(Boolean)
    .slice(0, 5);
  const sig = conn.data?.signals?.[0] ?? null;
  const matCount = enrich.data?.maturity?.filter((m) => m.descriptor).length ?? 0;

  return (
    <Drawer
      open
      onClose={onClose}
      sub="Quick look"
      title={s?.name ?? (sub.isLoading ? 'Loading…' : id)}
      width={420}
      foot={
        s ? (
          <div className="row gap8">
            <button
              className="btn primary sm"
              style={{ flex: 1, justifyContent: 'center' }}
              onClick={() => {
                onClose();
                go('subcap/' + s.id);
              }}
            >
              Open full deep dive <Icon n="arrowR" s={14} />
            </button>
            <button
              className="btn ghost sm"
              onClick={() => {
                onClose();
                go('trace/' + s.id);
              }}
              title="Project-subcap trace"
            >
              <Icon n="branch" s={14} />
            </button>
          </div>
        ) : undefined
      }
    >
      {sub.isError && (
        <div className="banner info" style={{ fontSize: 11.5 }}>
          <Icon n="alert" s={13} />
          {id} is not in the active catalogue version ({version || 'none'}).
        </div>
      )}
      {s && (
        <>
          <div className="row gap8" style={{ marginBottom: 14 }}>
            <span className="mono" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
              {s.id}
            </span>
            <PillarDot p={s.pillar} s={8} />
            <LifeChip life={s.lifecycle_state} />
            {s.tier && <Tier t={s.tier} />}
          </div>
          <div
            style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, marginBottom: 14 }}
          >
            {(
              [
                [(s.completeness ?? 0) + '/8', 'complete'],
                [s.n_use_cases, 'use cases'],
                [s.n_stories, 'stories'],
                ['M' + matCount, 'maturity'],
              ] as [string | number, string][]
            ).map((k, i) => (
              <div key={i} className="card" style={{ padding: '9px 6px', textAlign: 'center' }}>
                <div className="num" style={{ fontSize: 16, fontWeight: 700, color: 'var(--interactive)' }}>
                  {k[0]}
                </div>
                <div className="muted" style={{ fontSize: 9.5 }}>
                  {k[1]}
                </div>
              </div>
            ))}
          </div>
          <div className="eyebrow" style={{ marginBottom: 6 }}>
            In one line
          </div>
          <p
            style={{
              fontSize: 12.5,
              color: 'var(--text-secondary)',
              lineHeight: 1.55,
              margin: '0 0 16px',
            }}
          >
            {s.description || 'No description on this subcap yet.'}
          </p>
          <div className="eyebrow" style={{ marginBottom: 7 }}>
            Latest signal
          </div>
          {sig ? (
            <div className="card pad" style={{ padding: '10px 12px', marginBottom: 14 }}>
              <div className="row gap6" style={{ marginBottom: 5 }}>
                <Claim label={sig.label} />
                <span className="muted" style={{ fontSize: 10, marginLeft: 'auto' }}>
                  {sig.source} · {sig.date}
                </span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                {sig.title}
              </div>
            </div>
          ) : (
            <div className="banner info" style={{ marginBottom: 14, fontSize: 11.5 }}>
              <Icon n="news" s={13} />
              No public or vendor signal currently maps to this subcap.
            </div>
          )}
          {off && (
            <div
              className="card pad"
              style={{ padding: '10px 12px', marginBottom: 14, borderColor: 'var(--border-medium)' }}
            >
              <div className="row gap8">
                <Icon n="package" s={15} style={{ color: 'var(--interactive)' }} />
                <b style={{ fontSize: 12.5 }}>{off.name}</b>
                <span className="chip teal" style={{ marginLeft: 'auto' }}>
                  in offering
                </span>
              </div>
            </div>
          )}
          {archs.length > 0 && (
            <div>
              <div className="eyebrow" style={{ marginBottom: 7 }}>
                Use-case archetypes
              </div>
              <div className="row wrap gap6">
                {archs.map((a) => (
                  <span key={a} className="chip blue">
                    {a}
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </Drawer>
  );
}
