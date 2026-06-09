// Hash router (matches the prototype's #/ scheme; `go()` drives it). Live surfaces replace the
// placeholder as they land in Stage 2; the rest route to the placeholder.
import type { ReactElement } from 'react';
import { createHashRouter, Navigate } from 'react-router-dom';

import { CapabilityWorkbench } from './pages/CapabilityWorkbench';
import { Lifecycle } from './pages/Lifecycle';
import { MissionControl } from './pages/MissionControl';
import { Platforms } from './pages/Platforms';
import { StoryLibrary } from './pages/StoryLibrary';
import { SubcapWorkbench } from './pages/SubcapWorkbench';
import { Surface } from './pages/Surface';
import { UseCases } from './pages/UseCases';
import { VersionTimeline } from './pages/VersionTimeline';
import { NAV } from './shell/nav';
import { Shell } from './shell/Shell';

const navIds = [...new Set(NAV.flatMap((g) => g.items.map((it) => it.r)))];
const accessIds = ['settings', 'schema-mapping', 'onboarding', 'subcap'];

const LIVE: Record<string, ReactElement> = {
  'mission-control': <MissionControl />,
  explorer: <CapabilityWorkbench />,
  subcap: <SubcapWorkbench />,
  versions: <VersionTimeline />,
  platforms: <Platforms />,
  'use-cases': <UseCases />,
  stories: <StoryLibrary />,
  lifecycle: <Lifecycle />,
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
      { path: 'subcap/:id', element: <SubcapWorkbench /> },
      { path: 'platforms/:id', element: <Platforms /> },
      { path: '*', element: <Surface id="not-found" /> },
    ],
  },
]);
