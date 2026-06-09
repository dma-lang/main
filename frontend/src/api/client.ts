// Typed API client. Same-origin in prod (the SPA is served by FastAPI); the Vite dev server proxies
// /api to the backend. Errors surface the server's `{"error":{"message"}}` envelope.

export interface Me {
  uid: string;
  email: string;
  is_admin: boolean;
  preferences: Record<string, unknown>;
}

export interface VersionInfo {
  version_id: string;
  label: string;
  status: string;
  schema_name: string;
  created_at: string | null;
}

const BASE: string = import.meta.env.VITE_API_BASE ?? '';

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    credentials: 'include',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers as Record<string, string> | undefined),
    },
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = (await res.json()) as { error?: { message?: string } };
      message = body.error?.message ?? message;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${res.status}: ${message}`);
  }
  return (await res.json()) as T;
}

export const api = {
  me: (): Promise<Me> => http<Me>('/api/me'),
  patchPreferences: (preferences: Record<string, unknown>): Promise<Me> =>
    http<Me>('/api/me/preferences', { method: 'PATCH', body: JSON.stringify({ preferences }) }),
  versions: (): Promise<VersionInfo[]> => http<VersionInfo[]>('/api/versions'),
};
