// TanStack Query hooks. Catalogue reads are keyed by [resource, version] so a version switch refetches.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  api,
  type CatalogueSummary,
  type Me,
  type SubcapDetail,
  type SubcapNode,
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
