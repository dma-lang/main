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

export interface OfferingRef {
  offering_id: string;
  name: string;
  category: string | null;
}

export interface SubcapEnrichment {
  personas: Persona[];
  platforms: Platform[];
  use_cases: UseCase[];
  maturity: Maturity[];
  offerings: OfferingRef[];
}

export interface ConnectionSibling {
  id: string;
  name: string;
  pillar: string;
  shared_platforms: number;
}

export interface SubcapConnections {
  siblings: ConnectionSibling[];
}

export interface ChatCitation {
  subcap_id: string;
  name: string;
}

export interface ChatResponse {
  grounded: boolean;
  answer: string;
  citations: ChatCitation[];
  claim_label: string | null;
  source_tier: string | null;
  source: string | null;
  ers: number;
  chain_id: string | null;
}

export interface EvidenceRow {
  claim_label: string;
  tier: string;
  text: string;
}

export interface ReasoningStep {
  kind: string;
  text: string;
  evidence: EvidenceRow[];
}

export interface GateCheck {
  name: string;
  state: string;
  detail: string;
}

export interface ReasoningChain {
  chain_id: string;
  title: string;
  claim_label: string | null;
  verdict: string | null;
  cost: string;
  model: string | null;
  created_at: string | null;
  steps: ReasoningStep[];
  checks: GateCheck[];
}

export interface LifecycleSubcap {
  id: string;
  name: string;
  pillar: string;
  stories: number;
  offering_id: string | null;
  offering_name: string | null;
}

export interface LifecycleSummary {
  subcaps_delivered: number;
  offerings: number;
  covered_pct: number;
  gaps: number;
  top: LifecycleSubcap[];
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

export interface StoryLibraryRow {
  story_key: string;
  summary: string | null;
  subcap_id: string;
  subcap_name: string | null;
  pillar: string | null;
  sv: string | null;
  composite_score: number | null;
  confidence_level: string | null;
  ac_score: number | null;
  sd_score: number | null;
  story_score: number | null;
}

export interface StoryLibraryPage {
  total: number;
  page: number;
  size: number;
  items: StoryLibraryRow[];
  high: number;
  medium: number;
  low: number;
  buckets: number[];
}

export interface StoryLibraryQuery {
  pillar?: string;
  conf?: string;
  sv?: string;
  min_composite?: number;
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
  subcapConnections: (v: string, id: string): Promise<SubcapConnections> =>
    http<SubcapConnections>(`/api/catalogue/${v}/subcaps/${id}/connections`),
  platforms: (v: string): Promise<PlatformRow[]> =>
    http<PlatformRow[]>(`/api/catalogue/${v}/platforms`),
  platform: (v: string, id: string): Promise<PlatformDetail> =>
    http<PlatformDetail>(`/api/catalogue/${v}/platforms/${id}`),
  vendors: (v: string): Promise<VendorRow[]> => http<VendorRow[]>(`/api/catalogue/${v}/vendors`),
  lifecycle: (v: string): Promise<LifecycleSummary> =>
    http<LifecycleSummary>(`/api/catalogue/${v}/lifecycle`),
  chat: (question: string, version: string): Promise<ChatResponse> =>
    http<ChatResponse>('/api/chat', { method: 'POST', body: JSON.stringify({ question, version }) }),
  reasoning: (chainId: string): Promise<ReasoningChain> =>
    http<ReasoningChain>(`/api/reasoning/${chainId}`),
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
  stories: (p: StoryLibraryQuery): Promise<StoryLibraryPage> => {
    const qs = new URLSearchParams();
    if (p.pillar) qs.set('pillar', p.pillar);
    if (p.conf) qs.set('conf', p.conf);
    if (p.sv) qs.set('sv', p.sv);
    if (p.min_composite) qs.set('min_composite', String(p.min_composite));
    if (p.q) qs.set('q', p.q);
    qs.set('page', String(p.page ?? 1));
    qs.set('size', String(p.size ?? 10));
    return http<StoryLibraryPage>(`/api/stories?${qs.toString()}`);
  },
};
