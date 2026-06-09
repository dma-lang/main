// TanStack Query hooks, keyed for cache correctness ([resource] now; [version, resource, filters]
// once version-scoped surfaces land in Stage 2).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, type Me, type VersionInfo } from './client';

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
