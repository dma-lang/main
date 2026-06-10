// Global navigation + the prototype's custom-event contract (cia-reason/peek/loop/commit/toast).
// The Shell listens for these and mounts the matching modal/drawer/toast. Hash-setting drives the
// HashRouter, so `go()` is the single navigation primitive across every surface.

export function go(route: string): void {
  // Navigation CARRIES the current filter query (AppFlow §3.1: arrival never resets context).
  const query = window.location.hash.split('?')[1];
  const target = '#/' + route + (query ? '?' + query : '');
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

export const openLoop = (payload: unknown): void => {
  window.dispatchEvent(new CustomEvent('cia-loop', { detail: payload }));
};

export const openCommit = (payload: unknown): void => {
  window.dispatchEvent(new CustomEvent('cia-commit', { detail: payload }));
};

export const toast = (msg: string): void => {
  window.dispatchEvent(new CustomEvent('cia-toast', { detail: msg }));
};
