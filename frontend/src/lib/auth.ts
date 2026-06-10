// Auth bootstrap — plain Google Identity Services (NO Firebase, no passwords handled or stored).
// The SPA asks /api/config (the only public API route) how to sign in: dev mode needs no token;
// live mode loads Google's GSI script and renders the OFFICIAL Sign-in-with-Google button, whose
// callback hands us a Google ID token (a 1h JWT). Every API call carries it; the backend VERIFIES
// signature + audience + @zennify.com and fails closed — this module is UX, not the boundary.

export interface ClientConfig {
  auth_mode: 'dev' | 'live';
  auth_email_domain: string;
  google_client_id: string | null;
}

interface GisIdApi {
  initialize(opts: {
    client_id: string;
    callback: (r: { credential: string }) => void;
    hd?: string;
    auto_select?: boolean;
    use_fedcm_for_prompt?: boolean;
  }): void;
  renderButton(parent: HTMLElement, opts: Record<string, unknown>): void;
  disableAutoSelect(): void;
}

declare global {
  interface Window {
    google?: { accounts: { id: GisIdApi } };
  }
}

const TOKEN_KEY = 'cia_id_token';
const GSI_SRC = 'https://accounts.google.com/gsi/client';

let config: ClientConfig | null = null;
let configPromise: Promise<ClientConfig> | null = null;
let gsiPromise: Promise<GisIdApi> | null = null;
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

/** Load Google's GSI script once. Rejects (retryably) if it cannot load — surfaced on the Login. */
function loadGsi(): Promise<GisIdApi> {
  gsiPromise ??= new Promise<GisIdApi>((resolve, reject) => {
    if (window.google?.accounts?.id) {
      resolve(window.google.accounts.id);
      return;
    }
    const s = document.createElement('script');
    s.src = GSI_SRC;
    s.async = true;
    s.defer = true;
    const timer = window.setTimeout(() => {
      reject(new Error('Google sign-in script timed out'));
    }, 10_000);
    s.onload = () => {
      window.clearTimeout(timer);
      const api = window.google?.accounts?.id;
      if (api) resolve(api);
      else reject(new Error('Google sign-in script loaded without the accounts API'));
    };
    s.onerror = () => {
      window.clearTimeout(timer);
      reject(new Error('Could not load the Google sign-in script — check the network'));
    };
    document.head.appendChild(s);
  });
  return gsiPromise.catch((e) => {
    gsiPromise = null; // retryable
    throw e;
  });
}

/** Pre-load config + the GSI script so the Login renders Google's button immediately. */
export async function prewarmAuth(): Promise<void> {
  const cfg = await loadConfig();
  if (cfg.auth_mode === 'live') await loadGsi();
}

/** Render the official Sign-in-with-Google button. Google owns the click → no popup-blocked
 * failure mode; the callback receives the ID token. `hd` pre-filters to the Zennify domain in
 * the picker (the SERVER still enforces it — fails closed on any other account). */
export async function renderGoogleButton(
  parent: HTMLElement,
  onCredential: () => void,
): Promise<void> {
  const cfg = await loadConfig();
  if (cfg.auth_mode !== 'live') return;
  if (!cfg.google_client_id) {
    throw new Error(
      'Sign-in is not configured — set GOOGLE_CLIENT_ID on the service (an OAuth web client id ' +
        'from GCP Console → APIs & Services → Credentials).',
    );
  }
  const gsi = await loadGsi();
  gsi.initialize({
    client_id: cfg.google_client_id,
    hd: cfg.auth_email_domain,
    auto_select: false,
    use_fedcm_for_prompt: true,
    callback: (r) => {
      storeToken(r.credential);
      onCredential();
    },
  });
  parent.replaceChildren();
  gsi.renderButton(parent, {
    theme: 'outline',
    size: 'large',
    text: 'continue_with',
    shape: 'rectangular',
    width: 320,
    logo_alignment: 'left',
  });
  // GIS fails SILENTLY when this origin is not on the OAuth client's allow-list (it only logs
  // [GSI_LOGGER] to the console and renders nothing) — turn that blank space into an honest,
  // actionable state. The iframe lands fast when allowed; poll briefly before declaring failure.
  for (let waited = 0; waited < 4000; waited += 200) {
    if (parent.childElementCount > 0) return;
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(
    `Google did not render the sign-in button — usually this origin (${location.origin}) is ` +
      "missing from the OAuth client's Authorized JavaScript origins (GCP Console → APIs & " +
      'Services → Credentials). Add it, wait a few minutes, then retry.',
  );
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

export function signOutUser(): void {
  token = null;
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode */
  }
  window.google?.accounts.id.disableAutoSelect();
}
