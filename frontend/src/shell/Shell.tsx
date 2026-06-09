// App shell layout — brand cell + header + 9-group sidebar + routed main + toasts. Ported from the
// prototype shell.jsx. Theme is applied to <html data-theme>; cia-toast drives the toast stack.
import { useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';

import { ReasoningModal } from '../components/ReasoningModal';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';
import { Header } from './Header';
import { Sidebar } from './Sidebar';

interface Toast {
  id: number;
  msg: string;
}

export function Shell() {
  const theme = useUi((s) => s.theme);
  const [collapsed, setCollapsed] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [reasoningId, setReasoningId] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // cia-reason carries a reasoning chain_id (string); the modal is the universal audit window.
  useEffect(() => {
    const h = (e: Event) => {
      const detail = (e as CustomEvent<unknown>).detail;
      if (typeof detail === 'string' && detail) setReasoningId(detail);
    };
    window.addEventListener('cia-reason', h);
    return () => window.removeEventListener('cia-reason', h);
  }, []);

  useEffect(() => {
    const h = (e: Event) => {
      const id = Date.now() + Math.random();
      const msg = String((e as CustomEvent<unknown>).detail ?? '');
      setToasts((t) => [...t, { id, msg }]);
      window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 2600);
    };
    window.addEventListener('cia-toast', h);
    return () => window.removeEventListener('cia-toast', h);
  }, []);

  return (
    <div className={'app' + (collapsed ? ' collapsed' : '') + (navOpen ? ' navopen' : '')}>
      <div className="navscrim" onClick={() => setNavOpen(false)} />
      <div className="brandcell">
        <span
          className="brandmark"
          style={{
            width: 22,
            height: 22,
            borderRadius: 6,
            background: 'var(--z-teal)',
            display: 'inline-block',
          }}
        />
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
      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className="toast">
            <span className="tdot" />
            {t.msg}
          </div>
        ))}
      </div>
      {reasoningId && (
        <ReasoningModal chainId={reasoningId} onClose={() => setReasoningId(null)} />
      )}
    </div>
  );
}
