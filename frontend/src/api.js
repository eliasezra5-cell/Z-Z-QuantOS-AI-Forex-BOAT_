import { useEffect, useState, useCallback } from 'react';

// API base URL resolution:
//  - VITE_API_URL (build/deploy-time env var) overrides the base entirely, e.g.
//    "https://quantos-backend.example.com". It is injected by Vite at build
//    time, so it can be set per-environment without touching code.
//  - When unset, fall back to same-origin "/api" (dev-server proxy / nginx).
const API_URL = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '');
const BASE = API_URL || '/api';

// WebSocket endpoint mirrors the HTTP API base (same origin / host), so live
// channels follow VITE_API_URL when one is configured.
function wsBase() {
  if (API_URL) {
    const u = new URL(API_URL);
    return `${u.protocol === 'https:' ? 'wss' : 'ws'}://${u.host}`;
  }
  return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;
}

export async function api(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts
  });
  if (!res.ok) {
    let body;
    try { body = await res.json(); } catch (e) { body = {}; }
    throw new Error(body.error?.message || `Request failed: ${res.status}`);
  }
  return res.json();
}

export const get = (p) => api(p);
export const post = (p, body) => api(p, { method: 'POST', body: JSON.stringify(body) });

export function useFetch(path, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const refresh = useCallback(() => {
    setLoading(true);
    get(path).then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [path]);
  useEffect(() => { refresh(); }, [refresh, ...deps]);
  return { data, loading, error, refresh };
}

export function useLive(channel, handler, enabled = true) {
  useEffect(() => {
    if (!enabled) return undefined;
    const ws = new WebSocket(`${wsBase()}/ws`);
    ws.onopen = () => ws.send(JSON.stringify({ type: 'subscribe', channel }));
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'data' && msg.channel === channel) handler(msg.data);
      } catch (err) { /* ignore */ }
    };
    return () => ws.close();
  }, [channel, handler, enabled]);
}

export function useLiveQuotes() {
  const [quotes, setQuotes] = useState({});
  const handler = useCallback((tick) => {
    setQuotes((prev) => ({ ...prev, [tick.symbol]: tick }));
  }, []);
  useLive('market', handler);
  return quotes;
}

export const fmt = (n, digits = 5) => (n == null ? '—' : Number(n).toFixed(digits));
export const fmtPct = (n, digits = 2) => (n == null ? '—' : `${Number(n) >= 0 ? '+' : ''}${Number(n).toFixed(digits)}%`);
export const fmtMoney = (n) => (n == null ? '—' : `$${Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`);
export const fmtTime = (t) => (t == null ? '—' : new Date(t).toLocaleString());

// Normalizes a real 5-agent pipeline decision into the display shape the
// dashboard/AI pages already render (consensus / confidence / agents / xai).
export function normalizeDecision(d) {
  if (!d) return d;
  if (d.consensus && d.confidence && d.confidence.score !== undefined) return d; // already legacy
  const agents = (d.agentScores || []).map((a) => ({
    id: a.agent_id,
    name: a.name,
    weight: a.weight,
    direction: a.direction,
    confidence: a.confidence,
    reasoning: a.reasoning,
    contribution: Number((a.weight || 0) * (a.confidence || 0)),
  }));
  const direction = (d.direction || d.recommendation?.direction || 'neutral').toLowerCase();
  const buyWeight = agents.filter((a) => a.direction === 'buy').reduce((s, a) => s + a.weight, 0);
  const sellWeight = agents.filter((a) => a.direction === 'sell').reduce((s, a) => s + a.weight, 0);
  const score = Number(d.confidence ?? 0);
  const status = d.status || 'NO_TRADE';
  const level = score >= 0.9 ? 'high' : score >= 0.7 ? 'medium' : 'low';
  return {
    ...d,
    consensus: {
      direction,
      agreement: Math.abs(buyWeight - sellWeight),
      buyWeight,
      sellWeight,
    },
    confidence: { score, level },
    agents,
    xai: {
      contributions: agents.map((a) => ({ agent: a.name || a.id, direction: a.direction, reasoning: a.reasoning })),
      timeline: [
        { step: 'Multi-agent analysis', detail: `${agents.length} agents ran in parallel` },
        { step: 'Consensus', detail: `${direction.toUpperCase()} at ${(score * 100).toFixed(1)}% confidence` },
        { step: status === 'NO_TRADE' ? 'No trade' : 'Execution', detail: status },
      ],
    },
    recommendation: {
      action: d.recommendation?.action || 'hold',
      direction,
      status: d.recommendation?.status || status,
      entry: d.entry,
      stopLoss: d.stopLoss,
      takeProfit: d.takeProfit,
      reason: d.recommendation?.status || '',
    },
  };
}
