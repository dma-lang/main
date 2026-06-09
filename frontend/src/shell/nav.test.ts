import { describe, expect, it } from 'vitest';

import { NAV } from './nav';

describe('nav', () => {
  it('has the 9 sidebar groups A–I from the prototype', () => {
    expect(NAV).toHaveLength(9);
    expect(NAV[0].g).toContain('A · Explore');
    expect(NAV[NAV.length - 1].g).toContain('I · Sandbox');
  });

  it('exposes the read surfaces that are live in Stage 1', () => {
    const ids = NAV.flatMap((g) => g.items.map((it) => it.r));
    for (const id of ['mission-control', 'explorer', 'versions', 'diff']) {
      expect(ids).toContain(id);
    }
  });
});
