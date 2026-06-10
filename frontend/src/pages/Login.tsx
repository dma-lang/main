// Login (access) — plain Google sign-in (Google Identity Services), @zennify.com, fails closed.
// NO Firebase: Google renders its own official button (no custom popup → no popup-blocked
// failures); its callback hands us a Google ID token, the backend verifies signature + audience +
// domain. Layout/copy mirror the prototype's Login (dark brand panel: hero image, logo, promise
// list; right: sign-in card). Real states: config loading/error (Retry), sign-in not configured
// (GOOGLE_CLIENT_ID missing — actionable), dev-identity, domain-rejected (server 403 — honest,
// with sign-out), db-not-ready (503 → run the migration job).
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { api } from '../api/client';
import {
  type ClientConfig,
  loadConfig,
  prewarmAuth,
  renderGoogleButton,
  signOutUser,
} from '../lib/auth';
import { Icon } from '../lib/icons';
import { APP_VERSION } from '../version';

type Phase = 'loading' | 'ready' | 'signing' | 'rejected' | 'error';

const PROMISES: [string, string][] = [
  [
    'Trust-first',
    'Every AI output carries a claim label, its sources, and a reasoning trail you can open.',
  ],
  [
    'One living catalogue',
    '851 subcaps across 4 pillars, kept current from SOWs, news and vendor signals.',
  ],
  [
    'Evidence, not opinion',
    'Suggestions are gated by 8 deterministic checks before a human ever sees them.',
  ],
];

/** Map a sign-in/api failure to the phase + actionable message the operator needs. */
function mapError(e: unknown): { phase: Phase; detail: string } {
  const msg = String((e as Error)?.message ?? e);
  if (msg.startsWith('503') || msg.startsWith('500')) {
    return {
      phase: 'error',
      detail:
        'The service database is not ready — run the migration job (docs/DEPLOYMENT.md step A9), then retry.',
    };
  }
  if (msg.startsWith('401')) {
    return {
      phase: 'error',
      detail:
        'Google sign-in succeeded but the API rejected the token — verify GOOGLE_CLIENT_ID on the service matches the button’s client id.',
    };
  }
  return { phase: 'error', detail: msg.slice(0, 200) };
}

