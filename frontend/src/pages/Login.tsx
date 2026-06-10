// Login (access) — Firebase Google sign-in, @zennify.com, fails closed. Brand split layout:
// the left panel carries the product identity; the right card signs in. States: loading config,
// dev-identity (hermetic dev — no token needed), Google sign-in (live), domain-rejected (the
// backend 403s non-domain/unverified accounts — shown honestly, with sign-out), popup-blocked.
import { useEffect, useState } from 'react';

import { api } from '../api/client';
import { type ClientConfig, loadConfig, signIn, signOutUser } from '../lib/auth';
import { Icon } from '../lib/icons';

type Phase = 'loading' | 'ready' | 'signing' | 'rejected' | 'error';

export function Login() {
  const [cfg, setCfg] = useState<ClientConfig | null>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [detail, setDetail] = useState('');

  useEffect(() => {
    loadConfig()
      .then((c) => {
        setCfg(c);
        setPhase('ready');
      })
      .catch(() => {
        setPhase('error');
        setDetail('Could not reach the API — check the service and reload.');
      });
  }, []);

  const proceed = async () => {
    setPhase('signing');
    try {
      await signIn(); // dev mode resolves immediately; live opens the Google popup
      await api.me(); // backend verifies the token + domain — fails closed (403)
      location.hash = '#/mission-control';
    } catch (e) {
      const msg = String(e);
      if (msg.includes('403')) {
        setPhase('rejected');
        setDetail('This account is not permitted — sign in with a verified @' +
          (cfg?.auth_email_domain ?? 'zennify.com') + ' Google account.');
        void signOutUser();
      } else if (msg.toLowerCase().includes('popup')) {
        setPhase('ready');
        setDetail('The sign-in popup was blocked — allow popups for this site and retry.');
      } else {
        setPhase('error');
        setDetail(msg.slice(0, 140));
      }
    }
  };

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: 'var(--surface-base)' }}>
      <div
        style={{
          flex: 1,
          background: 'linear-gradient(135deg, #27bbaf 0%, #176d66 100%)',
          color: '#fff',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '0 8%',
        }}
      >
        <div
          style={{
            width: 46,
            height: 46,
            borderRadius: 12,
            background: 'rgba(255,255,255,.18)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: 18,
          }}
        >
          <Icon n="check" s={24} />
        </div>
        <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: '-0.5px' }}>
          Capability Intelligence Agent
        </div>
        <div style={{ fontSize: 13.5, opacity: 0.85, marginTop: 10, maxWidth: 440, lineHeight: 1.6 }}>
          The trust-first consultant workbench over the four-pillar capability catalogue and the
          canonical delivery corpus. Every AI value carries its claim label, source tier, ERS and
          a reasoning chain — and nothing AI-derived commits without the eight gates.
        </div>
      </div>

      <div
        style={{
          width: 420,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 32,
        }}
      >
        <div className="card pad" style={{ width: '100%', maxWidth: 340 }}>
          <div className="h2" style={{ marginBottom: 6 }}>
            Sign in
          </div>
          <div className="muted" style={{ fontSize: 11.5, marginBottom: 16 }}>
            Restricted to verified @{cfg?.auth_email_domain ?? 'zennify.com'} accounts — access
            fails closed.
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
              <button className="btn primary" style={{ width: '100%' }} onClick={proceed}>
                Continue to the workbench
              </button>
            </>
          )}

          {cfg?.auth_mode === 'live' && (phase === 'ready' || phase === 'signing') && (
            <button
              className="btn primary"
              style={{ width: '100%' }}
              disabled={phase === 'signing'}
              onClick={proceed}
            >
              <Icon n="google" s={14} /> {phase === 'signing' ? 'Signing in…' : 'Sign in with Google'}
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

          {detail && phase !== 'rejected' && (
            <div className="muted" style={{ fontSize: 11, marginTop: 10 }}>
              {detail}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
