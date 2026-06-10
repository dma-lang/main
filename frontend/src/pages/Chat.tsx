// AI chat (H1) — catalogue-grounded RAG. Every answer is citation-backed (subcap chips -> deep dive)
// and carries the trust envelope (tier · claim · ERS · reasoning backlink); off-catalogue questions
// are refused (G5). Wired to POST /api/chat; the reasoning chain opens via the cia-reason event.
import { useRef, useState } from 'react';

import type { ChatResponse } from '../api/client';
import { useChat } from '../api/queries';
import { Claim, Tier } from '../components/primitives';
import { go, openReasoning } from '../lib/events';
import { Icon } from '../lib/icons';
import { useUi } from '../state/store';

interface Msg {
  role: 'user' | 'ai';
  text: string;
  res?: ChatResponse;
}

const GREETING: Msg = {
  role: 'ai',
  text: 'Ask anything about the catalogue — capabilities, platforms, personas, delivery. I answer only from retrieved evidence and cite every claim; out-of-context questions are refused.',
};

export function Chat() {
  const version = useUi((s) => s.version);
  const lens = useUi((s) => s.lens);
  const pillar = useUi((s) => s.pillar);
  const [msgs, setMsgs] = useState<Msg[]>([GREETING]);
  const [input, setInput] = useState('');
  const chat = useChat();
  const endRef = useRef<HTMLDivElement>(null);

  const send = () => {
    const q = input.trim();
    if (!q || chat.isPending) return;
    setInput('');
    setMsgs((m) => [...m, { role: 'user', text: q }]);
    chat.mutate(
      { question: q, version },
      {
        onSuccess: (res) => setMsgs((m) => [...m, { role: 'ai', text: res.answer, res }]),
        onError: () =>
          setMsgs((m) => [
            ...m,
            { role: 'ai', text: 'Could not reach the grounded model — try again.' },
          ]),
      },
    );
    setTimeout(() => endRef.current?.scrollIntoView({ behavior: 'smooth' }), 60);
  };

  return (
    <>
      <div className="titlebar">
        <div className="crumbs">
          <span>H · Reasoning &amp; RAG</span>
          <span className="sep">
            <Icon n="chevR" s={11} />
          </span>
          <span style={{ color: 'var(--text-secondary)' }}>AI chat</span>
        </div>
      </div>
      <div
        className="content wide"
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 300px',
          gap: 20,
          height: 'calc(100% - 64px)',
          paddingBottom: 24,
        }}
      >
        <div className="card" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: 20,
              display: 'flex',
              flexDirection: 'column',
              gap: 16,
            }}
          >
            {msgs.map((m, i) => {
              if (m.role === 'user') {
                return (
                  <div
                    key={i}
                    style={{
                      alignSelf: 'flex-end',
                      maxWidth: '78%',
                      background: 'var(--surface-overlay)',
                      padding: '10px 14px',
                      borderRadius: '10px 10px 2px 10px',
                      fontSize: 13.5,
                    }}
                  >
                    {m.text}
                  </div>
                );
              }
              const res = m.res;
              const cited = res && res.citations.length > 0;
              return (
                <div key={i} style={{ alignSelf: 'flex-start', maxWidth: '85%' }}>
                  <div
                    className="card pad"
                    style={{ padding: '14px 16px', borderRadius: '10px 10px 10px 2px' }}
                  >
                    <div style={{ fontSize: 13.5, lineHeight: 1.55, marginBottom: cited ? 12 : 0 }}>
                      {m.text}
                    </div>
                    {res && cited && (
                      <>
                        <div className="row wrap gap6" style={{ marginBottom: 10 }}>
                          {res.citations.map((c) => (
                            <span
                              key={c.subcap_id}
                              className="row gap6 card"
                              style={{ padding: '4px 8px', cursor: 'pointer' }}
                              onClick={() => go('subcap/' + c.subcap_id)}
                            >
                              <span
                                className="mono"
                                style={{ fontSize: 10.5, color: 'var(--interactive)', fontWeight: 600 }}
                              >
                                {c.subcap_id}
                              </span>
                              <span className="muted" style={{ fontSize: 11 }}>
                                {c.name}
                              </span>
                            </span>
                          ))}
                        </div>
                        <div
                          className="between"
                          style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}
                        >
                          <div className="row gap6">
                            {res.source_tier && <Tier t={res.source_tier} />}
                            {res.claim_label && <Claim label={res.claim_label} />}
                            <span className="muted" style={{ fontSize: 10.5 }}>
                              {res.source} · ERS {res.ers}
                            </span>
                          </div>
                          {res.chain_id && (
                            <button className="btn ghost xs" onClick={() => openReasoning(res.chain_id)}>
                              <Icon n="eye" s={13} /> Reasoning
                            </button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
            {chat.isPending && (
              <div className="muted" style={{ fontSize: 12 }}>
                Retrieving grounded evidence…
              </div>
            )}
            <div ref={endRef} />
          </div>
          <div style={{ padding: 14, borderTop: '1px solid var(--border-subtle)' }}>
            <div className="searchbox">
              <input
                placeholder="Ask anything about the catalogue…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && send()}
              />
              <button className="btn primary xs" onClick={send} disabled={chat.isPending}>
                <Icon n="arrowR" s={14} />
              </button>
            </div>
          </div>
        </div>
        <div style={{ display: 'grid', gap: 14, alignContent: 'start' }}>
          <div className="card pad">
            <div className="h3" style={{ marginBottom: 10 }}>
              Context
            </div>
            <div style={{ display: 'grid', gap: 6, fontSize: 12 }}>
              <div className="between">
                <span className="muted">Version</span>
                <span className="chip soft">{version || '—'}</span>
              </div>
              <div className="between">
                <span className="muted">Lens</span>
                <span className="chip soft">{lens}</span>
              </div>
              <div className="between">
                <span className="muted">Pillar</span>
                <span className="chip soft">{pillar}</span>
              </div>
            </div>
            <div className="muted" style={{ fontSize: 11, marginTop: 10, lineHeight: 1.5 }}>
              Answers are grounded only in the retrieved {version || ''} catalogue evidence and cite
              every claim. Out-of-context questions are refused (G5).
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
