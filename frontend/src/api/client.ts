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

export interface StoryRow {
  story_key: string;
  project_key: string | null;
  summary: string | null;
  confidence_level: string | null;
  composite_score: number | null;
  ac_score: number | null;
  sd_score: number | null;
  story_score: number | null;
  story_sv_code: string | null;
  tier: string | null;
}

export interface StoryPage {
  total: number;
  page: number;
  size: number;
  items: StoryRow[];
}

export interface Persona {
  persona_id: string;
  canonical_name: string;
  role_description: string | null;
}

export interface Platform {
  l3_id: string;
  name: string;
  vendor: string | null;
  category: string | null;
}

export interface UseCase {
  use_case_id: string;
  archetype: string | null;
  name: string;
  description: string | null;
}

export interface Maturity {
  level: string;
  descriptor: string | null;
  features: string | null;
}

export interface SubcapEnrichment {
  personas: Persona[];
  platforms: Platform[];
  use_cases: UseCase[];
  maturity: Maturity[];
}

export interface PlatformRow {
  l3_id: string;
  name: string;
  vendor: string | null;
  category: string | null;
  subcap_count: number;
  p1: number;
  p2: number;
  p3: number;
  p4: number;
  stories: number;
}

export interface PlatformSubcap {
  id: string;
  pillar: string;
  name: string;
}

export interface PlatformDetail {
  l3_id: string;
  name: string;
  vendor: string | null;
  category: string | null;
  subcaps: PlatformSubcap[];
}

export interface VendorRow {
  vendor: string;
  plats: number;
  subcap_count: number;
  p1: number;
  p2: number;
  p3: number;
  p4: number;
}

export interface UseCaseRow {
  use_case_id: string;
  archetype: string | null;
  description: string | null;
  subcap_id: string;
  subcap_name: string;
  pillar: string;
  category: string;
}

export interface UseCasePage {
  total: number;
  page: number;
  size: number;
  items: UseCaseRow[];
  archetypes: { archetype: string; count: number }[];
}

export interface UseCaseQuery {
  pillar?: string;
  category?: string;
  archetype?: string;
  q?: string;
  page?: number;
  size?: number;
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
  subcapStories: (v: string, id: string, page = 1, size = 8): Promise<StoryPage> =>
    http<StoryPage>(`/api/catalogue/${v}/subcaps/${id}/stories?page=${page}&size=${size}`),
  subcapEnrichment: (v: string, id: string): Promise<SubcapEnrichment> =>
    http<SubcapEnrichment>(`/api/catalogue/${v}/subcaps/${id}/enrichment`),
  platforms: (v: string): Promise<PlatformRow[]> =>
    http<PlatformRow[]>(`/api/catalogue/${v}/platforms`),
  platform: (v: string, id: string): Promise<PlatformDetail> =>
    http<PlatformDetail>(`/api/catalogue/${v}/platforms/${id}`),
  vendors: (v: string): Promise<VendorRow[]> => http<VendorRow[]>(`/api/catalogue/${v}/vendors`),
  useCases: (v: string, p: UseCaseQuery): Promise<UseCasePage> => {
    const qs = new URLSearchParams();
    if (p.pillar) qs.set('pillar', p.pillar);
    if (p.category) qs.set('category', p.category);
    if (p.archetype) qs.set('archetype', p.archetype);
    if (p.q) qs.set('q', p.q);
    qs.set('page', String(p.page ?? 1));
    qs.set('size', String(p.size ?? 12));
    return http<UseCasePage>(`/api/catalogue/${v}/use-cases?${qs.toString()}`);
  },
};
