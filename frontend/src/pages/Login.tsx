// Login (access) — Firebase Google sign-in, @zennify.com, fails closed. Layout/copy mirror the
// prototype's Login (brand panel: dark, hero image, logo + promise list; right: sign-in card).
// Real states the prototype mocks: loading/error on /api/config (with Retry), dev-identity
// (hermetic dev — no token), Google popup (live), domain-rejected (backend 403s — shown honestly,
// with sign-out), popup-blocked/closed, unauthorized-domain, db-not-ready, sign-in timeout.
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { api } from '../api/client';
import { type ClientConfig, loadConfig, signIn, signOutUser } from '../lib/auth';
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

/** Map a sign-in failure to the phase + actionable message the operator needs. */
function mapSignInError(e: unknown, host: string): { phase: Phase; detail: string } {
  const code = (e as { code?: string }).code ?? '';
  const msg = String((e as Error)?.message ?? e);
  if (code === 'auth/unauthorized-domain') {
    return {
      phase: 'ready',
      detail:
        `Sign-in is blocked for this host — in Firebase Console → Authentication → Settings → ` +
        `Authorized domains, add ${host}, then retry. (Deployment guide, end of step A7.)`,
    };
  }
  if (code === 'auth/popup-blocked' || msg.toLowerCase().includes('popup')) {
    if (code === 'auth/popup-closed-by-user' || code === 'auth/cancelled-popup-request') {
      return { phase: 'ready', detail: '' }; // user dismissed it — silent reset
    }
    return {
      phase: 'ready',
      detail: 'The sign-in popup was blocked — allow popups for this site and retry.',
    };
  }
  if (code === 'auth/popup-closed-by-user' || code === 'auth/cancelled-popup-request') {
    return { phase: 'ready', detail: '' };
  }
  if (code === 'auth/network-request-failed') {
    return {
      phase: 'error',
      detail: 'Could not reach Google sign-in — check the network and retry.',
    };
  }
  if (code === 'auth/timeout') {
    return {
      phase: 'ready',
      detail: 'Sign-in timed out — the popup may have been blocked or closed. Retry.',
    };
  }
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
        'Google sign-in succeeded but the API rejected the token — verify FIREBASE_PROJECT_ID on the service.',
    };
  }
  return { phase: 'error', detail: msg.slice(0, 160) };
}

export function Login() {
  const qc = useQueryClient();
  const [cfg, setCfg] = useState<ClientConfig | null>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [detail, setDetail] = useState('');

  const load = () => {
    setPhase('loading');
    setDetail('');
    loadConfig()
      .then((c) => {
        setCfg(c);
        setPhase('ready');
      })
      .catch(() => {
        setPhase('error');
        setDetail('Could not reach the API — check the service, then retry.');
      });
  };
  useEffect(load, []);

  const proceed = async () => {
    setPhase('signing');
    setDetail('');
    try {
      // dev mode resolves immediately; live opens the Google popup. The race keeps the button
      // from sticking on "Signing in…" forever when a popup silently never returns.
      await Promise.race([
        signIn(),
        new Promise((_, reject) =>
          setTimeout(() => reject(Object.assign(new Error('timeout'), { code: 'auth/timeout' })), 30_000),
        ),
      ]);
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
        void signOutUser();
        return;
      }
      const mapped = mapSignInError(e, location.hostname);
      setPhase(mapped.phase);
      setDetail(mapped.detail);
    }
  };

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
                onClick={() => void proceed()}
              >
                Continue to the workbench
              </button>
            </>
          )}

          {cfg?.auth_mode === 'live' && (phase === 'ready' || phase === 'signing') && (
            <button
              className="btn ghost"
              style={{ width: '100%', justifyContent: 'center', padding: 12, fontSize: 14 }}
              disabled={phase === 'signing'}
              onClick={() => void proceed()}
            >
              {phase === 'signing' ? (
                <Icon n="refresh" s={16} cls="spin" />
              ) : (
                <Icon n="google" s={16} />
              )}
              {phase === 'signing' ? 'Signing in…' : 'Continue with Google'}
            </button>
          )}

          {phase === 'rejected' && (
            <div
              className="card"
              style={{ padding: '10px 12px', background: 'var(--state-warn-bg)', marginTop: 4 }}
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
                }}
              >
                Try a different account
              </button>
            </div>
          )}

          {phase === 'error' && (
            <div className="card" style={{ padding: '10px 12px', marginTop: 4 }}>
              <div className="row gap8">
                <Icon n="alert" s={14} style={{ color: 'var(--z-orange)', flex: 'none' }} />
                <span style={{ fontSize: 11.5 }}>{detail}</span>
              </div>
              <button className="btn ghost xs" style={{ marginTop: 8 }} onClick={load}>
                Retry
              </button>
            </div>
          )}

          {detail && phase !== 'rejected' && phase !== 'error' && (
            <div className="muted" style={{ fontSize: 11, marginTop: 10 }}>
              {detail}
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
