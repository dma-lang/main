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
  tier?: string; // active | inactive | legacy — computed relative to the active version's number
}

export interface DiffRow {
  id: string;
  name: string;
  pillar: string;
  l2?: string | null;
  explanation: string;
}

export interface DiffModified extends DiffRow {
  from_id?: string | null; // set when the id was reassigned (a rename carried across versions)
  changes: string[];
}

export interface DiffResp {
  a: string;
  b: string;
  added: DiffRow[];
  removed: DiffRow[];
  modified: DiffModified[];
  unchanged: number;
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

export interface HeatmapRow {
  key: string;
  label: string;
  subtitle: string;
  total: number;
  cells: number[];
  pillar: string | null;
}

export interface HeatmapResp {
  lens: string;
  axis: string[];
  rows: HeatmapRow[];
  max: number;
}

export interface HeatmapDrillSubcap {
  id: string;
  name: string;
  pillar: string;
  stories: number;
}

export interface HeatmapDrillResp {
  lens: string;
  key: string;
  subcaps: HeatmapDrillSubcap[];
  total_subcaps: number;
  total_stories: number;
}

export interface OfferingRow {
  id: string;
  name: string;
  family: string;
  summary: string;
  platforms: string[];
  n_subcaps: number;
  stories: number;
  pillars: Record<string, number>;
}

export interface OfferingMatch {
  id: string;
  name: string;
  pillar: string;
  stories: number;
  score: number;
  capability: string;
}

export interface OfferingDetail {
  id: string;
  name: string;
  family: string;
  summary: string;
  platforms: string[];
  outcomes: string[];
  capabilities: string[];
  n_subcaps: number;
  stories: number;
  pillars: Record<string, number>;
  subcaps: OfferingMatch[];
}

// AI-identified candidate subverticals we have NOT scoped (gated proposals from the unscoped-Jira
// detector) — rendered as the ORANGE heatmap + drilldown on mission control.
export interface UnscopedCandidate {
  flag_id: string;
  chain_id: string | null;
  client: string; // the Jira project_key driving this unscoped delivery
  code: string | null; // provisional subvertical code
  name: string; // proposed (provisional) subvertical name
  severity: string;
  status: string;
  stories: number;
  cells: number[]; // 6 composite-score bands — the orange heatmap row
  pillars: string[];
  top_capabilities: { name: string; n: number }[];
  overlap_sv: string | null;
  overlap: number;
  claim_label: string | null;
  source_tier: string | null;
  ers: number | null;
  samples: string[];
}
export interface UnscopedSubverticalsResp {
  version: string;
  axis: string[];
  candidates: UnscopedCandidate[];
  max: number;
}

export interface TimelineEvent {
  kind: string;
  date: string | null;
  title: string;
  claim: string | null;
  tier: string | null;
  mag: string | null;
  excerpt: string | null;
  chain: string | null;
}

export interface TimelineResp {
  subcap_id: string;
  name: string;
  stories: number;
  sources: number;
  events: TimelineEvent[];
}

export interface KgNode {
  id: string;
  kind: string;
  label: string;
  pillar: string | null;
}

// R6 directional semantics — the NLP relation, its direction, the connective keywords and the
// grounded "why". `relation` is null on legacy symmetric edges (treat null as non-directional);
// `direction` is "forward" (draw an ARROW source→target) or "bidirectional" (symmetric, no arrowhead).
export type KgRelation =
  | 'enables'
  | 'depends_on'
  | 'precedes'
  | 'affects'
  | 'complements'
  | 'alternative_to'
  | 'subsumes';

export interface KgEdge {
  source: string;
  target: string;
  kind: string; // relation: uses_platform | shares_platform | co_delivered | same_value_chain | …
  layer: string;
  score?: number | null; // legacy alias of strength (Layer-B confidence); null for facts
  strength?: number | null; // R5 unified 0..1 confidence — edge thickness ∝ strength
  basis?: string | null; // R5 the "why" (e.g. "co-delivered across 30 client projects, lift 5.2")
  crosses?: string | null; // R5 cross_capability | cross_pillar (subcap↔subcap edges)
  novelty?: number | null; // R5 discovery rank (Layer B): strong AND non-obvious ranks top
  chain?: string | null; // R5 reasoning-chain backlink (Layer B)
  pending_id?: string | null; // R5 approve/peek the proposal straight from the edge
  relation?: KgRelation | string | null; // R6 directional semantics; null on legacy symmetric edges
  direction?: 'forward' | 'bidirectional' | string | null; // R6 forward → arrowhead; bidirectional → none
  keywords?: string[]; // R6 the connective concepts ("major keywords")
  rationale?: string | null; // R6 the NLP "why", grounded in the two descriptions
  verify_survived?: number | null; // R6 0..1 fraction of adversary passes that upheld it (KgEdge only)
  corroboration?: string | null; // R6 the Jira-corpus corroboration note (KgEdge only)
}

// R5 "relationships you may be missing" — a gated Layer-B proposal oriented from a focus subcap to
// the OTHER subcap, ranked by novelty (strong AND non-obvious first: cross-pillar, no shared platform).
export interface LatentEdge {
  source: string;
  source_name: string;
  target: string;
  target_name: string;
  target_pillar: string;
  kind: string;
  strength: number;
  novelty: number;
  basis: string;
  crosses: string; // cross_capability | cross_pillar
  chain?: string | null;
  pending_id?: string | null;
  relation?: KgRelation | string | null; // R6 directional semantics; null on legacy symmetric edges
  direction?: 'forward' | 'bidirectional' | string | null; // R6 forward → arrow glyph, bidirectional → ↔
  keywords?: string[]; // R6 the connective concepts ("major keywords")
  rationale?: string | null; // R6 the NLP "why", grounded in the two descriptions
}

export interface KgResp {
  center: string;
  name: string;
  nodes: KgNode[];
  edges: KgEdge[];
  stats: Record<string, number>;
  pending: KgEdge[];
  latent: LatentEdge[]; // R5 per-subcap novelty-ranked discoveries
}

export interface KgDiscoverResp {
  version: string;
  latent: LatentEdge[]; // R5 version-wide discovery surface
}

export interface SowDoc {
  sow_id: string;
  account_key: string;
  account_name: string;
  title: string;
  sv_code: string | null;
  signed_date: string | null;
  status: string;
  redacted: boolean;
  items: number;
  confirmed: number;
  review: number;
  unmapped: number;
}

export interface SowItem {
  scope_id: string;
  ordinal: number;
  clause: string;
  match_id: string | null;
  subcap_id: string | null;
  subcap_name: string | null;
  similarity: number | null;
  status: string | null;
  claim_label: string | null;
  source_tier: string | null;
  chain_id: string | null;
  confirmed_by: string | null;
}

export interface SowDetail {
  sow_id: string;
  account_key: string;
  account_name: string;
  title: string;
  sv_code: string | null;
  signed_date: string | null;
  status: string;
  redacted: boolean;
  items: SowItem[];
}

export interface ClientRow {
  key: string; // the client identity — a resolved client_name, or a project_key fallback
  client_name: string | null; // the resolved client (e.g. "Academy Bank"); null on unmatched keys
  salesforce_account_id: string | null;
  client_match_confidence: number | null; // 0..1 resolution confidence
  sows: number;
  scope_items: number;
  stories: number;
  projects: number; // distinct Jira project keys rolled up under this client
  subcaps_touched: number;
  last_sow: string | null;
}

export interface MappingField {
  sheet_name: string;
  source_field: string;
  canonical_entity: string;
  canonical_field: string;
  confidence: number;
  status: string;
  is_custom: boolean;
}

export interface MappingRelation {
  from_entity: string;
  rel_type: string;
  to_entity: string;
  card: string;
  via_sheet: string;
  is_cascade: boolean;
}

export interface MappingResp {
  version: string;
  fields: MappingField[];
  relations: MappingRelation[];
}

export interface ClientJourney {
  key: string; // the client identity (a resolved client_name, or a project_key fallback)
  client_name: string | null; // the resolved client; null on an unmatched key
  salesforce_account_id: string | null;
  client_match_confidence: number | null; // 0..1 resolution confidence
  stories: number;
  sows: { sow_id: string; title: string; sv_code: string | null; signed_date: string | null; status: string }[];
  matches: {
    subcap_id: string;
    subcap_name: string | null;
    similarity: number;
    status: string;
    claim_label: string;
    chain_id: string | null;
    date: string | null;
    clause: string;
  }[];
  top_delivery: { subcap_id: string; subcap_name: string | null; stories: number }[];
}

export interface WhatIfRef {
  id: string;
  name: string;
}

export interface WhatIfResp {
  subcap: string;
  name: string;
  action: string;
  stories: number;
  use_cases: number;
  offerings: WhatIfRef[];
  platforms: WhatIfRef[];
  siblings: WhatIfRef[];
  blast: number;
  summary: string;
  reversible: boolean;
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

export interface VcPillarTally {
  P1: number;
  P2: number;
  P3: number;
  P4: number;
}
export interface VcTopSubcap {
  id: string;
  name: string;
  n: number; // delivered Jira stories
  pillar: string | null;
}
export interface ValueChainSubcap {
  id: string;
  name: string;
  pillar: string;
  stage?: string;
}
export interface ValueChainCluster {
  code: string;
  name: string; // the REAL stage name (the code is only an id)
  position?: number; // chain step (1..N) in the real per-SV pipeline
  pillar: string | null;
  count: number;
  subcaps: ValueChainSubcap[];
  stories?: number; // delivered Jira stories across the stage's subcaps (Pipeline/Radial heat)
  pillars?: VcPillarTally; // P1-P4 subcap tally for the stage
  top?: VcTopSubcap[]; // top-8 subcaps by delivery
  stages?: { name: string; count: number }[]; // present only in the derived fallback
  merged_from: string[];
}
export interface ValueChainGroup {
  sv: string; // the subvertical this ordered chain belongs to
  clusters: ValueChainCluster[];
  total_subcaps: number;
}
export interface ValueChainStageRollup {
  code: string; // VCC-01..08
  name: string;
  blurb: string;
  subcaps: number;
  stories: number;
  projects: number;
  pillars: VcPillarTally;
  confidence: { HIGH: number; MEDIUM: number; LOW: number }; // delivery-confidence split (Jira)
  top: VcTopSubcap[];
}
export interface ValueChainResp {
  version: string;
  sv: string;
  resolved_sv?: string; // set only when ONE subvertical is pinned (empty for 'All SV')
  sv_requested?: string;
  subverticals?: string[]; // subverticals that carry a chain in this version (delivery-ranked)
  source?: string; // catalogue_vc_mapping[_inherited] (real per-SV stages) | derived_from_clusters
  inherited_from?: string | null; // the reference version this chain was inherited from (e.g. v7)
  chains?: ValueChainGroup[]; // one ordered pipeline per subvertical (all of them for 'All SV')
  clusters: ValueChainCluster[]; // backward-compat flat list (the derived fallback uses only this)
  raw_clusters: number;
  deduped: number;
  total_subcaps: number;
  rollup?: ValueChainStageRollup[]; // the 8 canonical MECE stages (Rollup view); absent on derived
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

// R8 structured story detail — the user-story shape (role/goal/benefit), the acceptance OUTCOMES and
// the solution APPROACH, all parsed deterministically from the raw Jira text. Any field can be null /
// empty when the source did not carry it; render nothing rather than "null".
export interface StoryFacets {
  role: string | null;
  goal: string | null;
  benefit: string | null;
  acceptance: string[];
  approach: string[];
}

export interface StoryRow {
  story_key: string;
  project_key: string | null;
  epic_key?: string | null;
  summary: string | null;
  confidence_level: string | null;
  composite_score: number | null;
  ac_score: number | null;
  sd_score: number | null;
  story_score: number | null;
  delivery_score?: number | null;
  story_sv_code: string | null;
  tier: string | null;
  cap_name?: string | null;
  category_name?: string | null;
  reusability_layer?: string | null;
  population?: string | null;
  is_synthetic?: boolean;
  // R8 rich detail — the resolved client, the synthesized narrative + structured facets, and the
  // raw acceptance-criteria / solution-design text (the fallback when facets are absent).
  client_name?: string | null;
  narrative?: string | null;
  facets?: StoryFacets | null;
  ac_text?: string | null;
  solution_design_text?: string | null;
}

export interface StoryPage {
  total: number;
  page: number;
  size: number;
  items: StoryRow[];
}

// Delivery drilldown under a subcap's story count: clients parsed from Jira project keys +
// deterministic story clusters listing the related clients with similar story characteristics.
export interface ClientAgg {
  project_key: string;
  stories: number;
  share: number;
  avg_composite: number | null;
  subverticals: string[];
  top: StoryRow[];
}

export interface StoryCluster {
  cluster_id: number;
  label: string;
  stories: number;
  clients: string[];
  avg_composite: number | null;
  sample: StoryRow[];
}

export interface DeliveryDrill {
  subcap_id: string;
  name: string;
  total_stories: number;
  n_clients: number;
  clients: ClientAgg[];
  clusters: StoryCluster[];
  unclustered: number;
  clustered_over: number;
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
  inherited_from?: string | null; // set when facets came from the reference catalogue (v7)
}

export interface ConnectionSibling {
  id: string;
  name: string;
  pillar: string;
  shared_platforms: number;
  relation: string; // "cluster" (same capability) | "semantic" (embedding-near, cross-capability)
  score: number; // semantic cosine; 0 for cluster
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
  latent: LatentEdge[]; // R5 gated "relationships you may be missing" that touch this subcap
}

// R8 productized-offering coverage for one subcap. A subcap MAY be tackled by several offerings;
// when `multi` is true the deep-dive shows all of them side by side, each with its match score, the
// capability that drove it, the aligned use-case chips, a grounded explanation and evidence stories.
export interface OfferingAlignment {
  offering_id: string;
  name: string;
  category: string | null;
  score: number; // the matcher's confidence that this offering tackles the subcap
  capability: string; // the offering capability that drove the match (the "why")
  aligned_use_cases: { use_case_id: string; name: string }[];
  explanation: string; // grounded, plain-language WHY this offering applies
  evidence_story_keys: string[]; // top delivered stories on the subcap
}

export interface SubcapOfferingCoverage {
  subcap_id: string;
  multi: boolean; // a subcap tackled by >= 2 productized offerings
  offerings: OfferingAlignment[];
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

export interface VendorProfile {
  vendor_id: string;
  name: string;
  platforms: number;
  developments_90d: number;
  subcaps_touched: number;
  heat: number;
}

export interface VendorEventItem {
  id: string;
  vendor: string;
  vendor_id: string;
  event_type: string;
  type_label: string;
  title: string;
  date: string;
  mag: string;
  tier: string;
  label: string;
  impact_note: string;
  reliability: number;
  source: NewsSource;
  affects: [string, number, string, string][]; // [subcap_id, score, name, mag]
  chain: string | null;
}

export interface VendorHeatCell {
  vendor: string;
  subcap_id: string;
  name: string;
  score: number;
}

export interface VendorIntelResp {
  vendors: VendorProfile[];
  items: VendorEventItem[];
  heat: VendorHeatCell[];
  types: { v: string; l: string }[];
  scan: NewsScan;
}

export interface VendorScanStats {
  version: string;
  fetched: number;
  created: number;
  deduped: number;
  mapped: number;
  review: number;
  flagged: number;
  registry_flags: number;
}


export interface DigestPriority {
  pillar: string;
  pillar_name: string;
  title: string;
  body: string;
  adversary_verdict: string;
}

export interface DigestResp {
  quarter: string;
  generated: boolean;
  summary: string;
  theme: string;
  claim_label: string;
  chain: string | null;
  created_at: string | null;
  priorities: DigestPriority[];
  quarters: string[];
  cadence: { cadence: string; cron: string; next_run: string };
  export: { export_id: string; signed_at: string; valid: boolean } | null;
}

export interface DigestExportOut {
  exported: boolean;
  export_id?: string;
  quarter?: string;
  hmac_sig?: string;
  reason?: string;
}

export interface AdminRow {
  email: string;
  source: string; // bootstrap (env) | grant (runtime)
  removable: boolean;
  granted_by: string;
  note?: string;
  created_at?: string;
}

export interface SourceRow {
  key: string;
  name: string;
  type: string;
  tier: string;
  enabled: boolean;
  mode: string; // recorded | live
  origin_active: string;
  origin_recorded: string;
  origin_live: string;
  cadence: string;
  cron: string | null;
  next_run: string | null;
  last_run: string | null;
  last_status: string | null;
  last_stats: Record<string, number>;
  status: string; // ok | stale | never_run | disabled
  notes: string;
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

export interface ReasoningChainRow {
  chain_id: string;
  title: string;
  claim_label: string | null;
  verdict: string | null;
  model: string | null;
  cost: string;
  steps: number;
  created_at: string | null;
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

export interface FlagPropagation {
  saved: { version: string; subcap: string; use_case_id: string }[];
  skipped: { version: string; reason: string }[];
}

export interface FlagActionOut {
  resolved: boolean;
  status: string;
  gate_failed: string | null;
  before: string | null;
  after: string | null;
  propagated?: FlagPropagation | null; // R7: cross-version fan-out summary (saved to / skipped)
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

export interface PlatformUseCase {
  archetype: string;
  stories: number; // delivered Jira stories on this platform's subcaps via this archetype
}

export interface PlatformDetail {
  l3_id: string;
  name: string;
  vendor: string | null;
  category: string | null;
  subcaps: PlatformSubcap[];
  use_cases: PlatformUseCase[];
}

export interface VendorRow {
  vendor: string;
  plats: number;
  subcap_count: number;
  p1: number;
  p2: number;
  p3: number;
  p4: number;
  stories: number; // distinct delivered stories across the vendor's subcaps
}

export interface VendorCellSubcap {
  id: string;
  name: string;
  pillar: string;
  stories: number;
}

export interface UseCaseRow {
  use_case_id: string;
  archetype: string | null; // raw archetype code (filter key)
  name: string | null; // readable title (humanized archetype)
  description: string | null;
  subcap_id: string;
  subcap_name: string;
  pillar: string;
  category: string; // L1 capability name
  category_id: string; // L1 capability id (P1C1 …)
  cluster: string | null; // L2 capability ("cluster")
  maturity: string | null; // the use case's OWN maturity (e.g. M3+)
  is_new: boolean;
  n_stories: number; // Jira stories MATCHED to this use case (real per-use-case delivery)
  subcap_stories: number; // the owning subcap's total delivery (for "X of N" context)
}

export interface UseCaseCategory {
  category_id: string;
  category: string;
  pillar: string;
  use_cases: number;
  n_stories: number; // distinct stories matched to this L1's use cases
}

export interface UseCasePage {
  total: number;
  page: number;
  size: number;
  items: UseCaseRow[];
  archetypes: { archetype: string; count: number; n_stories: number }[];
  categories: UseCaseCategory[]; // L1-capability grouping (matched-story totals)
}

export interface UseCaseQuery {
  pillar?: string;
  category?: string;
  archetype?: string;
  q?: string;
  sort?: string; // 'delivery' (default) | 'alpha'
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
  is_synthetic: boolean;
  source_system: string | null; // jira | gen_stories_v1 | gen_synthesized_gap_fill | …
  // R8 rich detail — the resolved client (+ its Jira project), the synthesized narrative + facets
  // and the raw acceptance / solution-design text.
  client_name?: string | null;
  project_key?: string | null;
  narrative?: string | null;
  facets?: StoryFacets | null;
  ac_text?: string | null;
  solution_design_text?: string | null;
}

export interface StoryLibraryPage {
  total: number;
  page: number;
  size: number;
  items: StoryLibraryRow[];
  high: number;
  medium: number;
  low: number;
  jira_total: number; // the real corpus (analysis-grade)
  synthetic_total: number; // workbook-embedded synthetic rows (labelled, excluded by default)
  buckets: number[];
}

export interface StoryLibraryQuery {
  pillar?: string;
  conf?: string;
  sv?: string;
  min_composite?: number;
  q?: string;
  synthetic?: 'exclude' | 'include' | 'only';
  page?: number;
  size?: number;
}

// An ID collision in the source workbook reconciled by name against the governing version's
// register (subcap ids are never reused, recycled, or invented).
export interface IdReconciliation {
  source_id: string;
  assigned_id: string;
  name: string;
  via: string;
}

export interface IdConflict {
  source_id: string;
  name: string;
  file: string;
}

export interface DetectedColumn {
  source: string;
  field: string;
  confidence?: number; // 0..1 — alias match + fill rate + format validity
  samples?: string[]; // first 3 values, for the human review
  signals?: { header_match: number; fill_rate: number; format_valid: number; rows_scanned: number };
}

export interface WorkbookDetail {
  file: string;
  sheet: string;
  columns: DetectedColumn[];
  unmapped_headers: string[];
  subcaps_parsed: number;
  other_sheets?: string[];
}

export interface DetectedRelation {
  from: string;
  verb: string;
  to: string;
  via: string;
}

export interface UploadManifest {
  version: string;
  workbooks: { name: string; bytes: number }[];
  pillars_recognised: string[];
  subcaps_parsed: number;
  synthetic_stories_found: number;
  id_reconciliations: IdReconciliation[];
  id_conflicts: IdConflict[];
  workbooks_detail: WorkbookDetail[];
  relations_detected: DetectedRelation[];
  skipped_rows: number;
  duplicate_rows: number;
  recorded: boolean;
  note: string;
}

import { getToken, isLiveAuth } from '../lib/auth';

const BASE: string = import.meta.env.VITE_API_BASE ?? '';

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  // Live auth attaches a fresh Google ID token; dev mode sends none. A 401 from a request that
  // CARRIED the current token means the session is no/expired — route to the login page (the
  // backend fails closed; this is just the UX). A 401 from a token-less request while a token
  // exists NOW is stale noise (e.g. a refetch that raced the sign-in popup) — never let it yank
  // a freshly signed-in user back to the login page.
  const token = await getToken().catch(() => null);
  const res = await fetch(BASE + path, {
    credentials: 'include',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers as Record<string, string> | undefined),
    },
  });
  if (!res.ok) {
    if (res.status === 401 && isLiveAuth() && !location.hash.startsWith('#/login')) {
      const now = await getToken().catch(() => null);
      if (token !== null || now === null) location.hash = '#/login';
    }
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
  diff: (a: string, b: string): Promise<DiffResp> => http<DiffResp>(`/api/diff/${a}/${b}`),
  sows: (version: string): Promise<SowDoc[]> => http<SowDoc[]>(`/api/sow?version=${version}`),
  sowDetail: (id: string, version: string): Promise<SowDetail> =>
    http<SowDetail>(`/api/sow/${id}?version=${version}`),
  scanSows: (version: string): Promise<Record<string, number | string>> =>
    http(`/api/admin/sow/scan/${version}`, { method: 'POST' }),
  confirmSowMatch: (matchId: string): Promise<{ ok: boolean; status: string }> =>
    http(`/api/sow/matches/${matchId}/confirm`, { method: 'POST' }),
  clients: (version: string): Promise<ClientRow[]> =>
    http<ClientRow[]>(`/api/clients?version=${version}`),
  mapping: (version: string): Promise<MappingResp> =>
    http<MappingResp>(`/api/admin/mapping/${version}`),
  clientJourney: (key: string, version: string): Promise<ClientJourney> =>
    http<ClientJourney>(`/api/clients/${encodeURIComponent(key)}/journey?version=${version}`),
  summary: (v: string, sv = 'all'): Promise<CatalogueSummary> =>
    http<CatalogueSummary>(`/api/catalogue/${v}/summary?sv=${sv}`),
  heatmap: (v: string, lens: string, pillar: string, sv: string): Promise<HeatmapResp> => {
    const qs = new URLSearchParams({ lens, pillar, sv });
    return http<HeatmapResp>(`/api/catalogue/${v}/heatmap?${qs.toString()}`);
  },
  heatmapDrill: (
    v: string,
    lens: string,
    key: string,
    pillar: string,
    sv: string,
  ): Promise<HeatmapDrillResp> => {
    const qs = new URLSearchParams({ lens, key, pillar, sv });
    return http<HeatmapDrillResp>(`/api/catalogue/${v}/heatmap/drill?${qs.toString()}`);
  },
  offerings: (v: string): Promise<OfferingRow[]> =>
    http<OfferingRow[]>(`/api/catalogue/${v}/offerings`),
  offeringDetail: (v: string, id: string): Promise<OfferingDetail> =>
    http<OfferingDetail>(`/api/catalogue/${v}/offerings/${encodeURIComponent(id)}`),
  unscopedSubverticals: (v: string): Promise<UnscopedSubverticalsResp> =>
    http<UnscopedSubverticalsResp>(`/api/catalogue/${v}/unscoped-subverticals`),
  subcaps: (v: string, sv = 'all'): Promise<SubcapNode[]> =>
    http<SubcapNode[]>(`/api/catalogue/${v}/subcaps?sv=${sv}`),
  valueChain: (v: string, pillar = '', sv = ''): Promise<ValueChainResp> => {
    const qs = new URLSearchParams();
    if (pillar && pillar !== 'all') qs.set('pillar', pillar);
    if (sv && sv !== 'all') qs.set('sv', sv);
    return http<ValueChainResp>(`/api/catalogue/${v}/value-chain?${qs.toString()}`);
  },
  subcap: (v: string, id: string): Promise<SubcapDetail> =>
    http<SubcapDetail>(`/api/catalogue/${v}/subcaps/${id}`),
  subcapStories: (v: string, id: string, page = 1, size = 8, synthetic = false): Promise<StoryPage> =>
    http<StoryPage>(
      `/api/catalogue/${v}/subcaps/${id}/stories?page=${page}&size=${size}&include_synthetic=${synthetic}`,
    ),
  useCaseStories: (v: string, id: string, page = 1, size = 12): Promise<StoryPage> =>
    http<StoryPage>(
      `/api/catalogue/${v}/use-cases/${encodeURIComponent(id)}/stories?page=${page}&size=${size}`,
    ),
  subcapDelivery: (v: string, id: string, synthetic = false): Promise<DeliveryDrill> =>
    http<DeliveryDrill>(
      `/api/catalogue/${v}/subcaps/${id}/delivery?include_synthetic=${synthetic}`,
    ),
  timeline: (v: string, id: string): Promise<TimelineResp> =>
    http<TimelineResp>(`/api/catalogue/${v}/subcaps/${id}/timeline`),
  kg: (v: string, subcap: string): Promise<KgResp> =>
    http<KgResp>(`/api/catalogue/${v}/kg?subcap=${encodeURIComponent(subcap)}`),
  kgDiscover: (v: string, limit = 24): Promise<KgDiscoverResp> =>
    http<KgDiscoverResp>(`/api/catalogue/${v}/kg/discover?limit=${limit}`),
  whatif: (v: string, subcap: string, action: string): Promise<WhatIfResp> =>
    http<WhatIfResp>(
      `/api/catalogue/${v}/whatif?subcap=${encodeURIComponent(subcap)}&action=${action}`,
    ),
  subcapEnrichment: (v: string, id: string): Promise<SubcapEnrichment> =>
    http<SubcapEnrichment>(`/api/catalogue/${v}/subcaps/${id}/enrichment`),
  subcapConnections: (v: string, id: string): Promise<SubcapConnections> =>
    http<SubcapConnections>(`/api/catalogue/${v}/subcaps/${id}/connections`),
  subcapOfferings: (v: string, id: string): Promise<SubcapOfferingCoverage> =>
    http<SubcapOfferingCoverage>(`/api/catalogue/${v}/subcaps/${id}/offerings`),
  platforms: (v: string): Promise<PlatformRow[]> =>
    http<PlatformRow[]>(`/api/catalogue/${v}/platforms`),
  platform: (v: string, id: string): Promise<PlatformDetail> =>
    http<PlatformDetail>(`/api/catalogue/${v}/platforms/${id}`),
  vendors: (v: string): Promise<VendorRow[]> => http<VendorRow[]>(`/api/catalogue/${v}/vendors`),
  vendorCell: (v: string, vendor: string, pillar: string): Promise<VendorCellSubcap[]> =>
    http<VendorCellSubcap[]>(
      `/api/catalogue/${v}/vendors/${encodeURIComponent(vendor)}/cell?pillar=${pillar}`,
    ),
  lifecycle: (v: string): Promise<LifecycleSummary> =>
    http<LifecycleSummary>(`/api/catalogue/${v}/lifecycle`),
  chat: (question: string, version: string): Promise<ChatResponse> =>
    http<ChatResponse>('/api/chat', { method: 'POST', body: JSON.stringify({ question, version }) }),
  reasoning: (chainId: string): Promise<ReasoningChain> =>
    http<ReasoningChain>(`/api/reasoning/${chainId}`),
  reasoningList: (limit = 50): Promise<ReasoningChainRow[]> =>
    http<ReasoningChainRow[]>(`/api/reasoning?limit=${limit}`),
  useCases: (v: string, p: UseCaseQuery): Promise<UseCasePage> => {
    const qs = new URLSearchParams();
    if (p.pillar) qs.set('pillar', p.pillar);
    if (p.category) qs.set('category', p.category);
    if (p.archetype) qs.set('archetype', p.archetype);
    if (p.q) qs.set('q', p.q);
    if (p.sort) qs.set('sort', p.sort);
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
    if (p.synthetic) qs.set('synthetic', p.synthetic);
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
  vendorIntel: (eventType?: string): Promise<VendorIntelResp> => {
    const qs = new URLSearchParams({ kind: 'vendor_event' });
    if (eventType && eventType !== 'all') qs.set('event_type', eventType);
    return http<VendorIntelResp>(`/api/evidence?${qs.toString()}`);
  },
  scanVendors: (version: string): Promise<VendorScanStats> =>
    http<VendorScanStats>(`/api/admin/evidence/scan/vendor/${version}`, { method: 'POST' }),
  vendorLoop: (id: string): Promise<NewsLoopOut> =>
    http<NewsLoopOut>(`/api/evidence/vendor/${id}/loop`, { method: 'POST' }),
  digest: (quarter?: string): Promise<DigestResp> =>
    http<DigestResp>('/api/digest' + (quarter && quarter !== 'latest' ? `?quarter=${quarter}` : '')),
  generateDigest: (quarter?: string): Promise<{ generated: boolean; quarter: string; reason?: string }> =>
    http('/api/admin/digest/generate', { method: 'POST', body: JSON.stringify({ quarter: quarter ?? null }) }),
  exportDigest: (quarter?: string): Promise<DigestExportOut> =>
    http('/api/exports/digest', { method: 'POST', body: JSON.stringify({ quarter: quarter ?? null }) }),
  provisionVersion: (version: string): Promise<Record<string, number | string>> =>
    http(`/api/admin/provision/${version}`, { method: 'POST' }),
  uploadCatalogue: async (version: string, file: File): Promise<UploadManifest> => {
    // multipart: let the browser set the boundary — our default JSON header must not apply
    const token = await getToken().catch(() => null);
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`/api/admin/catalogue/upload/${version}`, {
      method: 'POST',
      credentials: 'include',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      body: form,
    });
    if (!res.ok) {
      const body = (await res.json().catch(() => null)) as { error?: { message?: string } } | null;
      throw new Error(`${res.status}: ${body?.error?.message ?? res.statusText}`);
    }
    return res.json();
  },
  activateVersion: (version: string): Promise<{ ok: boolean; active: string }> =>
    http(`/api/admin/versions/${version}/activate`, { method: 'POST' }),
  carryForward: (version: string): Promise<Record<string, number | string>> =>
    http(`/api/admin/carry-forward/${version}`, { method: 'POST' }),
  admins: (): Promise<AdminRow[]> => http<AdminRow[]>('/api/admin/admins'),
  grantAdmin: (email: string, note?: string): Promise<{ ok: boolean; status: string }> =>
    http('/api/admin/admins', { method: 'POST', body: JSON.stringify({ email, note: note ?? '' }) }),
  revokeAdmin: (email: string): Promise<{ ok: boolean; status: string }> =>
    http(`/api/admin/admins/${encodeURIComponent(email)}`, { method: 'DELETE' }),
  sources: (): Promise<SourceRow[]> => http<SourceRow[]>('/api/admin/sources'),
  patchSource: (key: string, enabled: boolean): Promise<{ ok: boolean; enabled: boolean }> =>
    http<{ ok: boolean; enabled: boolean }>(`/api/admin/sources/${key}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),
  gates: (): Promise<GatesLog> => http<GatesLog>('/api/gates'),
  qaMetrics: (): Promise<QaMetrics> => http<QaMetrics>('/api/qa/metrics'),
  auditLog: (): Promise<AuditRow[]> => http<AuditRow[]>('/api/audit-log'),
  changeFlags: (status: string, severity?: string): Promise<ChangeFlagsResp> => {
    const qs = new URLSearchParams({ status });
    // severity=BLOCKING|HIGH|MED|LOW narrows the server-side list; the counts stay per-severity.
    if (severity && severity !== 'all') qs.set('severity', severity);
    return http<ChangeFlagsResp>(`/api/change-flags?${qs.toString()}`);
  },
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
