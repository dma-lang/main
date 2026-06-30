// TanStack Query hooks. Catalogue reads are keyed by [resource, version] so a version switch refetches.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  api,
  type AdminRow,
  type AuditRow,
  type BenchResp,
  type CatalogueSummary,
  type ClientJourney,
  type ClientRow,
  type DiffResp,
  type HeatmapResp,
  type HeatmapDrillResp,
  type OfferingDetail,
  type UnscopedSubverticalsResp,
  type MappingResp,
  type SowDetail,
  type SowDoc,
  type KgResp,
  type TimelineResp,
  type WhatIfResp,
  type ChangeFlagsResp,
  type ChatResponse,
  type DeliveryDrill,
  type GatesLog,
  type LifecycleSummary,
  type QaMetrics,
  type Me,
  type DigestResp,
  type NewsResp,
  type SourceRow,
  type TrendsResp,
  type VendorIntelResp,
  type ReasoningChain,
  type ReasoningChainRow,
  type PlatformDetail,
  type PlatformRow,
  type StoryPage,
  type SubcapDetail,
  type SubcapEnrichment,
  type StoryLibraryPage,
  type StoryLibraryQuery,
  type SubcapConnections,
  type SuggestionOut,
  type SubcapNode,
  type UseCasePage,
  type UseCaseQuery,
  type VendorCellSubcap,
  type VendorRow,
  type VersionInfo,
} from './client';

// Identity changes only through explicit sign-in/sign-out — never refetch it on window focus or
// reconnect. (The focus refetch raced the Google sign-in popup: it fired token-less the moment
// the popup closed, and its stale 401 could land AFTER the fresh identity, bouncing the gate
// straight back to the Login page.)
export const useMe = () =>
  useQuery<Me>({
    queryKey: ['me'],
    queryFn: api.me,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

export const useVersions = () =>
  useQuery<VersionInfo[]>({ queryKey: ['versions'], queryFn: api.versions });

export function usePatchPreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (prefs: Record<string, unknown>) => api.patchPreferences(prefs),
    onSuccess: (me) => qc.setQueryData(['me'], me),
  });
}

export const useSummary = (version: string, sv = 'all') =>
  useQuery<CatalogueSummary>({
    queryKey: ['summary', version, sv],
    queryFn: () => api.summary(version, sv),
    enabled: !!version,
  });

export const useHeatmap = (version: string, lens: string, pillar: string, sv: string) =>
  useQuery<HeatmapResp>({
    queryKey: ['heatmap', version, lens, pillar, sv],
    queryFn: () => api.heatmap(version, lens, pillar, sv),
    enabled: !!version,
  });

// The subcaps behind a heatmap lens-group row — Mission control's drill drawer. Only fetched once a
// non-pillar row is clicked (key set); pillar rows peek their subcap directly so no drill is needed.
export const useHeatmapDrill = (
  version: string,
  lens: string,
  key: string | null,
  pillar: string,
  sv: string,
) =>
  useQuery<HeatmapDrillResp>({
    queryKey: ['heatmap-drill', version, lens, key, pillar, sv],
    queryFn: () => api.heatmapDrill(version, lens, key as string, pillar, sv),
    enabled: !!version && !!key && lens !== 'pillar',
  });

// One productized offering's drilldown — its capabilities + the subcaps the semantic matcher mapped
// to it (scored, peekable). Fetched only when an offering chip is opened (id set).
export const useOfferingDetail = (version: string, id: string | null) =>
  useQuery<OfferingDetail>({
    queryKey: ['offering-detail', version, id],
    queryFn: () => api.offeringDetail(version, id as string),
    enabled: !!version && !!id,
  });

export const useUnscopedSubverticals = (version: string) =>
  useQuery<UnscopedSubverticalsResp>({
    queryKey: ['unscoped-subverticals', version],
    queryFn: () => api.unscopedSubverticals(version),
    enabled: !!version,
  });

export const useTimeline = (version: string, id: string | null) =>
  useQuery<TimelineResp>({
    queryKey: ['timeline', version, id],
    queryFn: () => api.timeline(version, id ?? ''),
    enabled: !!version && !!id,
  });

export const useKg = (version: string, subcap: string | null) =>
  useQuery<KgResp>({
    queryKey: ['kg', version, subcap],
    queryFn: () => api.kg(version, subcap ?? ''),
    enabled: !!version && !!subcap,
  });

