// Hash router (matches the prototype's #/ scheme; `go()` drives it). Live surfaces replace the
// placeholder as they land in Stage 2; the rest route to the placeholder.
import type { ReactElement } from 'react';
import { createHashRouter, Navigate } from 'react-router-dom';

import { Benchmarks } from './pages/Benchmarks';
import { CapabilityWorkbench } from './pages/CapabilityWorkbench';
import { ChangeFlags } from './pages/ChangeFlags';
import { Clients } from './pages/Clients';
import { Diff } from './pages/Diff';
import { Digest } from './pages/Digest';
import { Chat } from './pages/Chat';
import { Gates } from './pages/Gates';
import { KnowledgeGraph } from './pages/KnowledgeGraph';
import { Lifecycle } from './pages/Lifecycle';
import { Login } from './pages/Login';
import { MissionControl } from './pages/MissionControl';
import { News } from './pages/News';
import { Onboarding } from './pages/Onboarding';
import { Platforms } from './pages/Platforms';
import { QA } from './pages/QA';
import { Reasoning } from './pages/Reasoning';
import { SchemaMapping } from './pages/SchemaMapping';
import { Settings } from './pages/Settings';
import { Sow } from './pages/Sow';
import { StoryLibrary } from './pages/StoryLibrary';
import { SubcapWorkbench } from './pages/SubcapWorkbench';
import { Suggestions } from './pages/Suggestions';
import { Surface } from './pages/Surface';
import { Trace } from './pages/Trace';
import { Trends } from './pages/Trends';
import { UseCases } from './pages/UseCases';
import { ValueChain } from './pages/ValueChain';
import { Vendors } from './pages/Vendors';
import { VersionTimeline } from './pages/VersionTimeline';
import { WhatIf } from './pages/WhatIf';
import { NAV } from './shell/nav';
import { Shell } from './shell/Shell';

const navIds = [...new Set(NAV.flatMap((g) => g.items.map((it) => it.r)))];
const accessIds = ['settings', 'schema-mapping', 'onboarding', 'subcap'];

const LIVE: Record<string, ReactElement> = {
  'mission-control': <MissionControl />,
  explorer: <CapabilityWorkbench />,
  'value-chain': <ValueChain />,
  'change-flags': <ChangeFlags />,
  'knowledge-graph': <KnowledgeGraph />,
  subcap: <SubcapWorkbench />,
  versions: <VersionTimeline />,
  diff: <Diff />,
  platforms: <Platforms />,
  'use-cases': <UseCases />,
  stories: <StoryLibrary />,
  sow: <Sow />,
  trace: <Trace />,
  clients: <Clients />,
  lifecycle: <Lifecycle />,
  chat: <Chat />,
  reasoning: <Reasoning />,
  news: <News />,
  trends: <Trends />,
  benchmarks: <Benchmarks />,
  suggestions: <Suggestions />,
  digest: <Digest />,
  vendors: <Vendors />,
  settings: <Settings />,
  'schema-mapping': <SchemaMapping />,
  onboarding: <Onboarding />,
  'what-if': <WhatIf />,
  gates: <Gates />,
  qa: <QA />,
};

export const router = createHashRouter([
  { path: '/login', element: <Login /> },
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
      { path: 'trace/:id', element: <Trace /> },
      { path: '*', element: <Surface id="not-found" /> },
    ],
  },
]);
