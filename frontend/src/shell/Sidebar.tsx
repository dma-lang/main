// Sidebar — the 9-group nav (A-I), ported from shell.jsx. Admin items hide unless the admin view is on;
// active item is derived from the current route (item.match || first path segment).
import { useLocation } from 'react-router-dom';

import { go } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';
import { NAV, type NavItem } from './nav';

export function Sidebar({ onNav }: { onNav?: () => void }) {
  const adminView = useUi((s) => s.adminView);
  const loc = useLocation();
  const page = loc.pathname.replace(/^\//, '').split('/')[0] || 'mission-control';
  const active = (it: NavItem) => (it.match ?? it.r.split('/')[0]) === page;

  return (
    <nav className="sidebar">
      {NAV.map((grp) => {
        const items = grp.items.filter((it) => !it.admin || adminView);
        if (!items.length) return null;
        return (
          <div className="navgroup" key={grp.g}>
            <div className="navgrouph">
              <span>{grp.g}</span>
            </div>
            {items.map((it) => (
              <div
                key={it.r}
                className={'navitem' + (active(it) ? ' on' : '')}
                onClick={() => {
                  go(it.r);
                  onNav?.();
                }}
                title={it.t}
              >
                <Icon n={it.i} s={17} cls="nic" />
                <span>{it.t}</span>
                {it.admin && <Icon n="lock" s={12} cls="adminlock" />}
              </div>
            ))}
          </div>
        );
      })}
    </nav>
  );
}
