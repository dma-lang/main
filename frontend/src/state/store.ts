// Ephemeral UI state (Zustand). Theme/lens/persona mirror control.users.preferences (server home,
// PRD D10) and are persisted via PATCH on change. The SIX propagating filter objects (AppFlow §3:
// pillar, subvertical, claim-label filter, source-tier floor, persona lens, scope context) are
// URL-serialized for deep links — the URL is parsed FIRST on load; missing parameters fall back to
// saved preferences. Theme and cost are header state, not filters, and are never URL-encoded.
import { create } from 'zustand';

export type Pillar = 'all' | 'P1' | 'P2' | 'P3' | 'P4';
export type Theme = 'light' | 'dark';

// The durable source of truth for theme is control.users.preferences (server). But index.html runs
// a pre-paint script that reads localStorage.cia_theme to set data-theme BEFORE React mounts, so we
// also mirror the active theme there — otherwise every reload flashes light before hydration.
function mirrorTheme(theme: Theme): Theme {
  try {
    localStorage.setItem('cia_theme', JSON.stringify(theme));
  } catch {
    /* private mode */
  }
  return theme;
}

type FilterKey = 'p' | 'sv' | 'lens' | 'claim' | 'tier' | 'persona' | 'scope' | 'v';

/** Parse the filter query out of the hash (#/route?p=P1&sv=CL&...) — deep links reproduce the
 * exact filtered view (AppFlow §3.1). */
function urlFilters(): Partial<Record<FilterKey, string>> {
  try {
    const q = window.location.hash.split('?')[1];
    if (!q) return {};
    return Object.fromEntries(new URLSearchParams(q).entries());
  } catch {
    return {};
  }
}

const boot = urlFilters();
const bootHasPersona = boot.persona != null;
const bootHasLens = boot.lens != null;

interface UiState {
  theme: Theme;
  lens: string;
  persona: string;
  adminView: boolean; // client view-preference; the server still enforces real is_admin
  version: string;
  pillar: Pillar;
  sv: string;
  claim: string; // claim-label filter: all | FACT | INFERENCE | HYPOTHESIS | CEILING_ESTIMATE
  tier: string; // source-tier floor: all | T1..T5 (hides evidence below the floor)
  scope: string; // scope context: current subcap id / search term, carried across drilldowns
  setTheme: (t: Theme) => void;
  setLens: (l: string) => void;
  setPersona: (p: string) => void;
  setAdminView: (a: boolean) => void;
  setVersion: (v: string) => void;
  setPillar: (p: Pillar) => void;
  setSv: (s: string) => void;
  setClaim: (c: string) => void;
  setTier: (t: string) => void;
  setScope: (s: string) => void;
  hydrateFromMe: (prefs: Record<string, unknown>, isAdmin: boolean) => void;
}

export const useUi = create<UiState>((set) => ({
  theme: 'light',
  lens: boot.lens ?? 'pillar',
  persona: boot.persona ?? 'Pillar lead',
  adminView: false,
  version: boot.v ?? '',
  pillar: (boot.p as Pillar) ?? 'all',
  sv: boot.sv ?? 'all',
  claim: boot.claim ?? 'all',
  tier: boot.tier ?? 'all',
  scope: boot.scope ?? '',
  setTheme: (theme) => set({ theme: mirrorTheme(theme) }),
  setLens: (lens) => set({ lens }),
  setPersona: (persona) => set({ persona }),
  setAdminView: (adminView) => set({ adminView }),
  setVersion: (version) => set({ version }),
  setPillar: (pillar) => set({ pillar }),
  setSv: (sv) => set({ sv }),
  setClaim: (claim) => set({ claim }),
  setTier: (tier) => set({ tier }),
  setScope: (scope) => set({ scope }),
  hydrateFromMe: (prefs, isAdmin) =>
    set({
      theme: mirrorTheme((prefs.theme as Theme) ?? 'light'),
      // URL wins over saved preferences for the propagating filters (AppFlow §3)
      ...(bootHasLens ? {} : { lens: (prefs.lens as string) ?? 'pillar' }),
      ...(bootHasPersona ? {} : { persona: (prefs.persona as string) ?? 'Pillar lead' }),
      adminView: isAdmin,
    }),
}));

/** Serialize the current filters into the hash query (replaceState — no history spam, no nav).
 * Defaults are omitted so a clean view keeps a clean URL. */
export function syncFiltersToUrl(s: UiState): void {
  try {
    const [path] = window.location.hash.split('?');
    const q = new URLSearchParams();
    if (s.pillar !== 'all') q.set('p', s.pillar);
    if (s.sv !== 'all') q.set('sv', s.sv);
    if (s.lens !== 'pillar') q.set('lens', s.lens);
    if (s.claim !== 'all') q.set('claim', s.claim);
    if (s.tier !== 'all') q.set('tier', s.tier);
    if (s.persona !== 'Pillar lead') q.set('persona', s.persona);
    if (s.scope) q.set('scope', s.scope);
    if (s.version) q.set('v', s.version);
    const qs = q.toString();
    const next = qs ? `${path}?${qs}` : path;
    if (next !== window.location.hash) {
      history.replaceState(null, '', window.location.pathname + next);
    }
  } catch {
    /* non-browser */
  }
}