export const useWhatIf = (version: string, subcap: string, action: string, enabled: boolean) =>
  useQuery<WhatIfResp>({
    queryKey: ['whatif', version, subcap, action],
    queryFn: () => api.whatif(version, subcap, action),
    enabled: enabled && !!version && !!subcap,
  });

export const useSows = (version: string) =>
  useQuery<SowDoc[]>({
    queryKey: ['sows', version],
    queryFn: () => api.sows(version),
    enabled: !!version,
  });

export const useSowDetail = (id: string | null, version: string) =>
  useQuery<SowDetail>({
    queryKey: ['sow', id, version],
    queryFn: () => api.sowDetail(id ?? '', version),
    enabled: !!id && !!version,
  });

export function useSowActions() {
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['sows'] });
    void qc.invalidateQueries({ queryKey: ['sow'] });
    void qc.invalidateQueries({ queryKey: ['clients'] });
  };
  const scan = useMutation({ mutationFn: api.scanSows, onSuccess: invalidate });
  const confirm = useMutation({ mutationFn: api.confirmSowMatch, onSuccess: invalidate });
  return { scan, confirm };
}

export const useClients = (version: string) =>
  useQuery<ClientRow[]>({
    queryKey: ['clients', version],
    queryFn: () => api.clients(version),
    enabled: !!version,
  });

export const useMapping = (version: string | null) =>
  useQuery<MappingResp>({
    queryKey: ['mapping', version],
    queryFn: () => api.mapping(version ?? ''),
    enabled: !!version,
    retry: false, // an unprovisioned version is a designed 404 state
  });

export const useClientJourney = (key: string | null, version: string) =>
  useQuery<ClientJourney>({
    queryKey: ['client-journey', key, version],
    queryFn: () => api.clientJourney(key ?? '', version),
    enabled: !!key && !!version,
  });

export const useDiff = (a: string, b: string) =>
  useQuery<DiffResp>({
    queryKey: ['diff', a, b],
    queryFn: () => api.diff(a, b),
    enabled: !!a && !!b,
    retry: false, // an unprovisioned version is a designed 404 state, not a retryable fault
  });

export const useSubcaps = (version: string, sv = 'all') =>
  useQuery<SubcapNode[]>({
    queryKey: ['subcaps', version, sv],
    queryFn: () => api.subcaps(version, sv),
    enabled: !!version,
  });

export const useValueChain = (version: string, pillar: string, sv: string) =>
  useQuery({
    queryKey: ['value-chain', version, pillar, sv],
    queryFn: () => api.valueChain(version, pillar, sv),
    enabled: !!version,
    placeholderData: (prev) => prev,
  });

export const useSubcap = (version: string, id: string | null) =>
  useQuery<SubcapDetail>({
    queryKey: ['subcap', version, id],
    queryFn: () => api.subcap(version, id ?? ''),
    enabled: !!version && !!id,
  });

export const useSubcapStories = (version: string, id: string | null, synthetic = false) =>
  useQuery<StoryPage>({
    queryKey: ['subcap-stories', version, id, synthetic],
    queryFn: () => api.subcapStories(version, id ?? '', 1, 8, synthetic),
    enabled: !!version && !!id,
  });

// the Jira stories MATCHED to a specific use case (story->use-case), for the Use Case drawer
export const useUseCaseStories = (version: string, useCaseId: string | null) =>
  useQuery<StoryPage>({
    queryKey: ['use-case-stories', version, useCaseId],
    queryFn: () => api.useCaseStories(version, useCaseId ?? '', 1, 12),
    enabled: !!version && !!useCaseId,
  });

export const useSubcapDelivery = (version: string, id: string | null, synthetic = false) =>
  useQuery<DeliveryDrill>({
    queryKey: ['subcap-delivery', version, id, synthetic],
    queryFn: () => api.subcapDelivery(version, id ?? '', synthetic),
    enabled: !!version && !!id,
  });

export const useSubcapEnrichment = (version: string, id: string | null) =>
  useQuery<SubcapEnrichment>({
    queryKey: ['subcap-enrichment', version, id],
    queryFn: () => api.subcapEnrichment(version, id ?? ''),
    enabled: !!version && !!id,
  });

export const useSubcapConnections = (version: string, id: string | null) =>
  useQuery<SubcapConnections>({
    queryKey: ['subcap-connections', version, id],
    queryFn: () => api.subcapConnections(version, id ?? ''),
    enabled: !!version && !!id,
  });

