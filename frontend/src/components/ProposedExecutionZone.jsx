import { useEffect, useState } from 'react';
import { get } from '../api.js';
import { Panel, Badge, Loading } from '../components/ui.jsx';
import { useSymbol } from '../symbols.jsx';

const FIVE_SECONDS = 5000;
const PRICE_SCALE = 1000000;

function deriveDirection(decision, tech) {
  const mtfBias = tech?.mtfBias || null;
  if (mtfBias === 'bullish') return 'BUY';
  if (mtfBias === 'bearish') return 'SELL';
  const entry = decision?.entry ?? tech?.entry;
  const tp1 = decision?.takeProfit ?? tech?.takeProfit ?? tech?.takeProfits?.[0];
  if (entry != null && tp1 != null) {
    if (Number(tp1) > Number(entry)) return 'BUY';
    if (Number(tp1) < Number(entry)) return 'SELL';
  }
  const dir = (decision?.direction || '').toUpperCase();
  if (dir === 'BUY' || dir === 'SELL') return dir;
  return 'NEUTRAL';
}

function rrFromLevels(entry, sl, tp) {
  if (entry == null || sl == null || tp == null) return null;
  const e = Math.round(Number(entry) * PRICE_SCALE);
  const s = Math.round(Number(sl) * PRICE_SCALE);
  const t = Math.round(Number(tp) * PRICE_SCALE);
  const risk = Math.abs(e - s);
  const reward = Math.abs(t - e);
  if (risk === 0) return null;
  return Math.round((reward / risk) * 100) / 100;
}

function to5(v) {
  return v == null ? '—' : Number(v).toFixed(5);
}

