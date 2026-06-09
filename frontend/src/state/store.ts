// Ephemeral UI state (Zustand). Theme/lens/persona mirror control.users.preferences (server home,
// PRD D10) and are persisted via PATCH on change; pillar/sv/version are filter state. The prototype's
// localStorage cia_* keys map here, but the durable source of truth is the backend.
import { create } from 'zustand';

export type Pillar = 'all' | 'P1' | 'P2' | 'P3' | 'P4';
export type Theme = 'light' | 'dark';

interface UiState {
  theme: Theme;
  lens: string;
  persona: string;
  adminView: boolean; // client view-preference; the server still enforces real is_admin
  version: string;
  pillar: Pillar;
  sv: string;
  setTheme: (t: Theme) => void;
  setLens: (l: string) => void;
  setPersona: (p: string) => void;
  setAdminView: (a: boolean) => void;
  setVersion: (v: string) => void;
  setPillar: (p: Pillar) => void;
  setSv: (s: string) => void;
  hydrateFromMe: (prefs: Record<string, unknown>, isAdmin: boolean) => void;
}

export const useUi = create<UiState>((set) => ({
  theme: 'light',
  lens: 'pillar',
  persona: 'Pillar lead',
  adminView: false,
  version: '',
  pillar: 'all',
  sv: 'all',
  setTheme: (theme) => set({ theme }),
  setLens: (lens) => set({ lens }),
  setPersona: (persona) => set({ persona }),
  setAdminView: (adminView) => set({ adminView }),
  setVersion: (version) => set({ version }),
  setPillar: (pillar) => set({ pillar }),
  setSv: (sv) => set({ sv }),
  hydrateFromMe: (prefs, isAdmin) =>
    set({
      theme: (prefs.theme as Theme) ?? 'light',
      lens: (prefs.lens as string) ?? 'pillar',
      persona: (prefs.persona as string) ?? 'Pillar lead',
      adminView: isAdmin,
    }),
}));