export const usePlatforms = (version: string) =>
  useQuery<PlatformRow[]>({
    queryKey: ['platforms', version],
    queryFn: () => api.platforms(version),
    enabled: !!version,
  });

export const useVendors = (version: string) =>
  useQuery<VendorRow[]>({
    queryKey: ['vendors', version],
    queryFn: () => api.vendors(version),
    enabled: !!version,
  });

export const usePlatform = (version: string, id: string | null) =>
  useQuery<PlatformDetail>({
    queryKey: ['platform', version, id],
    queryFn: () => api.platform(version, id ?? ''),
    enabled: !!version && !!id,
  });

export const useVendorCell = (version: string, vendor: string | null, pillar: string | null) =>
  useQuery<VendorCellSubcap[]>({
    queryKey: ['vendorCell', version, vendor, pillar],
    queryFn: () => api.vendorCell(version, vendor ?? '', pillar ?? ''),
    enabled: !!version && !!vendor && !!pillar,
  });

export const useLifecycle = (version: string) =>
  useQuery<LifecycleSummary>({
    queryKey: ['lifecycle', version],
    queryFn: () => api.lifecycle(version),
    enabled: !!version,
  });

export const useChat = () =>
  useMutation<ChatResponse, Error, { question: string; version: string }>({
    mutationFn: ({ question, version }) => api.chat(question, version),
  });

export const useReasoning = (chainId: string | null) =>
  useQuery<ReasoningChain>({
    queryKey: ['reasoning', chainId],
    queryFn: () => api.reasoning(chainId ?? ''),
    enabled: !!chainId,
  });

export const useReasoningList = (limit = 50) =>
  useQuery<ReasoningChainRow[]>({
    queryKey: ['reasoning-list', limit],
    queryFn: () => api.reasoningList(limit),
  });

export const useSuggestions = (status: string) =>
  useQuery<SuggestionOut[]>({
    queryKey: ['suggestions', status],
    queryFn: () => api.suggestions(status),
  });

export const useNews = (impact: string, tier: string) =>
  useQuery<NewsResp>({
    queryKey: ['news', impact, tier],
    queryFn: () => api.news(impact, tier),
    placeholderData: (prev) => prev,
  });

export function useNewsActions() {
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['news'] });
    void qc.invalidateQueries({ queryKey: ['suggestions'] });
    void qc.invalidateQueries({ queryKey: ['change-flags'] });
  };
  const scan = useMutation({ mutationFn: api.scanNews, onSuccess: invalidate });
  const loop = useMutation({ mutationFn: api.newsLoop, onSuccess: invalidate });
  return { scan, loop };
}

export const useBenchmarks = (segment: string) =>
  useQuery<BenchResp>({
    queryKey: ['benchmarks', segment],
    queryFn: () => api.benchmarks(segment),
    placeholderData: (prev) => prev,
  });

export function useBenchmarkActions() {
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['benchmarks'] });
    void qc.invalidateQueries({ queryKey: ['suggestions'] });
    void qc.invalidateQueries({ queryKey: ['change-flags'] });
  };
  const scan = useMutation({ mutationFn: api.scanBenchmarks, onSuccess: invalidate });
  const loop = useMutation({ mutationFn: api.benchmarkLoop, onSuccess: invalidate });
  return { scan, loop };
}

export const useDigest = (quarter: string) =>
  useQuery<DigestResp>({
    queryKey: ['digest', quarter],
    queryFn: () => api.digest(quarter),
    placeholderData: (prev) => prev,
  });

export function useDigestActions() {
  const qc = useQueryClient();
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['digest'] });
  const generate = useMutation({ mutationFn: api.generateDigest, onSuccess: invalidate });
  const exportIt = useMutation({ mutationFn: api.exportDigest, onSuccess: invalidate });
  return { generate, exportIt };
}

export const useVendorIntel = (eventType: string) =>
  useQuery<VendorIntelResp>({
    queryKey: ['vendor-intel', eventType],
    queryFn: () => api.vendorIntel(eventType),
    placeholderData: (prev) => prev,
  });

export function useVendorActions() {
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['vendor-intel'] });
    void qc.invalidateQueries({ queryKey: ['suggestions'] });
    void qc.invalidateQueries({ queryKey: ['change-flags'] });
  };
  const scan = useMutation({ mutationFn: api.scanVendors, onSuccess: invalidate });
  const loop = useMutation({ mutationFn: api.vendorLoop, onSuccess: invalidate });
  return { scan, loop };
}

