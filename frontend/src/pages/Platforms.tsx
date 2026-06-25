// Platform catalog (B1) — the L3 technology platforms the catalogue is built on, grouped by vendor.
// Aligned to the prototype: a vendor card grid (logo · platforms/subcaps · delivery bar) and a
// vendor×pillar heatmap whose cells DRILL to the subcaps riding on that vendor in that pillar; each
// platform expands to its addressed subcaps + its highest-delivered use-case archetypes. Wired to
// GET /api/catalogue/{v}/{platforms,vendors,vendors/{vendor}/cell} + /platforms/{l3_id}.
import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';

import { usePlatform, usePlatforms, useVendorCell, useVendors } from '../api/queries';
import { PlatVendorLogo } from '../components/PlatVendorLogo';
import { Dropdown, Page, PillarDot } from '../components/primitives';
import { go, openPeek } from '../lib/events';
import { heatBg } from '../lib/helpers';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

const PILLARS = ['P1', 'P2', 'P3', 'P4'] as const;

function ExpandedPlatform({ version, l3_id }: { version: string; l3_id: string }) {
  const detail = usePlatform(version, l3_id);
  const subs = detail.data?.subcaps ?? [];
  const ucs = detail.data?.use_cases ?? [];
  const ucMax = Math.max(1, ...ucs.map((u) => u.stories));
  return (
    <>
      <div className="row wrap gap6">
        {subs.slice(0, 12).map((s) => (
          <button
            key={s.id}
            className="card hov"
            style={{ padding: '5px 9px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}
            onClick={() => go('subcap/' + s.id)}
          >
            <PillarDot p={s.pillar} s={6} />
            <span className="mono" style={{ fontSize: 10.5, color: 'var(--interactive)', fontWeight: 600 }}>
              {s.id}
            </span>
            <span
              className="muted"
              style={{ fontSize: 10.5, maxWidth: 130, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
            >
              {s.name}
            </span>
          </button>
        ))}
      </div>
      {ucs.length > 0 && (
        <>
          <div className="eyebrow" style={{ margin: '16px 0 8px' }}>
            Highest-delivered use cases here
          </div>
          <div style={{ display: 'grid', gap: 6 }}>
            {ucs.map((u) => (
              <button
                key={u.archetype}
                className="card hov"
                onClick={() => go('use-cases', { archetype: u.archetype })}
                style={{ padding: '7px 11px', cursor: 'pointer', textAlign: 'left' }}
              >
                <div className="between" style={{ marginBottom: 5 }}>
                  <span className="chip soft" style={{ fontSize: 9.5 }}>
                    {u.archetype}
                  </span>
                  <span className="num" style={{ fontSize: 12, fontWeight: 700, color: 'var(--interactive)' }}>
                    {u.stories.toLocaleString()}
                    <span className="muted" style={{ fontSize: 9, fontWeight: 400 }}> stories</span>
                  </span>
                </div>
                <div className="bartrack">
                  <div className="barfill" style={{ width: `${(u.stories / ucMax) * 100}%`, background: 'var(--interactive)' }} />
                </div>
              </button>
            ))}
          </div>
        </>
      )}
    </>
  );
}

export function Platforms() {
  const params = useParams<{ id?: string }>();
  const focusId = params.id ?? null;
  const version = useUi((s) => s.version);
  const platformsQ = usePlatforms(version);
  const vendorsQ = useVendors(version);
  const platforms = useMemo(() => platformsQ.data ?? [], [platformsQ.data]);
  const vendors = useMemo(() => vendorsQ.data ?? [], [vendorsQ.data]);

  const focusVendor = useMemo(
    () => platforms.find((p) => p.l3_id === focusId)?.vendor ?? 'all',
    [platforms, focusId],
  );
  const [vendorF, setVendorF] = useState('all');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [cell, setCell] = useState<{ vendor: string; pillar: string } | null>(null);
  const cellQ = useVendorCell(version, cell?.vendor ?? null, cell?.pillar ?? null);

  useEffect(() => {
    if (focusId) {
      setExpanded(focusId);
      setVendorF(focusVendor ?? 'all');
    }
  }, [focusId, focusVendor]);

  const top = vendors.slice(0, 8);
  const heatMax = Math.max(1, ...top.flatMap((v) => [v.p1, v.p2, v.p3, v.p4]));
  const cardVendors = vendors.slice(0, 7);
  const storyMax = Math.max(1, ...cardVendors.map((v) => v.stories));
  const shownPlats = platforms.filter((p) => vendorF === 'all' || p.vendor === vendorF).slice(0, 40);

  const vendorOpts = [
    { v: 'all', l: 'All vendors' },
    ...vendors.map((v) => ({ v: v.vendor, l: `${v.vendor} (${v.plats})` })),
  ];

  const pickVendor = (name: string) => {
    setVendorF((cur) => (cur === name ? 'all' : name));
    setCell(null);
  };

  return (
    <Page
      eyebrow="B · Catalogue tools"
      title="Platform catalog"
      intro={
        <>
          The {platforms.length} L3 technology platforms the catalogue is built on, grouped by vendor
          — each linking back to the subcaps and delivery stories that ride on it. Pick a vendor, click
          a heatmap cell to drill its subcaps, or expand a platform.
        </>
      }
      actions={<Dropdown value={vendorF} icon="filter" options={vendorOpts} onChange={setVendorF} />}
    >
      {/* vendor card grid — quick visual filter over the top vendors by delivery */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
          gap: 10,
          marginBottom: 18,
        }}
      >
        <button
          className="card hov"
          onClick={() => pickVendor('all')}
          style={{
            padding: '12px 14px',
            cursor: 'pointer',
            textAlign: 'left',
            borderColor: vendorF === 'all' ? 'var(--interactive)' : 'var(--border-subtle)',
            background: vendorF === 'all' ? 'var(--surface-overlay)' : 'var(--surface-base)',
          }}
        >
          <div className="row gap10">
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 7,
                background: 'var(--surface-overlay)',
                color: 'var(--interactive)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flex: 'none',
              }}
            >
              <Icon n="grid" s={16} />
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600 }}>All vendors</div>
              <div className="muted" style={{ fontSize: 11 }}>
                {platforms.length} platforms
              </div>
            </div>
          </div>
        </button>
        {cardVendors.map((v) => {
          const on = vendorF === v.vendor;
          return (
            <button
              key={v.vendor}
              className="card hov"
              onClick={() => pickVendor(v.vendor)}
              style={{
                padding: '12px 14px',
                cursor: 'pointer',
                textAlign: 'left',
                borderColor: on ? 'var(--interactive)' : 'var(--border-subtle)',
                background: on ? 'var(--surface-overlay)' : 'var(--surface-base)',
              }}
            >
              <div className="row gap10" style={{ marginBottom: 9 }}>
                <PlatVendorLogo vendor={v.vendor} size={32} />
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{ fontSize: 13, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {v.vendor}
                  </div>
                  <div className="muted" style={{ fontSize: 10.5 }}>
                    {v.plats} platforms · {v.subcap_count} subcaps
                  </div>
                </div>
              </div>
              <div className="bartrack" title={`${v.stories.toLocaleString()} delivered stories`}>
                <div className="barfill" style={{ width: `${(v.stories / storyMax) * 100}%`, background: 'var(--z-teal)' }} />
              </div>
            </button>
          );
        })}
      </div>

      <div className="card pad" style={{ marginBottom: 18 }}>
        <div className="between" style={{ marginBottom: 4 }}>
          <div className="h2">Vendor × pillar coverage</div>
          <span className="chip soft">subcaps addressed</span>
        </div>
        <div className="muted" style={{ fontSize: 12, marginBottom: 14 }}>
          Cell intensity = subcaps in that pillar that ride on the vendor's L3 platforms. Click a cell
          to drill its subcaps.
        </div>
        <table style={{ borderCollapse: 'separate', borderSpacing: '3px', width: '100%' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', fontSize: 10.5, color: 'var(--z-slate)', fontWeight: 700, width: 120 }}>
                VENDOR
              </th>
              {PILLARS.map((p) => (
                <th key={p} style={{ padding: '0 0 6px' }}>
                  <div className="row gap6" style={{ justifyContent: 'center' }}>
                    <PillarDot p={p} s={7} />
                    <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-secondary)' }}>{p}</span>
                  </div>
                </th>
              ))}
              <th style={{ fontSize: 10.5, color: 'var(--z-slate)', fontWeight: 700, width: 80, textAlign: 'right' }}>
                SUBCAPS
              </th>
            </tr>
          </thead>
          <tbody>
            {top.map((v) => (
              <tr key={v.vendor}>
                <td
                  style={{ fontSize: 12.5, fontWeight: 600, paddingRight: 8, cursor: 'pointer' }}
                  onClick={() => pickVendor(v.vendor)}
                >
                  {v.vendor}
                </td>
                {([v.p1, v.p2, v.p3, v.p4] as number[]).map((val, i) => {
                  const sel = cell?.vendor === v.vendor && cell?.pillar === PILLARS[i];
                  return (
                    <td key={i} style={{ padding: 0 }}>
                      <div
                        className="heatcell"
                        title={`${v.vendor} · ${PILLARS[i]} · ${val} subcaps — click to drill`}
                        onClick={() => {
                          setCell({ vendor: v.vendor, pillar: PILLARS[i] });
                          setVendorF(v.vendor);
                        }}
                        style={{
                          height: 30,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          cursor: 'pointer',
                          background: heatBg(val / heatMax),
                          color: val / heatMax > 0.5 ? '#fff' : 'var(--z-dark)',
                          fontSize: 11,
                          fontWeight: 700,
                          outline: sel ? '2px solid var(--interactive)' : 'none',
                          outlineOffset: -2,
                        }}
                      >
                        {val || ''}
                      </div>
                    </td>
                  );
                })}
                <td style={{ textAlign: 'right', fontWeight: 700, fontSize: 13 }} className="num">
                  {v.subcap_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {cell && (
          <div className="fade-in" style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border-subtle)' }}>
            <div className="between" style={{ marginBottom: 10 }}>
              <div className="row gap8">
                <span className="chip teal">
                  {cell.vendor} · {cell.pillar}
                </span>
                <span className="muted" style={{ fontSize: 12 }}>
                  top subcaps on {cell.vendor}'s platforms
                </span>
              </div>
              <button className="modal-x" onClick={() => setCell(null)} aria-label="close">
                <Icon n="x" s={14} />
              </button>
            </div>
            {cellQ.isLoading ? (
              <div className="muted" style={{ fontSize: 12 }}>
                Loading…
              </div>
            ) : (cellQ.data ?? []).length === 0 ? (
              <div className="muted" style={{ fontSize: 12 }}>
                No subcaps for this cell.
              </div>
            ) : (
              <div className="row wrap gap6">
                {(cellQ.data ?? []).map((s) => (
                  <button
                    key={s.id}
                    className="card hov"
                    style={{ padding: '5px 9px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}
                    onClick={() => openPeek(s.id)}
                    onDoubleClick={() => go('subcap/' + s.id)}
                  >
                    <PillarDot p={s.pillar} s={6} />
                    <span className="mono" style={{ fontSize: 10.5, color: 'var(--interactive)', fontWeight: 600 }}>
                      {s.id}
                    </span>
                    <span className="muted" style={{ fontSize: 10.5, maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {s.name}
                    </span>
                    <span className="num" style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-primary)' }}>
                      {s.stories.toLocaleString()}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="h2" style={{ marginBottom: 12 }}>
        {vendorF === 'all' ? 'All platforms' : vendorF + ' platforms'}{' '}
        <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>
          · {shownPlats.length}
        </span>
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        {shownPlats.map((p) => {
          const open = expanded === p.l3_id;
          return (
            <div key={p.l3_id} className="card">
              <div className="between" style={{ padding: '13px 16px', cursor: 'pointer' }} onClick={() => setExpanded(open ? null : p.l3_id)}>
                <div className="row gap10" style={{ minWidth: 0 }}>
                  <PlatVendorLogo vendor={p.vendor} size={32} />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 13.5, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {p.name}
                    </div>
                    <div className="row gap8">
                      <span className="mono muted" style={{ fontSize: 10.5 }}>
                        {p.l3_id}
                      </span>
                      {p.vendor && (
                        <span className="chip soft" style={{ fontSize: 9.5, padding: '1px 6px' }}>
                          {p.vendor}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="row gap16" style={{ flex: 'none' }}>
                  <div style={{ textAlign: 'right' }}>
                    <div className="num" style={{ fontSize: 15, fontWeight: 700 }}>
                      {p.subcap_count}
                    </div>
                    <div className="muted" style={{ fontSize: 9.5 }}>
                      subcaps
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="num" style={{ fontSize: 15, fontWeight: 700 }}>
                      {p.stories.toLocaleString()}
                    </div>
                    <div className="muted" style={{ fontSize: 9.5 }}>
                      stories
                    </div>
                  </div>
                  <Icon n={open ? 'chevD' : 'chevR'} s={16} style={{ color: 'var(--text-tertiary)' }} />
                </div>
              </div>
              {open && (
                <div className="fade-in" style={{ padding: '0 16px 16px', borderTop: '1px solid var(--border-subtle)' }}>
                  <div className="row gap16" style={{ margin: '12px 0' }}>
                    {PILLARS.map((pk, i) => (
                      <div key={pk} className="row gap6" style={{ fontSize: 11 }}>
                        <PillarDot p={pk} s={7} />
                        <span className="muted">{[p.p1, p.p2, p.p3, p.p4][i]}</span>
                      </div>
                    ))}
                    <span className="grow" />
                    {p.vendor && (
                      <button className="linkbtn" onClick={() => go('vendors/' + encodeURIComponent(p.vendor ?? ''))}>
                        {p.vendor} intelligence <Icon n="arrowR" s={12} />
                      </button>
                    )}
                  </div>
                  <div className="eyebrow" style={{ marginBottom: 8 }}>
                    Addressing subcaps · {p.subcap_count} (top 12)
                  </div>
                  <ExpandedPlatform version={version} l3_id={p.l3_id} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Page>
  );
}
