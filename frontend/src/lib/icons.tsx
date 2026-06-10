// Lucide-style line icons — the exact path set from the prototype (ui.jsx).
import type { CSSProperties } from 'react';

export const ICON = {
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
  compass: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20M16.2 7.8l-2.9 6.4-6.4 2.9 2.9-6.4z',
  layers: 'M12 2 2 7l10 5 10-5zM2 17l10 5 10-5M2 12l10 5 10-5',
  branch:
    'M6 3v12M18 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6M6 15a9 9 0 0 0 9-9',
  database:
    'M12 2c-4.4 0-8 1.3-8 3s3.6 3 8 3 8-1.3 8-3-3.6-3-8-3M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
  puzzle: 'M4 7h3a2 2 0 1 1 4 0h3v3a2 2 0 1 1 0 4v3h-3a2 2 0 1 0-4 0H4v-3a2 2 0 1 0 0-4z',
  activity: 'M3 12h4l3 8 4-16 3 8h4',
  file: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M9 13h6M9 17h6',
  book: 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z',
  route:
    'M6 19a3 3 0 1 0 0-6 3 3 0 0 0 0 6M18 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6M9 16h6a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6',
  news: 'M4 4h16v14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6h2zM8 8h8M8 12h8M8 16h5',
  trend: 'M3 17l6-6 4 4 8-8M15 7h6v6',
  sparkles:
    'M12 3l1.8 4.7L18.5 9 13.8 10.8 12 15.5l-1.8-4.7L5.5 9l4.7-1.3zM19 14l.9 2.3L22 17l-2.1.8L19 20l-.9-2.2L16 17l2.1-.7z',
  bars: 'M3 3v18h18M8 17V9M13 17V5M18 17v-6',
  brief: 'M4 7h16v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zM9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2',
  package: 'M12 2 3 7v10l9 5 9-5V7zM3 7l9 5 9-5M12 22V12',
  building: 'M4 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18M4 22h16M9 7h2M9 11h2M9 15h2',
  clock: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20M12 7v5l3 2',
  compare:
    'M5 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6M5 8v8a3 3 0 0 0 3 3h5M19 16a3 3 0 1 0 0 6 3 3 0 0 0 0-6M19 16V8a3 3 0 0 0-3-3h-5',
  flag: 'M4 22V4M4 4l2-1h9l-1 4h6l-2 5 2 5H6l-2 1',
  shield: 'M12 2 4 5v6c0 5 3.4 8.5 8 10 4.6-1.5 8-5 8-10V5zM9 12l2 2 4-4',
  check: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20M8 12l3 3 5-6',
  chat: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z',
  graph:
    'M5 6a3 3 0 1 0 0-6 3 3 0 0 0 0 6M19 24a3 3 0 1 0 0-6 3 3 0 0 0 0 6M5 18a3 3 0 1 0 0-6 3 3 0 0 0 0 6M8 4h8a3 3 0 0 1 3 3v8',
  beaker: 'M9 2v6L4 18a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3L15 8V2M9 2h6M7 14h10',
  gear: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M19 12l2-1-2-4-2 1a7 7 0 0 0-2-1l-.5-2h-5L9 5a7 7 0 0 0-2 1L5 5 3 9l2 1a7 7 0 0 0 0 2l-2 1 2 4 2-1a7 7 0 0 0 2 1l.5 2h5l.5-2a7 7 0 0 0 2-1l2 1 2-4-2-1a7 7 0 0 0 0-2z',
  upload: 'M12 15V3M7 8l5-5 5 5M5 15v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14M21 21l-5-5',
  chevR: 'M9 6l6 6-6 6',
  chevD: 'M6 9l6 6 6-6',
  chevL: 'M15 6l-6 6 6 6',
  sun: 'M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
  moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z',
  bell: 'M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0',
  x: 'M18 6 6 18M6 6l12 12',
  refresh: 'M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5',
  ext: 'M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6',
  plus: 'M12 5v14M5 12h14',
  lock: 'M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4',
  zap: 'M13 2 4 14h7l-1 8 9-12h-7z',
  alert: 'M12 2 2 20h20zM12 9v4M12 17h.01',
  arrowR: 'M5 12h14M13 6l6 6-6 6',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6',
  filter: 'M3 4h18l-7 8v6l-4 2v-8z',
  dot: 'M12 12m-3 0a3 3 0 1 0 6 0 3 3 0 1 0-6 0',
  google:
    'M21.8 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.5a4.7 4.7 0 0 1-2 3.1v2.6h3.3c1.9-1.8 3-4.4 3-7.5M12 22c2.7 0 5-1 6.7-2.5l-3.3-2.6c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3v2.6A10 10 0 0 0 12 22M6.4 13.8a6 6 0 0 1 0-3.6V7.6H3a10 10 0 0 0 0 8.8M12 6c1.5 0 2.8.5 3.8 1.5l2.9-2.9A10 10 0 0 0 3 7.6l3.4 2.6C7.2 7.9 9.4 6 12 6',
  arrowUp: 'M12 19V5M5 12l7-7 7 7',
  arrowDown: 'M12 5v14M5 12l7 7 7-7',
} as const;

export type IconName = keyof typeof ICON;

export function Icon({
  n,
  s = 18,
  sw = 1.7,
  style,
  cls,
}: {
  n: IconName;
  s?: number;
  sw?: number;
  style?: CSSProperties;
  cls?: string;
}) {
  const solid = n === 'dot' || n === 'google';
  return (
    <svg
      width={s}
      height={s}
      viewBox="0 0 24 24"
      fill={solid ? 'currentColor' : 'none'}
      stroke={solid ? 'none' : 'currentColor'}
      strokeWidth={sw}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
      className={cls}
      aria-hidden="true"
    >
      <path d={ICON[n]} />
    </svg>
  );
}
