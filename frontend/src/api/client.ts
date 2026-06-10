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

export interface ConnectionSignal {
  title: string;
  source: string;
  tier: string;
  label: string;
  ers: number;
  mag: string;
  score: number;
  date: string;
  chain: string | null;
}

export interface SubcapConnections {
  siblings: ConnectionSibling[];
  signals: ConnectionSignal[];
}

export interface NewsSource {
  name: string;
  type: string;
  tier: string;
  url: string;
  ers: number;
  fetched_at: string;
}

export interface NewsItem {
  id: string;
  title: string;
  date: string;
  mag: string;
  tier: string;
  label: string;
  impact: string;
  impact_label: string;
  impact_note: string;
  reliability: number;
  source: NewsSource;
  affects: [string, number, string, string][]; // [subcap_id, score, name, mag]
  chain: string | null;
}

export interface NewsScan {
  last_scan: string | null;
  next_scan: string | null;
  cadence: string;
  cron: string;
}

export interface NewsResp {
  items: NewsItem[];
  impacts: { v: string; l: string }[];
  scan: NewsScan;
}

export interface NewsLoopOut {
  staged: boolean;
  status: string;
  reason: string | null;
  suggestion_id: string | null;
  kind: string | null;
  target: string | null;
}

export interface NewsScanStats {
  version: string;
  fetched: number;
  created: number;
  deduped: number;
  mapped: number;
  flagged: number;
}

export interface TrendSignals {
  velocity: number;
  diversity: number;
  novelty: number;
  persistence: number;
}

export interface TrendSubcap {
  subcap_id: string;
  name: string;
  emergent: boolean;
}

export interface TrendItem {
  id: string;
  label: string;
  status: string;
  window: string;
  window_start: string;
  window_end: string;
  evidence_count: number;
  score: number;
  signals: TrendSignals;
  affects: TrendSubcap[];
  emergent: boolean;
  label_claim: string;
  tier: string;
  ers: number;
  chain: string | null;
}

export interface TrendsResp {
  items: TrendItem[];
  counts: Record<string, number>;
  scan: NewsScan;
}

export interface TrendScanStats {
  version: string;
  detected: number;
  staged: number;
  review: number;
  filtered: number;
  decided: number;
  emergent: number;
}

export interface TrendEvidenceItem {
  title: string;
  url: string;
  source: string;
  stype: string;
  tier: string;
  date: string;
  impact: string;
  ers: number;
  chain: string | null;
}

export interface TrendEvidenceResp {
  found: boolean;
  label: string;
  status: string;
  evidence_count: number;
  evidence: TrendEvidenceItem[];
}

export interface BenchItem {
  id: string;
  metric: string;
  unit: string;
  segment: string;
  date: string;
  n: number;
  observations: number[];
  p25: number;
  p50: number;
  p75: number;
  ci_low: number | null; // null = suppressed (thin coverage — no false precision)
  ci_high: number | null;
  thin: boolean;
  coverage_note: string | null;
  methodology: string; // "not documented" when the source did not publish one
  verdict: string; // BENCHMARK | INDICATIVE | EXPLORATORY | pending
  verdict_note: string;
  label: string;
  tier: string;
  ers: number;
  reliability: number;
  source: NewsSource;
  affects: [string, number, string][]; // [subcap_id, score, name]
  chain: string | null;
}

export interface BenchResp {
  items: BenchItem[];
  segments: string[];
  scan: NewsScan;
}

