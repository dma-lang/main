// Auth bootstrap. The SPA asks /api/config (the only public API route) how to sign in:
// dev mode needs no token; live mode lazy-loads the Firebase SDK (dynamic import — hermetic
// users never download it) and attaches a fresh ID token to every API call. The backend
// VERIFIES every token and fails closed — this module is UX, not the security boundary.
import type { User } from 'firebase/auth';

export interface ClientConfig {
  auth_mode: 'dev' | 'live';
  auth_email_domain: string;
  firebase: {
    api_key: string;
    auth_domain: string;
    project_id: string;
    storage_bucket?: string;
    messaging_sender_id?: string;
    app_id?: string;
    measurement_id?: string;
  } | null;
}

let config: ClientConfig | null = null;
let user: User | null = null;
let configPromise: Promise<ClientConfig> | null = null;
let ready: Promise<void> | null = null;

export async function loadConfig(): Promise<ClientConfig> {
  // Failures are NOT cached: a transient /api/config error must stay retryable, otherwise one
  // blip poisons every later getToken()/signIn() for the whole session.
  configPromise ??= fetch('/api/config').then(async (r) => {
    if (!r.ok) throw new Error(`config ${r.status}: ${r.statusText}`);
    config = (await r.json()) as ClientConfig;
    return config;
  });
  try {
    return await configPromise;
  } catch (e) {
    configPromise = null;
    throw e;
  }
}

/** Test seam: subscribes the module's user to an auth-like object and resolves once the
 * initial restore settles. The subscription is PERMANENT — session restore, token refresh
 * and sign-out-in-another-tab all keep flowing into `user`. */
export async function wireAuthState(auth: {
  currentUser: User | null;
  authStateReady?: () => Promise<void>;
}, onAuthStateChanged: (a: typeof auth, cb: (u: User | null) => void) => unknown): Promise<void> {
  let settle: (() => void) | null = null;
  const first = new Promise<void>((resolve) => {
    settle = resolve;
  });
  onAuthStateChanged(auth, (u) => {
    user = u;
    settle?.();
    settle = null;
  });
  // authStateReady (firebase ^10.7) resolves after the initial restore; the first listener
  // emission is the fallback for fakes/tests that don't implement it.
  await (auth.authStateReady ? auth.authStateReady() : first);
  user = auth.currentUser ?? user;
}

async function initFirebase(cfg: ClientConfig): Promise<void> {
  if (!cfg.firebase) return;
  const [{ initializeApp }, { getAuth, onAuthStateChanged }] = await Promise.all([
    import('firebase/app'),
    import('firebase/auth'),
  ]);
  // The full public web config, served by /api/config (hardcoded server-side, env-overridable).
  const app = initializeApp({
    apiKey: cfg.firebase.api_key,
    authDomain: cfg.firebase.auth_domain,
    projectId: cfg.firebase.project_id,
    storageBucket: cfg.firebase.storage_bucket,
    messagingSenderId: cfg.firebase.messaging_sender_id,
    appId: cfg.firebase.app_id,
    measurementId: cfg.firebase.measurement_id,
  });
  if (cfg.firebase.measurement_id) {
    // Analytics is optional + lazy; isSupported() guards non-browser/blocked environments.
    void import('firebase/analytics').then(({ getAnalytics, isSupported }) =>
      isSupported().then((ok) => ok && getAnalytics(app)).catch(() => undefined),
    );
  }
  await wireAuthState(getAuth(app), (a, cb) => onAuthStateChanged(a as ReturnType<typeof getAuth>, cb));
}

/** Idempotent auth init; awaited once by the API layer before the first request.
 * Like loadConfig, a rejected init resets so the Login page's Retry actually retries. */
export function ensureAuth(): Promise<void> {
  ready ??= loadConfig().then((cfg) => (cfg.auth_mode === 'live' ? initFirebase(cfg) : undefined));
  return ready.catch((e) => {
    ready = null;
    throw e;
  });
}

export function isLiveAuth(): boolean {
  return config?.auth_mode === 'live';
}

export function signedIn(): boolean {
  return !isLiveAuth() || user !== null;
}

/** Fresh ID token for the Authorization header (SDK caches/refreshes); null in dev mode. */
export async function getToken(): Promise<string | null> {
  await ensureAuth();
  if (!isLiveAuth()) return null;
  return user ? user.getIdToken() : null;
}

/** Google sign-in popup (live mode). Returns the signed-in email. */
export async function signIn(): Promise<string> {
  const cfg = await loadConfig();
  if (cfg.auth_mode !== 'live') return 'dev@' + cfg.auth_email_domain;
  await ensureAuth();
  const { getAuth, GoogleAuthProvider, signInWithPopup } = await import('firebase/auth');
  const cred = await signInWithPopup(getAuth(), new GoogleAuthProvider());
  user = cred.user; // the permanent listener also fires; this just removes any gap
  return user.email ?? '';
}

export async function signOutUser(): Promise<void> {
  if (!isLiveAuth()) return;
  const { getAuth, signOut } = await import('firebase/auth');
  await signOut(getAuth());
  user = null;
}
