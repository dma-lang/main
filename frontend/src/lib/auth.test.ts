// The two sign-in regressions that made the login button "dead": a config fetch whose failure
// was cached forever (poisoned promise), and an auth listener that unsubscribed itself after the
// first emission (so a session restored a beat later was never seen). Each test re-imports the
// module fresh — auth.ts keeps module-level state by design.
import { beforeEach, describe, expect, it, vi } from 'vitest';

type AuthModule = typeof import('./auth');

async function freshAuth(): Promise<AuthModule> {
  vi.resetModules();
  return import('./auth');
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe('loadConfig', () => {
  it('rejects on a non-OK response and RETRIES on the next call (no poisoned cache)', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503, statusText: 'Service Unavailable' })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ auth_mode: 'dev', auth_email_domain: 'zennify.com', firebase: null }),
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
      json: async () => ({ auth_mode: 'dev', auth_email_domain: 'zennify.com', firebase: null }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const auth = await freshAuth();

    await auth.loadConfig();
    await auth.loadConfig();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('wireAuthState (live mode)', () => {
  it('keeps listening after the initial null emission — a late session restore is seen', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          auth_mode: 'live',
          auth_email_domain: 'zennify.com',
          firebase: { api_key: 'k', auth_domain: 'd', project_id: 'p' },
        }),
      }),
    );
    const auth = await freshAuth();
    await auth.loadConfig(); // live mode: signedIn() now depends on the module's user

    type Cb = (u: unknown) => void;
    let listener: Cb = () => undefined;
    await auth.wireAuthState({ currentUser: null } as never, (_a, cb) => {
      listener = cb as Cb;
      cb(null); // initial emission: restore not finished yet
    });
    expect(auth.signedIn()).toBe(false);

    listener({ uid: 'u1', email: 'a@zennify.com' }); // Firebase restores the session LATER
    expect(auth.signedIn()).toBe(true); // the permanent listener saw it
  });

  it('prefers authStateReady and reports currentUser after the initial restore', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          auth_mode: 'live',
          auth_email_domain: 'zennify.com',
          firebase: { api_key: 'k', auth_domain: 'd', project_id: 'p' },
        }),
      }),
    );
    const auth = await freshAuth();
    await auth.loadConfig();

    const user = { uid: 'u2', email: 'b@zennify.com' };
    const ready = vi.fn().mockResolvedValue(undefined);
    await auth.wireAuthState({ currentUser: user, authStateReady: ready } as never, () => undefined);
    expect(ready).toHaveBeenCalled();
    expect(auth.signedIn()).toBe(true); // restored session visible even with no emission yet
  });
});