export default function ProposedExecutionZone() {
  const { symbol } = useSymbol();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastSync, setLastSync] = useState(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const ticker = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(ticker);
  }, []);

  useEffect(() => {
    let mounted = true;
    let timerId = null;

    const load = async () => {
      try {
        const res = await get(`/decisions?symbol=${encodeURIComponent(symbol)}&limit=1`);
        if (!mounted) return;
        setData(res?.decisions?.[0] || null);
        setError(null);
        setLastSync(Date.now());
      } catch (e) {
        if (!mounted) return;
        setError(e.message);
      } finally {
        if (mounted) setLoading(false);
      }
    };

    const onVisible = () => {
      if (document.visibilityState === 'visible') load();
    };

    load();
    timerId = setInterval(load, FIVE_SECONDS);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      mounted = false;
      if (timerId) clearInterval(timerId);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [symbol]);

  const secondsUntilNext = lastSync ? Math.max(0, FIVE_SECONDS / 1000 - Math.floor((now - lastSync) / 1000)) : FIVE_SECONDS / 1000;

  const decision = data || null;
  const techScore = (decision?.agentScores || []).find((a) => a.agent_id === 'technical');
  const tech = techScore?.data || {};
  const execution = tech.execution || decision?.status || 'no_trade';
  const confirmed = execution === 'confirmed';

  const entry = decision?.entry ?? tech.entry ?? null;
  const sl = decision?.stopLoss ?? tech.stopLoss ?? null;
  const tp1 = decision?.takeProfit ?? tech.takeProfit ?? tech.takeProfits?.[0] ?? null;
  const tp2 = tech.takeProfits?.[1] ?? null;

  const direction = deriveDirection(decision, tech);
  const rr = tech.sltp?.riskReward != null ? Number(tech.sltp.riskReward) : rrFromLevels(entry, sl, tp1);
  const hasLevels = entry != null && sl != null && tp1 != null;

  const dirColor = direction === 'BUY' ? 'var(--green)' : direction === 'SELL' ? 'var(--red)' : 'var(--amber)';
  const badgeType = direction === 'BUY' ? 'buy' : direction === 'SELL' ? 'sell' : 'neutral';

  const ladder = [
    { label: 'TP2', value: tp2, color: 'var(--green)' },
    { label: 'TP1', value: tp1, color: 'var(--green)' },
    { label: 'Entry', value: entry, color: 'var(--accent)' },
    { label: 'SL', value: sl, color: 'var(--red)' }
  ];

  return (
    <Panel
      title="Proposed Execution Zone"
      sub={`${symbol} · Technical Engine output · auto-refresh every 5s · next refresh in ${secondsUntilNext}s`}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span className="zone-live"><span className="zone-live-dot" /> LIVE</span>
        {lastSync ? <span className="muted" style={{ fontSize: 10.5 }}>Last synced {new Date(lastSync).toLocaleTimeString()}</span> : null}
      </div>
      {loading ? <Loading /> : error ? (
        <div className="empty" style={{ color: 'var(--red)' }}>Error: {error}</div>
      ) : !hasLevels ? (
        <div className="empty">
          No technical execution levels available yet. The Technical Execution Agent publishes entry / SL / TP after a full AI decision cycle.
        </div>
      ) : (
        <div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
            <span className="muted" style={{ fontSize: 11 }}>Direction</span>
            <Badge type={badgeType}>{direction}</Badge>
            <span style={{ marginLeft: 'auto', fontSize: 11 }}>
              Execution: <Badge type={confirmed ? 'buy' : 'warning'}>{execution}</Badge>
            </span>
          </div>

          <div className="grid grid-4">
            <div className="stat-card">
              <div className="stat-label">Entry Price</div>
              <div className="stat-value" style={{ color: 'var(--accent)', fontSize: 18 }}>{to5(entry)}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Stop Loss (SL)</div>
              <div className="stat-value" style={{ color: 'var(--red)', fontSize: 18 }}>{to5(sl)}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Take Profit 1 (TP1)</div>
              <div className="stat-value" style={{ color: 'var(--green)', fontSize: 18 }}>{to5(tp1)}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Take Profit 2 (TP2)</div>
              <div className="stat-value" style={{ color: 'var(--green)', fontSize: 18 }}>{to5(tp2)}</div>
            </div>
          </div>

          <div style={{ height: 12 }} />

          <div className="grid grid-3">
            <div className="stat-card">
              <div className="stat-label">Risk / Reward</div>
              <div className="stat-value" style={{ fontSize: 18, color: rr != null && rr >= 2 ? 'var(--green)' : 'var(--amber)' }}>
                {rr != null ? `1 : ${rr.toFixed(2)}` : '—'}
              </div>
              {tech.sltp?.minRiskReward != null && (
                <div className="stat-sub">Minimum gate: 1 : {Number(tech.sltp.minRiskReward).toFixed(1)}</div>
              )}
            </div>
            <div className="stat-card">
              <div className="stat-label">MTF Alignment Score</div>
              <div className="stat-value" style={{ fontSize: 18, color: (tech.mtfAlignmentScore ?? 0) >= 40 ? 'var(--green)' : 'var(--amber)' }}>
                {tech.mtfAlignmentScore != null ? `${Math.round(tech.mtfAlignmentScore)}/100` : '—'}
              </div>
              <div className="stat-sub">MTF bias: {tech.mtfBias || '—'}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Signal State</div>
              <div className="stat-value" style={{ fontSize: 18 }}>{tech.state || '—'}</div>
              {tech.sltp?.reason && <div className="stat-sub" style={{ fontSize: 10.5 }}>{tech.sltp.reason}</div>}
            </div>
          </div>

          <div style={{ height: 16 }} />

          <div className="zone-ladder">
            {ladder.map((lvl) => (
              <div key={lvl.label} className="zone-ladder-row">
                <div className="zone-ladder-label">{lvl.label}</div>
                <div className="zone-ladder-track">
                  <div className="zone-ladder-fill" style={{ width: '100%', background: lvl.value != null ? lvl.color : 'var(--border2)' }} />
                </div>
                <div className="zone-ladder-value" style={{ color: lvl.value != null ? lvl.color : 'var(--muted)' }}>{to5(lvl.value)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}
