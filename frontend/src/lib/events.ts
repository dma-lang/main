// Global navigation + the prototype's custom-event contract (cia-reason/peek/loop/commit/toast).
// The Shell listens for these and mounts the matching modal/drawer/toast. Hash-setting drives the
// HashRouter, so `go()` is the single navigation primitive across every surface.

export function go(route: string, params?: Record<string, string>): void {
  // Navigation CARRIES the current filter query (AppFlow §3.1: arrival never resets context);
  // `params` overlays route-specific keys (e.g. { tab: 'delivery' } to land on a deep-dive tab).
  const q = new URLSearchParams(window.location.hash.split('?')[1] ?? '');
  q.delete('tab'); // route-local (one destination's tab must not leak into the next page)
  for (const [k, v] of Object.entries(params ?? {})) q.set(k, v);
  const qs = q.toString();
  const target = '#/' + route + (qs ? '?' + qs : '');
  if (window.location.hash !== target) {
    window.location.hash = target;
  } else {
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  }
}

export const openReasoning = (id: unknown): void => {
  window.dispatchEvent(new CustomEvent('cia-reason', { detail: id }));
};

export const openPeek = (id: string): void => {
  window.dispatchEvent(new CustomEvent('cia-peek', { detail: id }));
};

// Open the productized-offering drilldown drawer (matched subcaps + capabilities) for an offering id.
export const openOffering = (id: string): void => {
  window.dispatchEvent(new CustomEvent('cia-offering', { detail: id }));
};

export const openLoop = (payload: unknown): void => {
  window.dispatchEvent(new CustomEvent('cia-loop', { detail: payload }));
};

export const openCommit = (payload: unknown): void => {
  window.dispatchEvent(new CustomEvent('cia-commit', { detail: payload }));
};

export const toast = (msg: string): void => {
  window.dispatchEvent(new CustomEvent('cia-toast', { detail: msg }));
};
