import { useState } from 'react';
import { useFetch } from '../api.js';
import { Panel, Badge, Loading } from './ui.jsx';

function fmt(v, d = 3) { return v == null ? '—' : Number(v).toFixed(d); }

function IchimokuPanel({ data }) {
  if (!data) return <div className="empty">No data.</div>;
  return (
    <div>
      {data.cloudBias && <div style={{ marginBottom: 8 }}>Cloud Bias: <Badge type={data.cloudBias === 'bullish' ? 'ok' : data.cloudBias === 'bearish' ? 'warn' : 'info'}>{data.cloudBias}</Badge></div>}
      {data.cloud && (
        <div className="kv">
          <dt>Tenkan</dt><dd>{fmt(data.cloud.tenkan)}</dd>
          <dt>Kijun</dt><dd>{fmt(data.cloud.kijun)}</dd>
          <dt>Senkou A</dt><dd>{fmt(data.cloud.senkouA)}</dd>
          <dt>Senkou B</dt><dd>{fmt(data.cloud.senkouB)}</dd>
          <dt>Chikou</dt><dd>{fmt(data.cloud.chikou)}</dd>
        </div>
      )}
    </div>
  );
}

function FibonacciPanel({ data }) {
  if (!data) return <div className="empty">No data.</div>;
  const levels = data.levels || [];
  if (!levels.length) return <div className="empty">No levels.</div>;
  return (
    <table className="table">
      <thead><tr><th>Level</th><th>Price</th></tr></thead>
      <tbody>
        {levels.map((l, i) => (
          <tr key={i}><td>{l.level}%</td><td style={{ fontWeight: 700 }}>{fmt(l.price)}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function DeMarkPanel({ data }) {
  if (!data) return <div className="empty">No data.</div>;
  return (
    <div>
      {data.setup && <div style={{ marginBottom: 6 }}>Setup: <b>{data.setup.type}</b> count <b>{data.setup.count}</b></div>}
      {data.countdown && <div>Countdown: <b>{data.countdown.type}</b> count <b>{data.countdown.count}</b></div>}
      {data.phase && <div className="muted" style={{ marginTop: 6 }}>Phase: {data.phase}</div>}
    </div>
  );
}

function DonchianPanel({ data }) {
  if (!data) return <div className="empty">No data.</div>;
  return (
    <div className="kv">
      <dt>Upper</dt><dd>{fmt(data.upper)}</dd>
      <dt>Middle</dt><dd>{fmt(data.middle)}</dd>
      <dt>Lower</dt><dd>{fmt(data.lower)}</dd>
      {data.period && <><dt>Period</dt><dd>{data.period}</dd></>}
    </div>
  );
}

function ClenowPanel({ data }) {
  if (!data) return <div className="empty">No data.</div>;
  return (
    <div>
      <div style={{ display: 'flex', gap: 16, marginBottom: 8 }}>
        <span>Momentum: <b style={{ color: data.momentum >= 0 ? 'var(--green)' : 'var(--red)' }}>{fmt(data.momentum)}</b></span>
        <span>R²: <b>{fmt(data.rSquared)}</b></span>
      </div>
      <div className="muted" style={{ fontSize: 11 }}>{data.note || `${data.window}w regression score`}</div>
    </div>
  );
}

function VolConesPanel({ data }) {
  if (!data) return <div className="empty">No data.</div>;
  const rows = data.cones || [];
  if (!rows.length) return <div className="empty">No cone data.</div>;
  return (
    <table className="table">
      <thead><tr><th>TF</th><th>Current</th><th>Low</th><th>Median</th><th>High</th><th>Rank</th></tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td>{r.timeframe}</td>
            <td style={{ fontWeight: 700 }}>{fmt(r.current)}</td>
            <td className="muted">{fmt(r.low)}</td>
            <td className="muted">{fmt(r.median)}</td>
            <td className="muted">{fmt(r.high)}</td>
            <td>{r.regime || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RrgPanel({ data }) {
  if (!data) return <div className="empty">No data.</div>;
  const best = data.rotation || [];
  return (
    <div>
      <div style={{ marginBottom: 6 }}>Relative rotation vs {data.benchmark || 'benchmark'}:</div>
      {best.length ? best.map((r, i) => (
        <div key={i} className="list-item" style={{ padding: '6px 0', display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ fontWeight: 600 }}>{r.symbol}</span>
          <span>quadrant: <Badge type="info">{r.quadrant}</Badge></span>
        </div>
      )) : <div className="muted">No rotation data.</div>}
    </div>
  );
}

const PANELS = [
  { key: 'ichimoku', label: 'Ichimoku Cloud', fetch: (s, tf) => `/technical/pro/ichimoku/${s}?timeframe=${tf}`, Body: IchimokuPanel },
  { key: 'fibonacci', label: 'Fibonacci Retracement', fetch: (s, tf) => `/technical/pro/fibonacci/${s}?timeframe=${tf}`, Body: FibonacciPanel },
  { key: 'demark', label: 'DeMark Sequential', fetch: (s, tf) => `/technical/pro/demark/${s}?timeframe=${tf}`, Body: DeMarkPanel },
  { key: 'donchian', label: 'Donchian Channel', fetch: (s, tf) => `/technical/pro/donchian/${s}?timeframe=${tf}`, Body: DonchianPanel },
  { key: 'clenow', label: 'Clenow Momentum', fetch: (s, tf) => `/technical/pro/clenow/${s}?timeframe=${tf}`, Body: ClenowPanel },
  { key: 'volcones', label: 'Volatility Cones', fetch: (s, tf) => `/technical/pro/volatility-cones/${s}?timeframe=${tf}`, Body: VolConesPanel },
  { key: 'rrg', label: 'Relative Rotation', fetch: (s, tf) => `/technical/pro/relative-rotation/${s}?timeframe=${tf}&benchmark=US500`, Body: RrgPanel },
];

export default function ProIndicatorsSection({ symbol, timeframe }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState('ichimoku');
  const { data, loading } = useFetch(
    open ? PANELS.find((p) => p.key === active).fetch(symbol, timeframe) : null,
    [symbol, timeframe, active, open]
  );

  const cfg = PANELS.find((p) => p.key === active);

  return (
    <Panel title="Pro Indicators" sub="Ichimoku · Fibonacci · DeMark · Donchian · Clenow · Vol Cones · RRG">
      <button className="btn" style={{ width: '100%', padding: '6px 0' }} onClick={() => setOpen((v) => !v)}>
        {open ? 'Hide Pro Indicators ▲' : 'Show Pro Indicators ▼'}
      </button>
      {open && (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
            {PANELS.map((p) => (
              <button
                key={p.key}
                className="btn"
                onClick={() => setActive(p.key)}
                style={{ padding: '3px 8px', fontSize: 10.5, background: p.key === active ? 'var(--accent)' : undefined, color: p.key === active ? '#000' : undefined }}
              >
                {p.label}
              </button>
            ))}
          </div>
          {loading ? <Loading /> : <cfg.Body data={data} />}
        </div>
      )}
    </Panel>
  );
}
