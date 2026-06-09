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

export interface PillarSummary {
  pillar_id: string;
  name: string;
  subcap_count: number;
  completeness: number;
  decay: number;
}

export interface CatalogueSummary {
  version_id: string;
  total_subcaps: number;
  pillars: PillarSummary[];
}

export interface SubcapNode {
  id: string;
  name: string;
  pillar: string;
  cat_id: string;
  cat_name: string;
  cluster: string;
  life: string;
  is_new: boolean;
}

export interface SubcapDetail {
  id: string;
  name: string;
  pillar: string;
  category: string;
  cluster: string;
  description: string | null;
  solution_type: string | null;
  tier: string | null;
  lifecycle_state: string;
  completeness: number | null;
  n_use_cases: number;
  n_stories: number;
  n_platforms: number;
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
  summary: (v: string): Promise<CatalogueSummary> =>
    http<CatalogueSummary>(`/api/catalogue/${v}/summary`),
  subcaps: (v: string): Promise<SubcapNode[]> =>
    http<SubcapNode[]>(`/api/catalogue/${v}/subcaps`),
  subcap: (v: string, id: string): Promise<SubcapDetail> =>
    http<SubcapDetail>(`/api/catalogue/${v}/subcaps/${id}`),
};
