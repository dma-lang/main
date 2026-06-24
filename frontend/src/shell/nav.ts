// The 9-group sidebar (A-I) — verbatim from the prototype shell.jsx NAV constant.
import type { IconName } from '../lib/icons';

export interface NavItem {
  r: string;
  t: string;
  i: IconName;
  admin?: boolean;
  phase?: number;
  match?: string;
}

export interface NavGroup {
  g: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    g: 'A · Explore',
    items: [
      { r: 'mission-control', t: 'Mission control', i: 'grid' },
      { r: 'explorer', t: 'Capability workbench', i: 'compass', match: 'subcap' },
      { r: 'value-chain', t: 'Value chain atlas', i: 'route' },
    ],
  },
  {
    g: 'B · Catalogue tools',
    items: [
      { r: 'platforms', t: 'Platform catalog', i: 'database' },
      { r: 'use-cases', t: 'Use case explorer', i: 'puzzle' },
      { r: 'knowledge-graph', t: 'Knowledge graph', i: 'graph', admin: true },
    ],
  },
  {
    g: 'C · Project validation',
    items: [
      { r: 'sow', t: 'SOW library', i: 'file', phase: 2 },
      { r: 'stories', t: 'Story library', i: 'book' },
      { r: 'trace', t: 'Project-subcap trace', i: 'branch', phase: 2 },
    ],
  },
  {
    g: 'D · Public intelligence',
    items: [
      { r: 'news', t: 'News watch', i: 'news', phase: 2 },
      { r: 'trends', t: 'Trends monitor', i: 'trend', phase: 2 },
      { r: 'suggestions', t: 'AI suggestions', i: 'sparkles', phase: 2 },
      { r: 'benchmarks', t: 'Benchmarks studio', i: 'bars', phase: 2, admin: true },
    ],
  },
  {
    g: 'E · Strategic synthesis',
    items: [{ r: 'digest', t: 'Quarterly digest', i: 'brief', phase: 2 }],
  },
  {
    g: 'F · Lifecycle & competition',
    items: [
      { r: 'lifecycle', t: 'Lifecycle manager', i: 'package', phase: 2 },
      { r: 'vendors', t: 'Vendor intelligence', i: 'building', phase: 2 },
      { r: 'clients', t: 'Client journey atlas', i: 'route', phase: 3 },
    ],
  },
  {
    g: 'G · Versioning & QA',
    items: [
      { r: 'versions', t: 'Version timeline', i: 'clock', admin: true },
      { r: 'diff', t: 'Diff viewer', i: 'compare', admin: true },
      { r: 'change-flags', t: 'Change flags inbox', i: 'flag', phase: 2, admin: true },
      { r: 'gates', t: 'Validation gates log', i: 'shield', phase: 2, admin: true },
      { r: 'qa', t: 'QA & audit dashboard', i: 'check', phase: 2, admin: true },
    ],
  },
  {
    g: 'H · Reasoning & RAG',
    items: [
      { r: 'reasoning', t: 'Reasoning chain viewer', i: 'sparkles', phase: 2, admin: true },
      { r: 'chat', t: 'AI chat', i: 'chat', phase: 2 },
    ],
  },
  {
    g: 'I · Sandbox',
    items: [{ r: 'what-if', t: 'What-if simulator', i: 'beaker', phase: 3, admin: true }],
  },
];
