// Shared UI primitives — ported verbatim from the prototype (ui.jsx), using the same class names so
// the extracted stylesheet styles them identically.
import { Fragment, type ReactNode, useEffect, useRef, useState } from 'react';

import { go } from '../lib/events';
import { clamp, LIFE_COLORS, LIFE_LABEL, PILLAR_COLORS } from '../lib/helpers';
import { Icon, type IconName } from '../lib/icons';

export function Claim({ label }: { label: string }) {
  const k = (label || '').toLowerCase();
  const c =
    k === 'fact' ? 'fact' : k === 'inference' ? 'inference' : k === 'hypothesis' ? 'hypothesis' : 'ceiling';
  return <span className={'claim ' + c}>{label}</span>;
}

export const Tier = ({ t }: { t: string }) => <span className="tierchip">{t}</span>;

export function Mag({ m }: { m: string }) {
  return <span className={'mag ' + (m || '').toLowerCase()}>{m}</span>;
}

export function PillarDot({ p, s = 8 }: { p: string; s?: number }) {
  return <span className="pilldot" style={{ background: PILLAR_COLORS[p], width: s, height: s }} />;
}

export function Bar({ v, max = 8, color }: { v: number; max?: number; color?: string }) {
  const pct = clamp((v / max) * 100, 0, 100);
  return (
    <div className="bartrack">
      <div className="barfill" style={{ width: pct + '%', background: color ?? 'var(--z-teal)' }} />
    </div>
  );
}

export function LifeChip({ life }: { life: string }) {
  const c = LIFE_COLORS[life];
  return (
    <span className="chip" style={{ background: 'transparent', color: c, border: '1px solid ' + c }}>
      <span className="pilldot" style={{ width: 6, height: 6, borderRadius: '50%', background: c }} />
      {LIFE_LABEL[life]}
    </span>
  );
}

export function Switch({ on, onChange }: { on: boolean; onChange: () => void }) {
  return (
    <button
      className={'switch' + (on ? ' on' : '')}
      onClick={onChange}
      role="switch"
      aria-checked={on}
    >
      <span className="knob" />
    </button>
  );
}

export function Seg({
  options,
  value,
  onChange,
}: {
  options: { v: string; l: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="seg">
      {options.map((o) => (
        <button key={o.v} className={value === o.v ? 'on' : ''} onClick={() => onChange(o.v)}>
          {o.l}
        </button>
      ))}
    </div>
  );
}

export function Empty({
  icon = 'database',
  title,
  desc,
  cta,
  onCta,
}: {
  icon?: IconName;
  title: string;
  desc?: ReactNode;
  cta?: string;
  onCta?: () => void;
}) {
  return (
    <div className="empty">
      <div
        style={{
          width: 54,
          height: 54,
          borderRadius: 14,
          background: 'var(--surface-overlay)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--z-teal)',
        }}
      >
        <Icon n={icon} s={26} />
      </div>
      <div className="et">{title}</div>
      <div className="ed">{desc}</div>
      {cta && (
        <button className="btn primary sm" onClick={onCta}>
          {cta}
        </button>
      )}
    </div>
  );
}

interface Crumb {
  t: string;
  to?: string;
}

export function Page({
  crumbs,
  title,
  intro,
  actions,
  width = 'wide',
  children,
  eyebrow,
}: {
  crumbs?: Crumb[];
  title?: string;
  intro?: ReactNode;
  actions?: ReactNode;
  width?: string;
  children?: ReactNode;
  eyebrow?: string;
}) {
  return (
    <>
      <div className="titlebar">
        {crumbs && (
          <div className="crumbs">
            {crumbs.map((c, i) => (
              <Fragment key={i}>
                {i > 0 && (
                  <span className="sep">
                    <Icon n="chevR" s={11} />
                  </span>
                )}
                {c.to ? <a onClick={() => c.to && go(c.to)}>{c.t}</a> : <span>{c.t}</span>}
              </Fragment>
            ))}
          </div>
        )}
        <span className="grow" />
        {actions}
      </div>
      <div className={'content ' + width + ' fade-in'}>
        {(eyebrow || title) && (
          <div style={{ marginBottom: intro ? 6 : 18 }}>
            {eyebrow && (
              <div className="eyebrow" style={{ marginBottom: 6 }}>
                {eyebrow}
              </div>
            )}
            {title && <div className="h1">{title}</div>}
          </div>
        )}
        {intro && <div className="pageintro">{intro}</div>}
        {children}
      </div>
    </>
  );
}

export function Dropdown({
  label,
  value,
  options,
  onChange,
  icon,
}: {
  label?: string;
  value: string;
  options: { v: string; l: string }[];
  onChange: (v: string) => void;
  icon?: IconName;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);
  const cur = options.find((o) => o.v === value);
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button className="hdrsel" onClick={() => setOpen((o) => !o)}>
        {icon && <Icon n={icon} s={14} />}
        {cur ? cur.l : label}
        <span className="car">
          <Icon n="chevD" s={11} />
        </span>
      </button>
      {open && (
        <div
          className="card"
          style={{
            position: 'absolute',
            top: '110%',
            left: 0,
            zIndex: 60,
            minWidth: 160,
            boxShadow: 'var(--el-2)',
            padding: 5,
            maxHeight: 300,
            overflowY: 'auto',
          }}
        >
          {options.map((o) => (
            <div
              key={o.v}
              className="navitem"
              style={{ fontWeight: o.v === value ? 600 : 500 }}
              onClick={() => {
                onChange(o.v);
                setOpen(false);
              }}
            >
              {o.l}
              {o.v === value && (
                <Icon n="check" s={14} style={{ marginLeft: 'auto', color: 'var(--interactive)' }} />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
