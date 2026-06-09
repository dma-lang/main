// Colour maps + small helpers — verbatim from the prototype (ui.jsx).

export const PILLAR_COLORS: Record<string, string> = {
  P1: 'var(--p1)',
  P2: 'var(--p2)',
  P3: 'var(--p3)',
  P4: 'var(--p4)',
};

export const PILLAR_SOFT: Record<string, string> = {
  P1: 'var(--p1-soft)',
  P2: 'var(--p2-soft)',
  P3: 'var(--p3-soft)',
  P4: 'var(--p4-soft)',
};

export const LIFE_COLORS: Record<string, string> = {
  emerging: '#27bbaf',
  rising: '#62d7b8',
  stable: '#3d81f6',
  declining: '#ffb066',
  fading: '#fe9732',
  dead: '#8094c0',
};

export const LIFE_LABEL: Record<string, string> = {
  emerging: 'emerging',
  rising: 'rising',
  stable: 'stable',
  declining: 'declining',
  fading: 'fading',
  dead: 'dead',
};

export const pillarOf = (id: string): string => (id ? id.slice(0, 2) : '');

export const clamp = (n: number, a: number, b: number): number => Math.max(a, Math.min(b, n));
