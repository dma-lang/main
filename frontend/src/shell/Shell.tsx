// App shell layout — brand cell + header + 9-group sidebar + routed main + toasts. Ported from the
// prototype shell.jsx. Theme is applied to <html data-theme>; the 5 custom events (cia-reason/
// peek/loop/commit/toast) each mount their modal/drawer/toast here — the prototype's contract.
import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';

import { CommitModal, type CommitPayload } from '../components/CommitModal';
import { ConsultantLoop, type LoopPayload } from '../components/ConsultantLoop';
import { ReasoningModal } from '../components/ReasoningModal';
import { OfferingDrawer } from '../components/OfferingDrawer';
import { SubcapPeek } from '../components/SubcapPeek';
import { Icon } from '../lib/icons';
import { syncFiltersToUrl, useUi } from '../state/store';
import { Header } from './Header';
import { Sidebar } from './Sidebar';

interface Toast {
  id: number;
  msg: string;
}

function useCiaEvent<T>(name: string, on: (detail: T) => void): void {
  useEffect(() => {
    const h = (e: Event) => on((e as CustomEvent<T>).detail);
    window.addEventListener(name, h);
    return () => window.removeEventListener(name, h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);
}

export function Shell() {
  const theme = useUi((s) => s.theme);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem('cia_collapsed') === 'true';
    } catch {
      return false;
    }
  });
  const [navOpen, setNavOpen] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [reasoningId, setReasoningId] = useState<string | null>(null);
  const [peekId, setPeekId] = useState<string | null>(null);
  const [offeringId, setOfferingId] = useState<string | null>(null);
  const [loopCtx, setLoopCtx] = useState<LoopPayload | null>(null);
  const [commitCtx, setCommitCtx] = useState<CommitPayload | null>(null);
  const loc = useLocation();

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  useEffect(() => {
    try {
      localStorage.setItem('cia_collapsed', String(collapsed));
    } catch {
      /* private mode */
    }
  }, [collapsed]);

  // The prototype scrolls .main to the top on every route change.
  useEffect(() => {
    document.querySelector('.main')?.scrollTo(0, 0);
  }, [loc.pathname]);

  // The six filter objects serialize into the URL on every change — a deep link reproduces the
  // exact filtered view, and navigation carries the filters (AppFlow §3.1).
  const ui = useUi();
  useEffect(() => {
    syncFiltersToUrl(ui);
  }, [ui, loc.pathname]);

  // cia-reason carries a reasoning chain_id (string); the modal is the universal audit window.
  useCiaEvent<unknown>('cia-reason', (d) => {
    if (typeof d === 'string' && d) setReasoningId(d);
  });
  useCiaEvent<unknown>('cia-peek', (d) => {
    if (typeof d === 'string' && d) setPeekId(d);
  });
  useCiaEvent<unknown>('cia-offering', (d) => {
    if (typeof d === 'string' && d) setOfferingId(d);
  });
  useCiaEvent<unknown>('cia-loop', (d) => {
    if (d && typeof d === 'object') setLoopCtx(d as LoopPayload);
  });
  useCiaEvent<unknown>('cia-commit', (d) => {
    if (d && typeof d === 'object') setCommitCtx(d as CommitPayload);
  });
  useCiaEvent<unknown>('cia-toast', (d) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg: String(d ?? '') }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 2600);
  });

  return (
    <div className={'app' + (collapsed ? ' collapsed' : '') + (navOpen ? ' navopen' : '')}>
      <div className="navscrim" onClick={() => setNavOpen(false)} />
      <div className="brandcell">
        <img className="brandmark" src="/brand/logo-mark-teal.png" alt="Zennify" />
        <span className="brandname">Capability Intelligence</span>
        <button
          className="hamburger"
          title="Menu"
          onClick={() => {
            if (window.innerWidth <= 1024) setNavOpen((o) => !o);
            else setCollapsed((c) => !c);
          }}
        >
          <Icon n="grid" s={16} />
        </button>
      </div>
      <Header />
      <Sidebar onNav={() => setNavOpen(false)} />
      <div className="main">
        <Outlet />
      </div>
      <div className="toasts" role="status" aria-live="polite" aria-atomic="true">
        {toasts.map((t) => (
          <div key={t.id} className="toast">
            <span className="tdot" />
            {t.msg}
          </div>
        ))}
      </div>
      {reasoningId && <ReasoningModal chainId={reasoningId} onClose={() => setReasoningId(null)} />}
      {peekId && <SubcapPeek id={peekId} onClose={() => setPeekId(null)} />}
      {offeringId && (
        <OfferingDrawer version={ui.version} id={offeringId} onClose={() => setOfferingId(null)} />
      )}
      {loopCtx && <ConsultantLoop payload={loopCtx} onClose={() => setLoopCtx(null)} />}
      {commitCtx && <CommitModal payload={commitCtx} onClose={() => setCommitCtx(null)} />}
    </div>
  );
}
