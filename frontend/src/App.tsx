// App entry: query provider + auth gate. /api/me drives identity (is_admin, preferences); on 401 the
// Login screen shows (hermetic dev auto-authenticates). Preferences hydrate the UI store on load.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect } from 'react';
import { RouterProvider } from 'react-router-dom';

import { useMe } from './api/queries';
import { Login } from './Login';
import { router } from './router';
import { useUi } from './state/store';

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: false } },
});

function Gate() {
  const me = useMe();
  const hydrate = useUi((s) => s.hydrateFromMe);

  useEffect(() => {
    if (me.data) hydrate(me.data.preferences, me.data.is_admin);
  }, [me.data, hydrate]);

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
