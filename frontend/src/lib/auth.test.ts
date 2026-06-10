// Sign-in regressions guarded here: a config fetch whose failure was cached forever (poisoned
// promise), and token-session handling for plain Google Identity Services (the ID token IS the
// session — an expired or garbled token must never pass). Each test re-imports the module fresh —
// auth.ts keeps module-level state by design. Node test env: sessionStorage is stubbed.
import { beforeEach, describe, expect, it, vi } from 'vitest';

type AuthModule = typeof import('./auth');

async function freshAuth(): Promise<AuthModule> {
  vi.resetModules();
  return import('./auth');
}

function fakeJwt(exp: number): string {
  const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url');
  return `${b64({ alg: 'RS256' })}.${b64({ exp, email: 'a@zennify.com' })}.sig`;
}

// Minimal in-memory sessionStorage for the node test environment; persists across freshAuth()
// (module reloads) within a test, like the real one persists across page refreshes.
function stubStorage(): void {
  const m = new Map<string, string>();
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
    clear: () => m.clear(),
  });
}

beforeEach(() => {
  vi.unstubAllGlobals();
  stubStorage();
});

describe('loadConfig', () => {
  it('rejects on a non-OK response and RETRIES on the next call (no poisoned cache)', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503, statusText: 'Service Unavailable' })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          auth_mode: 'dev',
          auth_email_domain: 'zennify.com',
          google_client_id: null,
        }),
      });
    vi.stubGlobal('fetch', fetchMock);
    const auth = await freshAuth();

    await expect(auth.loadConfig()).rejects.toThrow('config 503');
    const cfg = await auth.loadConfig(); // a second call must actually refetch
    expect(cfg.auth_mode).toBe('dev');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('caches a successful config (single fetch for repeat callers)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        auth_mode: 'dev',
        auth_email_domain: 'zennify.com',
        google_client_id: null,
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const auth = await freshAuth();

    await auth.loadConfig();
    await auth.loadConfig();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('token session (live mode)', () => {
  const liveFetch = () =>
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        auth_mode: 'live',
        auth_email_domain: 'zennify.com',
        google_client_id: 'abc.apps.googleusercontent.com',
      }),
    });

  it('a stored unexpired ID token IS the session; getToken returns it', async () => {
    vi.stubGlobal('fetch', liveFetch());
    const auth = await freshAuth();
    await auth.loadConfig();
    expect(auth.signedIn()).toBe(false);

    const jwt = fakeJwt(Math.floor(Date.now() / 1000) + 3600);
    auth.storeToken(jwt);
    expect(auth.signedIn()).toBe(true);
    expect(await auth.getToken()).toBe(jwt);
  });

  it('an EXPIRED token never passes (signed out -> the Gate shows Login again)', async () => {
    vi.stubGlobal('fetch', liveFetch());
    const auth = await freshAuth();
    await auth.loadConfig();
    auth.storeToken(fakeJwt(Math.floor(Date.now() / 1000) - 10));
    expect(auth.signedIn()).toBe(false);
    expect(await auth.getToken()).toBeNull();
  });

  it('a garbled token parses to exp 0 and never passes', async () => {
    vi.stubGlobal('fetch', liveFetch());
    const auth = await freshAuth();
    await auth.loadConfig();
    expect(auth.tokenExp('not-a-jwt')).toBe(0);
    auth.storeToken('not-a-jwt');
    expect(auth.signedIn()).toBe(false);
  });

  it('the session survives a module reload via sessionStorage (page refresh)', async () => {
    vi.stubGlobal('fetch', liveFetch());
    const first = await freshAuth();
    await first.loadConfig();
    first.storeToken(fakeJwt(Math.floor(Date.now() / 1000) + 3600));

    const second = await freshAuth(); // simulates a refresh: fresh module, same sessionStorage
    await second.loadConfig();
    expect(second.signedIn()).toBe(true);
  });
});
