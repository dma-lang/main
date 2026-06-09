// Hash router (matches the prototype's #/ scheme; `go()` drives it). Live surfaces replace the
// placeholder as they land in Stage 2; the rest route to the placeholder.
import type { ReactElement } from 'react';
import { createHashRouter, Navigate } from 'react-router-dom';

import { CapabilityWorkbench } from './pages/CapabilityWorkbench';
import { MissionControl } from './pages/MissionControl';
import { Surface } from './pages/Surface';
import { NAV } from './shell/nav';
import { Shell } from './shell/Shell';

const navIds = [...new Set(NAV.flatMap((g) => g.items.map((it) => it.r)))];
const accessIds = ['settings', 'schema-mapping', 'onboarding', 'subcap'];

const LIVE: Record<string, ReactElement> = {
  'mission-control': <MissionControl />,
  explorer: <CapabilityWorkbench />,
};

export const router = createHashRouter([
  {
    path: '/',
    element: <Shell />,
    children: [
      { index: true, element: <Navigate to="/mission-control" replace /> },
      ...[...navIds, ...accessIds].map((id) => ({
        path: id,
        element: LIVE[id] ?? <Surface id={id} />,
      })),
      { path: 'subcap/:id', element: <Surface id="subcap" /> },
      { path: '*', element: <Surface id="not-found" /> },
    ],
  },
]);
