// App entry: query provider + auth gate. /api/me drives identity (is_admin, preferences); while it
// errors (no/expired session in live auth, service unavailable) the REAL brand-split Login page
// renders — its sign-in writes the fresh identity into the ['me'] cache, which flips this gate.
// Hermetic dev auto-authenticates. Nothing but /api/config and /api/me is called pre-auth.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { RouterProvider } from 'react-router-dom';

import type { Me } from './api/client';
import { useMe, useVersions } from './api/queries';
import { Login } from './pages/Login';
import { router } from './router';
import { useUi } from './state/store';

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: false } },
});

function Authed({ me }: { me: Me }) {
  const versions = useVersions();
  const hydrate = useUi((s) => s.hydrateFromMe);
  const version = useUi((s) => s.version);
  const setVersion = useUi((s) => s.setVersion);
  const hydrated = useRef(false);

  // Seed the store from server preferences exactly once, on the first successful /api/me load.
  // Re-running on every me change (e.g. a PATCH response) would clobber the user's in-session
  // theme/lens/persona changes, so we guard with a ref.
  useEffect(() => {
    if (!hydrated.current) {
      hydrated.current = true;
      hydrate(me.preferences, me.is_admin);
    }
  }, [me, hydrate]);

  useEffect(() => {
    const vs = versions.data;
    // Default to the MOST RECENT catalogue version — highest version number, not latest
    // provisioned row (re-provisioning legacy v5 must never steal the default from v7).
    if (vs && vs.length > 0 && !version) {
      const newest = [...vs].sort(
        (a, b) =>
          (parseInt(b.version_id.replace(/\D/g, ''), 10) || 0) -
          (parseInt(a.version_id.replace(/\D/g, ''), 10) || 0),
      )[0];
      setVersion(newest.version_id);
    }
  }, [versions.data, version, setVersion]);

  return <RouterProvider router={router} />;
}

function Gate() {
  const me = useMe();

  if (me.isLoading) {
    return (
      <div className="muted" style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
        Loading…
      </div>
    );
  }
  if (me.isError || !me.data) {
    return <Login />;
  }
  return <Authed me={me.data} />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Gate />
    </QueryClientProvider>
  );
}