export function useProvisionActions() {
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries();
  };
  const provision = useMutation({ mutationFn: (v: string) => api.provisionVersion(v), onSuccess: invalidate });
  const carry = useMutation({ mutationFn: (v: string) => api.carryForward(v), onSuccess: invalidate });
  const activate = useMutation({ mutationFn: (v: string) => api.activateVersion(v), onSuccess: invalidate });
  return { provision, carry, activate };
}

export const useAdmins = (enabled: boolean) =>
  useQuery<AdminRow[]>({ queryKey: ['admins'], queryFn: api.admins, enabled });

export function useAdminActions() {
  const qc = useQueryClient();
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['admins'] });
  const grant = useMutation({
    mutationFn: (a: { email: string; note?: string }) => api.grantAdmin(a.email, a.note),
    onSuccess: invalidate,
  });
  const revoke = useMutation({ mutationFn: (email: string) => api.revokeAdmin(email), onSuccess: invalidate });
  return { grant, revoke };
}

export const useSources = (enabled: boolean) =>
  useQuery<SourceRow[]>({
    queryKey: ['admin-sources'],
    queryFn: api.sources,
    enabled,
  });

export function useSourceActions() {
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: (a: { key: string; enabled: boolean }) => api.patchSource(a.key, a.enabled),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin-sources'] }),
  });
  return { toggle };
}

export const useTrends = (status: string, version: string | null) =>
  useQuery<TrendsResp>({
    queryKey: ['trends', status, version],
    queryFn: () => api.trends(status, version ?? undefined),
    placeholderData: (prev) => prev,
    enabled: !!version,
  });

export function useTrendsActions() {
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['trends'] });
    void qc.invalidateQueries({ queryKey: ['suggestions'] });
    void qc.invalidateQueries({ queryKey: ['change-flags'] });
  };
  const scan = useMutation({ mutationFn: api.scanTrends, onSuccess: invalidate });
  const loop = useMutation({ mutationFn: api.trendLoop, onSuccess: invalidate });
  const feedback = useMutation({
    mutationFn: (a: { id: string; verdict: string }) => api.trendFeedback(a.id, a.verdict),
    onSuccess: invalidate,
  });
  return { scan, loop, feedback };
}

export const useGates = () => useQuery<GatesLog>({ queryKey: ['gates'], queryFn: api.gates });

export const useQaMetrics = (enabled = true) =>
  useQuery<QaMetrics>({ queryKey: ['qa-metrics'], queryFn: api.qaMetrics, enabled });

export const useAuditLog = () =>
  useQuery<AuditRow[]>({ queryKey: ['audit-log'], queryFn: api.auditLog });

export const useChangeFlags = (status = 'open') =>
  useQuery<ChangeFlagsResp>({
    queryKey: ['change-flags', status],
    queryFn: () => api.changeFlags(status),
  });

export function useFlagActions() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ['change-flags'] });
  const scan = useMutation({ mutationFn: api.scanFlags, onSuccess: invalidate });
  const approve = useMutation({ mutationFn: api.approveFlag, onSuccess: invalidate });
  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => api.rejectFlag(id, reason),
    onSuccess: invalidate,
  });
  const defer = useMutation({ mutationFn: api.deferFlag, onSuccess: invalidate });
  return { scan, approve, reject, defer };
}

export function useSuggestionActions() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ['suggestions'] });
  const propose = useMutation({ mutationFn: api.proposeSuggestions, onSuccess: invalidate });
  const apply = useMutation({ mutationFn: api.applySuggestion, onSuccess: invalidate });
  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => api.rejectSuggestion(id, reason),
    onSuccess: invalidate,
  });
  return { propose, apply, reject };
}

export const useUseCases = (version: string, params: UseCaseQuery) =>
  useQuery<UseCasePage>({
    queryKey: ['use-cases', version, params],
    queryFn: () => api.useCases(version, params),
    enabled: !!version,
    placeholderData: (prev) => prev,
  });

export const useStoryLibrary = (params: StoryLibraryQuery) =>
  useQuery<StoryLibraryPage>({
    queryKey: ['story-library', params],
    queryFn: () => api.stories(params),
    placeholderData: (prev) => prev,
  });