export function Login() {
  const qc = useQueryClient();
  const [cfg, setCfg] = useState<ClientConfig | null>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [detail, setDetail] = useState('');
  const gsiHost = useRef<HTMLDivElement>(null);

  const finish = async () => {
    setPhase('signing');
    setDetail('');
    try {
      const me = await api.me(); // backend verifies the token + domain — fails closed (403)
      qc.setQueryData(['me'], me); // flips the App gate; the router mounts
      location.hash = '#/mission-control';
    } catch (e) {
      const msg = String((e as Error)?.message ?? e);
      if (msg.includes('403')) {
        setPhase('rejected');
        setDetail(
          'This account is not permitted — sign in with a verified @' +
            (cfg?.auth_email_domain ?? 'zennify.com') +
            ' Google account.',
        );
        signOutUser();
        return;
      }
      const mapped = mapError(e);
      setPhase(mapped.phase);
      setDetail(mapped.detail);
    }
  };

  const load = () => {
    setPhase('loading');
    setDetail('');
    loadConfig()
      .then(async (c) => {
        setCfg(c);
        setPhase('ready');
        if (c.auth_mode === 'live') {
          // Pre-warm Google's script, then let GOOGLE render the button — Google owns the click,
          // so there is no custom popup to be blocked and nothing to time out.
          await prewarmAuth();
          if (gsiHost.current) {
            await renderGoogleButton(gsiHost.current, () => void finish());
          }
        }
      })
      .catch((e) => {
        setPhase('error');
        setDetail(
          String((e as Error)?.message ?? e).includes('config')
            ? 'Could not reach the API — check the service, then retry.'
            : String((e as Error)?.message ?? e).slice(0, 220),
        );
      });
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, []);

  return (
    <div className="loginwrap">
      <div className="loginbrand">
        <div
          style={{
            position: 'absolute',
            inset: 0,
            backgroundImage: 'url(/brand/hero-bg.png)',
            backgroundSize: 'cover',
            backgroundPosition: 'center bottom',
            opacity: 0.5,
            maskImage: 'linear-gradient(to bottom, transparent, #000 55%)',
            WebkitMaskImage: 'linear-gradient(to bottom, transparent, #000 55%)',
          }}
        />
        <div style={{ position: 'relative', zIndex: 1 }}>
          <div className="row gap12" style={{ marginBottom: 54 }}>
            <img src="/brand/logo-mark-teal.png" style={{ width: 32, height: 32 }} alt="Zennify" />
            <span style={{ fontSize: 19, fontWeight: 700, letterSpacing: '-.01em' }}>zennify</span>
          </div>
          <div
            style={{
              fontSize: 12,
              fontWeight: 700,
              letterSpacing: '.14em',
              textTransform: 'uppercase',
              color: '#27bbaf',
              marginBottom: 14,
            }}
          >
            Capability Intelligence Agent
          </div>
          <h1
            style={{
              fontSize: 34,
              fontWeight: 700,
              lineHeight: 1.12,
              letterSpacing: '-.02em',
              margin: '0 0 16px',
              maxWidth: 460,
            }}
          >
            The internal workbench that keeps Zennify&rsquo;s capability catalogue provably current.
          </h1>
          <div style={{ display: 'grid', gap: 16, marginTop: 36, maxWidth: 440 }}>
            {PROMISES.map(([t, d]) => (
              <div key={t} className="row gap12" style={{ alignItems: 'flex-start' }}>
                <div
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: 6,
                    background: 'rgba(39,187,175,.2)',
                    color: '#62d7b8',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flex: 'none',
                    marginTop: 1,
                  }}
                >
                  <Icon n="check" s={13} />
                </div>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 2 }}>{t}</div>
                  <div style={{ fontSize: 12.5, color: 'rgba(255,255,255,.62)', lineHeight: 1.5 }}>
                    {d}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div
          style={{
            position: 'relative',
            zIndex: 1,
            marginTop: 'auto',
            fontSize: 11,
            color: 'rgba(255,255,255,.4)',
          }}
        >
          Capability Intelligence Agent · v{APP_VERSION} · © 2026 Zennify · Confidential
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 48 }}>
        <div style={{ width: '100%', maxWidth: 360 }}>
          <div className="h1" style={{ fontSize: 24, marginBottom: 6 }}>
            Sign in
          </div>
          <div className="muted" style={{ fontSize: 13.5, marginBottom: 28, lineHeight: 1.5 }}>
            Use your Zennify Google account. Access is limited to staff; this workbench is not for
            client use.
          </div>

          {phase === 'loading' && (
            <div className="muted" style={{ fontSize: 12 }}>
              Loading sign-in configuration…
            </div>
          )}

          {cfg?.auth_mode === 'dev' && phase !== 'loading' && (
            <>
              <div
                className="card"
                style={{ padding: '9px 12px', marginBottom: 12, background: 'var(--surface-raised)' }}
              >
                <div className="row gap8">
                  <span className="chip blue" style={{ fontSize: 9.5 }}>
                    dev identity
                  </span>
                  <span className="muted" style={{ fontSize: 11.5 }}>
                    AUTH_MODE=dev — local development only
                  </span>
                </div>
              </div>
              <button
                className="btn primary"
                style={{ width: '100%', justifyContent: 'center', padding: 12, fontSize: 14 }}
                disabled={phase === 'signing'}
                onClick={() => void finish()}
              >
                Continue to the workbench
              </button>
            </>
          )}

          {cfg?.auth_mode === 'live' && (
            <>
              {/* Google renders its official button in here (live mode). */}
              <div
                ref={gsiHost}
                style={{ minHeight: 44, display: phase === 'signing' ? 'none' : 'block' }}
              />
              {phase === 'signing' && (
                <div className="row gap8" style={{ fontSize: 12.5 }}>
                  <Icon n="refresh" s={15} cls="spin" />
                  Signing in…
                </div>
              )}
            </>
          )}

          {phase === 'rejected' && (
            <div
              className="card"
              style={{ padding: '10px 12px', background: 'var(--state-warn-bg)', marginTop: 12 }}
            >
              <div className="row gap8">
                <Icon n="alert" s={14} style={{ color: 'var(--z-orange)', flex: 'none' }} />
                <span style={{ fontSize: 11.5 }}>{detail}</span>
              </div>
              <button
                className="btn ghost xs"
                style={{ marginTop: 8 }}
                onClick={() => {
                  setPhase('ready');
                  setDetail('');
                  load();
                }}
              >
                Try a different account
              </button>
            </div>
          )}

          {phase === 'error' && (
            <div
              className="card"
              style={{ padding: '10px 12px', marginTop: 12, background: 'var(--state-warn-bg)' }}
            >
              <div className="row gap8">
                <Icon n="alert" s={14} style={{ color: 'var(--z-orange)', flex: 'none' }} />
                <span style={{ fontSize: 11.5 }}>{detail}</span>
              </div>
              <button className="btn ghost xs" style={{ marginTop: 8 }} onClick={load}>
                Retry
              </button>
            </div>
          )}

          {cfg?.auth_mode === 'live' && (
            <div
              className="row gap8"
              style={{
                marginTop: 18,
                padding: '10px 12px',
                background: 'var(--surface-overlay)',
                borderRadius: 7,
              }}
            >
              <span
                style={{
                  borderRadius: '50%',
                  width: 8,
                  height: 8,
                  background: 'var(--interactive)',
                  flex: 'none',
                }}
              />
              <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                Restricted to <b>@{cfg?.auth_email_domain ?? 'zennify.com'}</b> · other domains are
                turned away.
              </span>
            </div>
          )}

          <div className="muted" style={{ fontSize: 11.5, marginTop: 24, textAlign: 'center' }}>
            Having trouble? Contact it-help@zennify.com
          </div>
        </div>
      </div>
    </div>
  );
}
