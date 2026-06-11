// Auth bootstrap — plain Google Identity Services (NO Firebase, no passwords handled or stored).
// The SPA asks /api/config (the only public API route) how to sign in: dev mode needs no token;
// live mode loads Google's GSI script and renders the OFFICIAL Sign-in-with-Google button, whose
// callback hands us a Google ID token (a 1h JWT). Every API call carries it; the backend VERIFIES
// signature + audience + @zennify.com and fails closed — this module is UX, not the boundary.

export interface ClientConfig {
  auth_mode: 'dev' | 'live';
  auth_email_domain: string;
  auth_configured?: boolean; // live: is the OAuth client id+secret set on the service?
  login_url?: string; // where to start the OAuth Authorization-Code redirect (/api/auth/login)
  db?: 'ok' | 'down' | 'not_configured'; // server-reported, so the Login can pre-flight the blocker
}

const TOKEN_KEY = 'cia_id_token';

let config: ClientConfig | null = null;
let configPromise: Promise<ClientConfig> | null = null;
let token: string | null = null;

export async function loadConfig(): Promise<ClientConfig> {
  // Failures are NOT cached: a transient /api/config error must stay retryable, otherwise one
  // blip poisons every later getToken()/sign-in for the whole session.
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

/** JWT exp (seconds since epoch), or 0 when unparseable — an unparseable token never passes. */
export function tokenExp(jwt: string): number {
  try {
    const payload = JSON.parse(atob(jwt.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return typeof payload.exp === 'number' ? payload.exp : 0;
  } catch {
    return 0;
  }
}

function freshToken(): string | null {
  if (token === null) {
    try {
      token = sessionStorage.getItem(TOKEN_KEY);
    } catch {
      /* private mode */
    }
  }
  // 30s skew so a token never expires mid-request; expiry means sign in again (Google ID tokens
  // are 1h JWTs with no refresh — the Gate shows the Login and one click re-issues).
  if (token && tokenExp(token) * 1000 > Date.now() + 30_000) return token;
  return null;
}

export function storeToken(jwt: string): void {
  token = jwt;
  try {
    sessionStorage.setItem(TOKEN_KEY, jwt);
  } catch {
    /* private mode */
  }
}

/** Idempotent auth init; awaited by the API layer before the first request. With GIS there is no
 * SDK session to restore — the stored ID token (if unexpired) IS the session. */
export function ensureAuth(): Promise<void> {
  return loadConfig().then(() => undefined);
}

export function isLiveAuth(): boolean {
  return config?.auth_mode === 'live';
}

export function signedIn(): boolean {
  return !isLiveAuth() || freshToken() !== null;
}

/** The bearer for the Authorization header; null in dev mode or when expired (→ sign in again). */
export async function getToken(): Promise<string | null> {
  await ensureAuth();
  if (!isLiveAuth()) return null;
  return freshToken();
}

/** Sign out: the session is an HttpOnly cookie set by the OAuth callback, so JS cannot clear it —
 * hand off to the server route, which deletes the cookie and returns to the login page. */
export function signOutUser(): void {
  token = null;
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode */
  }
  if (isLiveAuth()) window.location.href = '/api/auth/logout';
}
