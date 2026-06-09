// Hash router (matches the prototype's #/ scheme; `go()` drives it). Every surface routes to the
// placeholder for now; Stage 2 swaps in the live, data-wired page components.
import { createHashRouter, Navigate } from 'react-router-dom';

import { Surface } from './pages/Surface';
import { NAV } from './shell/nav';
import { Shell } from './shell/Shell';

const navIds = [...new Set(NAV.flatMap((g) => g.items.map((it) => it.r)))];
const accessIds = ['settings', 'schema-mapping', 'onboarding', 'subcap'];

export const router = createHashRouter([
  {
    path: '/',
    element: <Shell />,
    children: [
      { index: true, element: <Navigate to="/mission-control" replace /> },
      ...[...navIds, ...accessIds].map((id) => ({ path: id, element: <Surface id={id} /> })),
      { path: 'subcap/:id', element: <Surface id="subcap" /> },
      { path: '*', element: <Surface id="not-found" /> },
    ],
  },
]);
