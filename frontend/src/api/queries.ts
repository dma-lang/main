// TanStack Query hooks. Catalogue reads are keyed by [resource, version] so a version switch refetches.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  api,
  type AuditRow,
  type CatalogueSummary,
  type ChatResponse,
  type GatesLog,
  type LifecycleSummary,
  type QaMetrics,
  type Me,
  type ReasoningChain,
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
  type VendorRow,
  type VersionInfo,
} from './client';

export const useMe = () => useQuery<Me>({ queryKey: ['me'], queryFn: api.me, retry: false });

export const useVersions = () =>
  useQuery<VersionInfo[]>({ queryKey: ['versions'], queryFn: api.versions });

export function usePatchPreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (prefs: Record<string, unknown>) => api.patchPreferences(prefs),
    onSuccess: (me) => qc.setQueryData(['me'], me),
  });
}

export const useSummary = (version: string) =>
  useQuery<CatalogueSummary>({
    queryKey: ['summary', version],
    queryFn: () => api.summary(version),
    enabled: !!version,
  });

export const useSubcaps = (version: string) =>
  useQuery<SubcapNode[]>({
    queryKey: ['subcaps', version],
    queryFn: () => api.subcaps(version),
    enabled: !!version,
  });

export const useSubcap = (version: string, id: string | null) =>
  useQuery<SubcapDetail>({
    queryKey: ['subcap', version, id],
    queryFn: () => api.subcap(version, id ?? ''),
    enabled: !!version && !!id,
  });

export const useSubcapStories = (version: string, id: string | null) =>
  useQuery<StoryPage>({
    queryKey: ['subcap-stories', version, id],
    queryFn: () => api.subcapStories(version, id ?? ''),
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

export const useSuggestions = (status: string) =>
  useQuery<SuggestionOut[]>({
    queryKey: ['suggestions', status],
    queryFn: () => api.suggestions(status),
  });

export const useGates = () => useQuery<GatesLog>({ queryKey: ['gates'], queryFn: api.gates });

export const useQaMetrics = () =>
  useQuery<QaMetrics>({ queryKey: ['qa-metrics'], queryFn: api.qaMetrics });

export const useAuditLog = () =>
  useQuery<AuditRow[]>({ queryKey: ['audit-log'], queryFn: api.auditLog });

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