export interface BenchScanStats {
  version: string;
  fetched: number;
  created: number;
  deduped: number;
  mapped: number;
  flagged: number;
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

export interface SuggestionOut {
  suggestion_id: string;
  target_subcap: string | null;
  subcap_name: string | null;
  pillar: string | null;
  kind: string;
  title: string;
  rationale: string;
  status: string;
  verdict: string | null;
  breaking: boolean;
  claim_label: string | null;
  source_tier: string | null;
  ers: number;
  chain_id: string | null;
  cost: string;
  created_at: string | null;
}

export interface ApplyOut {
  applied: boolean;
  status: string;
  gate_failed: string | null;
  before: string | null;
  after: string | null;
}

export interface GateStat {
  id: string;
  name: string;
  pass_pct: number;
  warn_pct: number;
  fail_pct: number;
  score: number;
  runs: number;
}

export interface GatesLog {
  gates: GateStat[];
  total_runs: number;
  pass_runs: number;
  fail_runs: number;
}

export interface QaMetrics {
  gate_pass_rate: number | null;
  total_runs: number;
  reasoning_chains: number;
  applied: number;
  hallucination_rate: number | null;
  retrieval_mrr: number | null;
  spend_usd: number | null;
  envelope_usd: number;
}

export interface AuditRow {
  audit_id: number;
  actor: string | null;
  action: string;
  target_ref: string | null;
  at: string | null;
  meta: Record<string, unknown>;
}

export interface ChangeFlag {
  id: string;
  sev: string;
  kind: string;
  age: string;
  chain: string | null;
  title: string;
  body: string;
  target: string | null;
  name: string | null;
  pillar: string | null;
  gate_failed: string | null;
  before: string | null;
  after: string | null;
  stories: number;
  status: string;
}

export interface ChangeFlagsResp {
  flags: ChangeFlag[];
  counts: Record<string, number>;
}

export interface FlagActionOut {
  resolved: boolean;
  status: string;
  gate_failed: string | null;
  before: string | null;
  after: string | null;
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
  suggestions: (status: string): Promise<SuggestionOut[]> =>
    http<SuggestionOut[]>(`/api/suggestions?status=${status}`),
  proposeSuggestions: (version: string): Promise<{ created: number; candidates: number }> =>
    http<{ created: number; candidates: number }>(`/api/admin/suggestions/propose/${version}`, {
      method: 'POST',
    }),
  applySuggestion: (id: string): Promise<ApplyOut> =>
    http<ApplyOut>(`/api/suggestions/${id}/apply`, { method: 'POST' }),
  rejectSuggestion: (id: string, reason: string): Promise<ApplyOut> =>
    http<ApplyOut>(`/api/suggestions/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  news: (impact?: string, tier?: string): Promise<NewsResp> => {
    const qs = new URLSearchParams({ kind: 'news' });
    if (impact && impact !== 'all') qs.set('impact', impact);
    if (tier && tier !== 'all') qs.set('tier', tier);
    return http<NewsResp>(`/api/evidence?${qs.toString()}`);
  },
  scanNews: (version: string): Promise<NewsScanStats> =>
    http<NewsScanStats>(`/api/admin/evidence/scan/news/${version}`, { method: 'POST' }),
  newsLoop: (newsId: string): Promise<NewsLoopOut> =>
    http<NewsLoopOut>(`/api/evidence/news/${newsId}/loop`, { method: 'POST' }),
  trends: (status?: string, version?: string): Promise<TrendsResp> => {
    const qs = new URLSearchParams();
    if (status && status !== 'all') qs.set('status', status);
    if (version) qs.set('version', version);
    return http<TrendsResp>(`/api/trends?${qs.toString()}`);
  },
  scanTrends: (version: string): Promise<TrendScanStats> =>
    http<TrendScanStats>(`/api/admin/trends/scan/${version}`, { method: 'POST' }),
  trendEvidence: (id: string): Promise<TrendEvidenceResp> =>
    http<TrendEvidenceResp>(`/api/trends/${id}/evidence`),
  trendFeedback: (id: string, verdict: string): Promise<{ ok: boolean; status: string }> =>
    http<{ ok: boolean; status: string }>(`/api/trends/${id}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ verdict }),
    }),
  trendLoop: (id: string): Promise<NewsLoopOut> =>
    http<NewsLoopOut>(`/api/trends/${id}/loop`, { method: 'POST' }),
  benchmarks: (segment?: string): Promise<BenchResp> => {
    const qs = new URLSearchParams({ kind: 'benchmark' });
    if (segment && segment !== 'all') qs.set('segment', segment);
    return http<BenchResp>(`/api/evidence?${qs.toString()}`);
  },
  scanBenchmarks: (version: string): Promise<BenchScanStats> =>
    http<BenchScanStats>(`/api/admin/evidence/scan/benchmarks/${version}`, { method: 'POST' }),
  benchmarkLoop: (id: string): Promise<NewsLoopOut> =>
    http<NewsLoopOut>(`/api/evidence/benchmark/${id}/loop`, { method: 'POST' }),
  gates: (): Promise<GatesLog> => http<GatesLog>('/api/gates'),
  qaMetrics: (): Promise<QaMetrics> => http<QaMetrics>('/api/qa/metrics'),
  auditLog: (): Promise<AuditRow[]> => http<AuditRow[]>('/api/audit-log'),
  changeFlags: (status: string): Promise<ChangeFlagsResp> =>
    http<ChangeFlagsResp>(`/api/change-flags?status=${status}`),
  scanFlags: (version: string): Promise<{ created: number; candidates: number }> =>
    http<{ created: number; candidates: number }>(`/api/admin/change-flags/scan/${version}`, {
      method: 'POST',
    }),
  approveFlag: (id: string): Promise<FlagActionOut> =>
    http<FlagActionOut>(`/api/change-flags/${id}/approve`, { method: 'POST' }),
  rejectFlag: (id: string, reason: string): Promise<FlagActionOut> =>
    http<FlagActionOut>(`/api/change-flags/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  deferFlag: (id: string): Promise<FlagActionOut> =>
    http<FlagActionOut>(`/api/change-flags/${id}/defer`, { method: 'POST' }),
};
