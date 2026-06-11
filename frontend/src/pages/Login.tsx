// Login (access) — OAuth 2.0 Authorization-Code flow (the proven Accelerate pattern), @zennify.com,
// fails closed. Clicking "Continue with Google" is a FULL-PAGE redirect to /api/auth/login → Google
// consent → /api/auth/callback (server exchanges the code with the client secret, verifies the
// hosted domain, sets a signed HttpOnly session cookie) → back into the app. No browser Google SDK,
// no "Authorized JavaScript origins", so it works behind a load balancer / any origin. States:
// config loading/error (Retry), sign-in unconfigured (client id/secret missing — actionable),
// db unreachable (honest, not "run the migration job"), dev-identity, domain-rejected (callback).
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { api } from '../api/client';
import { type ClientConfig, loadConfig } from '../lib/auth';
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

/** Map a sign-in/api failure to the phase + actionable message the operator needs. The backend
 * now sends an HONEST message for each cause (auth unconfigured vs database unreachable), so we
 * SHOW IT rather than overwrite every 5xx with a single hardcoded line — the old behaviour sent
 * operators chasing the migration job for problems that were never the database. */
function mapError(e: unknown): { phase: Phase; detail: string } {
  const raw = String((e as Error)?.message ?? e);
  const body = raw.replace(/^\d{3}:\s*/, ''); // strip the "503: " status prefix → the real message
  if (raw.startsWith('401')) {
    return {
      phase: 'error',
      detail:
        'Google sign-in succeeded but the API rejected the token — verify GOOGLE_CLIENT_ID on the service matches the button’s client id.',
    };
  }
  if (raw.startsWith('503') || raw.startsWith('500')) {
    return { phase: 'error', detail: body.slice(0, 260) }; // the server's honest reason
  }
  return { phase: 'error', detail: body.slice(0, 220) };
}

export function Login() {
  const qc = useQueryClient();
  const [cfg, setCfg] = useState<ClientConfig | null>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [detail, setDetail] = useState('');

  // The OAuth callback redirects back to #/login?error=… on a refusal (e.g. non-@zennify account).
  const callbackError = (): string | null => {
    const m = /[?&]error=([^&]+)/.exec(location.hash);
    return m ? decodeURIComponent(m[1]) : null;
  };

  // Live sign-in is a full-page redirect to the server, which owns the entire Google handshake.
  const startLogin = () => {
    setPhase('signing');
    window.location.href = cfg?.login_url ?? '/api/auth/login';
  };

  // Dev mode only: there is no Google round-trip, so /api/me resolves the dev identity directly.
  const finishDev = async () => {
    setPhase('signing');
    setDetail('');
    try {
      const me = await api.me();
      await qc.cancelQueries({ queryKey: ['me'] });
      qc.setQueryData(['me'], me);
      location.hash = '#/mission-control';
    } catch (e) {
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
        // A refused OAuth callback landed back here with ?error=… — show it honestly.
        const err = callbackError();
        if (err) {
          setPhase('rejected');
          setDetail(
            err === 'domain'
              ? `This account is not permitted — sign in with a verified @${c.auth_email_domain} Google account.`
              : `Sign-in did not complete (${err}). Try again.`,
          );
          return;
        }
        // PRE-FLIGHT: name the exact blocker before the user ever clicks, instead of letting them
        // start a flow that can't finish. The server reports both readiness signals on /api/config.
        if (c.auth_mode === 'live' && c.auth_configured === false) {
          setPhase('error');
          setDetail(
            'Sign-in is not configured on the server — set GOOGLE_OAUTH_CLIENT_ID and ' +
              'GOOGLE_OAUTH_CLIENT_SECRET on the Cloud Run service. This is NOT a database problem.',
          );
          return;
        }
        if (c.db && c.db !== 'ok') {
          setPhase('error');
          setDetail(
            c.db === 'not_configured'
              ? 'The service has no database configured (DATABASE_URL) — set it and run the migration job (A9).'
              : 'The service cannot reach its database (its Cloud SQL connection). The migration ' +
                'job is separate and may already have run — check the service has ' +
                '--add-cloudsql-instances and a reachable instance, then retry.',
          );
          return;
        }
        setPhase('ready'); // live: the redirect button is shown; dev: the continue button
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
  useEffect(() => load(), []); // eslint-disable-line react-hooks/exhaustive-deps

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
                onClick={() => void finishDev()}
              >
                Continue to the workbench
              </button>
            </>
          )}

          {cfg?.auth_mode === 'live' && (phase === 'ready' || phase === 'signing') && (
            <button
              className="btn primary"
              style={{
                width: '100%',
                justifyContent: 'center',
                gap: 10,
                padding: 12,
                fontSize: 14,
              }}
              disabled={phase === 'signing'}
              onClick={startLogin}
            >
              {phase === 'signing' ? (
                <>
                  <Icon n="refresh" s={16} cls="spin" /> Redirecting to Google…
                </>
              ) : (
                <>
                  <Icon n="shield" s={16} /> Continue with Google
                </>
              )}
            </button>
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
