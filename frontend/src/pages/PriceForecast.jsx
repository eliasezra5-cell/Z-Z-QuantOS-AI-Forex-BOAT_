import { useEffect, useState } from 'react';
import { get, fmt, fmtPct } from '../api.js';
import { Panel, Badge, Loading } from '../components/ui.jsx';

const ALL_SYMBOLS = ['XAUUSD', 'XAGUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'BTCUSD', 'ETHUSD', 'US500', 'NAS100', 'US30', 'WTI', 'UKOIL', 'AAPL', 'TSLA'];
const HORIZONS = [12, 24, 48];

function ForecastChart({ actualPath, forecastPath }) {
  const actual = Array.isArray(actualPath) ? actualPath : [];
  const forecast = Array.isArray(forecastPath) ? forecastPath : [];
  const series = [...actual, ...forecast];
  if (!series.length) return <div className="empty">No path data available.</div>;
  const W = 760;
  const H = 260;
  const pad = { top: 12, right: 14, bottom: 24, left: 58 };
  const iw = W - pad.left - pad.right;
  const ih = H - pad.top - pad.bottom;
  const times = series.map((p) => Number(p.time));
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const values = series.map((p) => Number(p.close));
  const vMin = Math.min(...values);
  const vMax = Math.max(...values);
  const span = Math.max(vMax - vMin, 1e-9);
  const x = (t) => pad.left + ((t - tMin) / Math.max(tMax - tMin, 1)) * iw;
  const y = (v) => pad.top + ih - ((v - vMin) / span) * ih;
  const line = (points, dash) => {
    const pts = points.map((p) => `${x(Number(p.time)).toFixed(1)},${y(Number(p.close)).toFixed(1)}`).join(' ');
    return <polyline points={pts} fill="none" strokeWidth={1.8} strokeDasharray={dash} style={{ stroke: 'currentColor' }} />;
  };
  const yTicks = Array.from({ length: 5 }, (_, i) => vMin + (span * i) / 4);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }}>
      {yTicks.map((v) => (
        <g key={v}>
          <line x1={pad.left} x2={W - pad.right} y1={y(v)} y2={y(v)} stroke="rgba(148,163,184,0.15)" strokeWidth={1} />
          <text x={pad.left - 6} y={y(v) + 3} textAnchor="end" fontSize={9} fill="#94a3b8">{fmt(v)}</text>
        </g>
      ))}
      {actual.length > 1 ? (
        <g style={{ color: '#38bdf8' }}>
          {line(actual, '0')}
        </g>
      ) : null}
      {forecast.length > 1 ? (
        <g style={{ color: '#f59e0b' }}>
          {line(forecast, '5 3')}
        </g>
      ) : null}
      <text x={pad.left} y={H - 4} fontSize={9} fill="#38bdf8">Historical close</text>
      {forecast.length ? <text x={pad.left + 90} y={H - 4} fontSize={9} fill="#f59e0b">Kronos forecast</text> : null}
    </svg>
  );
}

export default function PriceForecast() {
  const [symbol, setSymbol] = useState('XAUUSD');
  const [horizon, setHorizon] = useState(24);
  const [data, setData] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    get(`/pro/forecast/${encodeURIComponent(symbol)}?horizon=${horizon}`)
      .then((res) => {
        if (!alive) return;
        setData(res && typeof res === 'object' ? res : {});
      })
      .catch((e) => {
        if (alive) { setError(e.message); setData({}); }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, [symbol, horizon]);

  const ok = data.status === 'ok';
  const dir = ok ? (data.direction || 'neutral') : 'neutral';
  const badgeType = dir === 'buy' ? 'buy' : dir === 'sell' ? 'sell' : 'neutral';
  const change = Number(data.expectedChangePct);

  return (
    <div>
      <div className="page-head">
        <div className="section-title">AI Price Forecast</div>
        <span className="muted" style={{ fontSize: 11 }}>
          Kronos foundation model path forecast · <Badge type="info">PRO</Badge>
        </span>
      </div>

      <Panel title="Forecast" icon="∿" sub="Lazy-loaded NeoQuasar/Kronos-mini — degrades gracefully when the model is unavailable">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
          <select className="select" value={symbol} onChange={(e) => setSymbol(e.target.value)} style={{ fontSize: 11, padding: '4px 8px' }}>
            {ALL_SYMBOLS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select className="select" value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} style={{ fontSize: 11, padding: '4px 8px' }}>
            {HORIZONS.map((h) => <option key={h} value={h}>{h} candles</option>)}
          </select>
          <button className="btn btn-primary" onClick={() => setHorizon((h) => h)} disabled={loading} style={{ fontSize: 11, padding: '4px 10px' }}>
            {loading ? 'Forecasting…' : 'Refresh'}
          </button>
        </div>

        {loading ? <Loading text="Loading forecast…" /> : null}
        {error ? <div className="empty">{error}</div> : null}
        {!loading && !error && !ok ? (
          <div className="empty">Forecast unavailable: {data.error || 'unknown error'}</div>
        ) : null}

        {!loading && ok ? (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', marginBottom: 14 }}>
              <Badge type={badgeType}>{dir.toUpperCase()}</Badge>
              <div style={{ fontSize: 20, fontWeight: 900, color: change >= 0 ? 'var(--green)' : 'var(--red)' }}>
                {change >= 0 ? '+' : ''}{change.toFixed(2)}%
              </div>
              <div className="muted" style={{ fontSize: 11 }}>
                over {data.horizon} candles · confidence <b>{fmtPct(data.confidence, 0)}</b>
              </div>
              <div style={{ marginLeft: 'auto' }} className="muted">
                {data.model} · last {fmt(data.lastClose)}
              </div>
            </div>
            <ForecastChart actualPath={data.actualPath} forecastPath={data.forecastPath} />
            <div className="muted" style={{ fontSize: 10.5, marginTop: 10 }}>
              Predicted close after {data.horizon} candles: <b>{fmt(data.predictedClose)}</b> (from {fmt(data.lastClose)})
            </div>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
