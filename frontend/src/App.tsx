// App entry: query provider + auth gate. /api/me drives identity (is_admin, preferences); on 401 the
// Login screen shows (hermetic dev auto-authenticates). Preferences hydrate the UI store on load.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect } from 'react';
import { RouterProvider } from 'react-router-dom';

import { useMe, useVersions } from './api/queries';
import { Login } from './Login';
import { router } from './router';
import { useUi } from './state/store';

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: false } },
});

function Gate() {
  const me = useMe();
  const versions = useVersions();
  const hydrate = useUi((s) => s.hydrateFromMe);
  const version = useUi((s) => s.version);
  const setVersion = useUi((s) => s.setVersion);

  useEffect(() => {
    if (me.data) hydrate(me.data.preferences, me.data.is_admin);
  }, [me.data, hydrate]);

  useEffect(() => {
    const vs = versions.data;
    if (vs && vs.length > 0 && !version) setVersion(vs[0].version_id);
  }, [versions.data, version, setVersion]);

  if (me.isLoading) {
    return (
      <div className="muted" style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
        Loading…
      </div>
    );
  }
  if (me.isError || !me.data) {
    return <Login onRetry={() => void me.refetch()} />;
  }
  return <RouterProvider router={router} />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Gate />
    </QueryClientProvider>
  );
}
