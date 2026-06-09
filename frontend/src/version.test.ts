import { describe, expect, it } from 'vitest';
import { APP_VERSION } from './version';

describe('app version', () => {
  it('is a valid SemVer', () => {
    expect(APP_VERSION).toMatch(/^\d+\.\d+\.\d+(?:[-+].+)?$/);
  });
});
