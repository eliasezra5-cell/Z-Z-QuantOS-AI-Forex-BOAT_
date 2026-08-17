import { useEffect, useState } from 'react';
import { get, fmt, fmtPct } from '../api.js';
import { Panel, Badge, Loading, StatCard } from '../components/ui.jsx';

const SYMBOLS = ['XAUUSD', 'US500', 'NAS100', 'GER40', 'BTCUSD', 'ETHUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'USOIL', 'US30', 'UK100'];

const TIMEFRAMES = ['M15', 'H1', 'H4', 'D', 'W'];

const ICONS = {
  ichimoku: '☯',
  fibonacci: '▦',
  demark: '9',
  donchian: '▤',
  clenow: '⇄',
  'volatility-cones': '◉',
  'relative-rotation': '◈',
};

function IchimokuPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  const bias = data.cloudBias;
  const color = bias === 'bullish' ? 'var(--green)' : bias === 'bearish' ? 'var(--red)' : 'var(--amber)';
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      {[['Tenkan', data.tenkan], ['Kijun', data.kijun], ['Senkou A', data.senkouA], ['Senkou B', data.senkouB], ['Chikou', data.chikou]].map(([label, v]) => (
        <div key={label}>
          <div className="muted" style={{ fontSize: 10.5 }}>{label}</div>
          <div style={{ fontSize: 13, fontWeight: 700 }}>{v != null ? fmt(v) : '—'}</div>
        </div>
      ))}
      <div>
        <div className="muted" style={{ fontSize: 10.5 }}>Cloud Bias</div>
        <div style={{ fontSize: 13, fontWeight: 800, color }}>{bias.toUpperCase()}</div>
      </div>
    </div>
  );
}

function FibonacciPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 8, fontSize: 12 }}>
        <span>High <b>{fmt(data.swingHigh)}</b></span>
        <span>Low <b>{fmt(data.swingLow)}</b></span>
        <span className="pill" style={{ fontSize: 10.5 }}>{data.bias}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
        {(data.levels || []).map((lvl) => (
          <div key={lvl.level} className="panel" style={{ margin: 0, padding: '6px 8px' }}>
            <div className="muted" style={{ fontSize: 10 }}>{lvl.level}</div>
            <div style={{ fontSize: 12, fontWeight: 700 }}>{lvl.price != null ? fmt(lvl.price) : '—'}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DemarkPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  const signal = data.signal;
  const color = signal.includes('buy') ? 'var(--green)' : signal.includes('sell') ? 'var(--red)' : 'var(--muted)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-around' }}>
      <div style={{ textAlign: 'center' }}>
        <div className="muted" style={{ fontSize: 10.5 }}>BUY SETUP</div>
        <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--green)' }}>{data.buySetup}</div>
      </div>
      <div style={{ textAlign: 'center' }}>
        <div className="muted" style={{ fontSize: 10.5 }}>SELL SETUP</div>
        <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--red)' }}>{data.sellSetup}</div>
      </div>
      <div style={{ textAlign: 'center' }}>
        <div className="muted" style={{ fontSize: 10.5 }}>SIGNAL</div>
        <div style={{ fontSize: 13, fontWeight: 800, color }}>{signal.replace(/-/g, ' ').toUpperCase()}</div>
      </div>
    </div>
  );
}

function DonchianPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  const pos = data.position != null ? data.position : null;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      {[['Upper', data.upper], ['Middle', data.middle], ['Lower', data.lower], ['Price', data.price]].map(([label, v]) => (
        <div key={label}>
          <div className="muted" style={{ fontSize: 10.5 }}>{label}</div>
          <div style={{ fontSize: 13, fontWeight: 700 }}>{v != null ? fmt(v) : '—'}</div>
        </div>
      ))}
      <div>
        <div className="muted" style={{ fontSize: 10.5 }}>Channel Position</div>
        <div style={{ fontSize: 13, fontWeight: 700 }}>{pos != null ? fmtPct(pos) : '—'}</div>
      </div>
    </div>
  );
}

function ClenowPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  const trend = data.trend;
  const color = trend === 'positive' ? 'var(--green)' : trend === 'negative' ? 'var(--red)' : 'var(--amber)';
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontSize: 24, fontWeight: 800, color }}>{data.momentum != null ? data.momentum.toFixed(4) : '—'}</span>
        <Badge type="info">{trend}</Badge>
      </div>
      <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {[['R²', fmtPct(data.rSquared)], ['Ann. Vol', data.annualizedVolatility != null ? fmtPct(data.annualizedVolatility) : '—'], ['Slope', data.slope != null ? data.slope.toFixed(6) : '—'], ['Period', data.period]].map(([label, v]) => (
          <div key={label}>
            <div className="muted" style={{ fontSize: 10.5 }}>{label}</div>
            <div style={{ fontSize: 12, fontWeight: 700 }}>{v}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function VolConesPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="table" style={{ minWidth: 420 }}>
        <thead>
          <tr>
            <th>Period</th>
            <th>Min</th>
            <th>P25</th>
            <th>Median</th>
            <th>P75</th>
            <th>Max</th>
            <th>Now</th>
            <th>Rank</th>
            <th>Regime</th>
          </tr>
        </thead>
        <tbody>
          {(data.cones || []).filter((c) => c.available).map((c) => {
            const p = c.percentiles;
            const color = c.regime === 'high-vol' ? 'var(--red)' : c.regime === 'low-vol' ? 'var(--green)' : 'var(--muted)';
            return (
              <tr key={c.period}>
                <td><b>{c.period}d</b></td>
                <td>{p.min != null ? fmtPct(p.min) : '—'}</td>
                <td>{p.p25 != null ? fmtPct(p.p25) : '—'}</td>
                <td>{p.median != null ? fmtPct(p.median) : '—'}</td>
                <td>{p.p75 != null ? fmtPct(p.p75) : '—'}</td>
                <td>{p.max != null ? fmtPct(p.max) : '—'}</td>
                <td style={{ fontWeight: 700 }}>{p.current != null ? fmtPct(p.current) : '—'}</td>
                <td>{c.percentileRank != null ? fmtPct(c.percentileRank) : '—'}</td>
                <td style={{ color, fontWeight: 700 }}>{c.regime}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RotationPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  const quadrant = data.quadrant;
  const color = quadrant === 'leading' ? 'var(--green)' : quadrant === 'improving' ? 'var(--amber)' : quadrant === 'weakening' ? 'var(--amber)' : 'var(--red)';
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      {[['vs', data.benchmark], ['RS Ratio', data.rsRatio != null ? data.rsRatio.toFixed(4) : '—'], ['RS Z-Score', data.rsZScore != null ? data.rsZScore.toFixed(2) : '—'], ['RS Momentum', data.rsMomentum != null ? data.rsMomentum.toFixed(4) : '—']].map(([label, v]) => (
        <div key={label}>
          <div className="muted" style={{ fontSize: 10.5 }}>{label}</div>
          <div style={{ fontSize: 13, fontWeight: 700 }}>{v}</div>
        </div>
      ))}
      <div>
        <div className="muted" style={{ fontSize: 10.5 }}>Quadrant</div>
        <div style={{ fontSize: 13, fontWeight: 800, color }}>{quadrant.toUpperCase()}</div>
      </div>
    </div>
  );
}

const PANELS = {
  ichimoku: { label: 'Ichimoku Cloud', icon: ICONS.ichimoku, component: IchimokuPanel, path: 'ichimoku' },
  fibonacci: { label: 'Fibonacci Retracement', icon: ICONS.fibonacci, component: FibonacciPanel, path: 'fibonacci' },
  demark: { label: 'DeMark Sequential', icon: ICONS.demark, component: DemarkPanel, path: 'demark' },
  donchian: { label: 'Donchian Channel', icon: ICONS.donchian, component: DonchianPanel, path: 'donchian' },
  clenow: { label: 'Clenow Momentum', icon: ICONS.clenow, component: ClenowPanel, path: 'clenow' },
  'volatility-cones': { label: 'Volatility Cones', icon: ICONS['volatility-cones'], component: VolConesPanel, path: 'volatility-cones' },
  'relative-rotation': { label: 'Relative Rotation', icon: ICONS['relative-rotation'], component: RotationPanel, path: 'relative-rotation' },
};

const BENCHMARKS = ['US500', 'NAS100', 'GER40', 'UK100', 'US30', 'XAUUSD', 'BTCUSD'];

export default function ProIndicators() {
  const [symbol, setSymbol] = useState('XAUUSD');
  const [timeframe, setTimeframe] = useState('H1');
  const [benchmark, setBenchmark] = useState('US500');
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const loadAll = async () => {
      const out = {};
      let firstErr = null;
      await Promise.all(
        Object.entries(PANELS).map(async ([key, cfg]) => {
          try {
            const query = key === 'relative-rotation' ? `?benchmark=${encodeURIComponent(benchmark)}` : '';
            const res = await get(`/technical/pro/${cfg.path}/${symbol}${query}`);
            if (alive) out[key] = res;
          } catch (e) {
            if (alive) {
              out[key] = { available: false, reason: 'request-failed' };
              firstErr = firstErr || e.message;
            }
          }
        })
      );
      if (alive) {
        setResults(out);
        setError(firstErr);
        setLoading(false);
      }
    };
    loadAll();
    return () => {
      alive = false;
    };
  }, [symbol, timeframe, benchmark]);

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Pro Indicators</div>
        <span className="muted" style={{ fontSize: 11 }}>Ichimoku · Fibonacci · DeMark · Donchian · Clenow · Vol Cones · RRG</span>
      </div>

      <div className="panel" style={{ marginBottom: 16, display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        <label className="muted" style={{ fontSize: 11 }}>Symbol</label>
        <select className="select" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          {SYMBOLS.map((s) => <option key={s}>{s}</option>)}
        </select>
        <label className="muted" style={{ fontSize: 11 }}>Timeframe</label>
        <select className="select" value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
          {TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}
        </select>
        <label className="muted" style={{ fontSize: 11 }}>Benchmark (RRG)</label>
        <select className="select" value={benchmark} onChange={(e) => setBenchmark(e.target.value)}>
          {BENCHMARKS.filter((b) => b !== symbol).map((b) => <option key={b}>{b}</option>)}
        </select>
        <Badge type="info">{symbol} · {timeframe}</Badge>
      </div>

      {loading ? (
        <Loading text="Computing pro indicators…" />
      ) : error ? (
        <div className="alert" style={{ color: 'var(--red)' }}>Some requests failed: {error}</div>
      ) : null}

      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <StatCard label="Ichimoku Bias" value={results?.ichimoku?.available ? (results.ichimoku.cloudBias || '—').toUpperCase() : '—'} icon="☯" />
        <StatCard label="DeMark Buy Setup" value={results?.demark?.available ? results.demark.buySetup : '—'} color="green" icon="9" />
        <StatCard label="DeMark Sell Setup" value={results?.demark?.available ? results.demark.sellSetup : '—'} color="red" icon="9" />
        <StatCard label="Clenow Momentum" value={results?.clenow?.available ? results.clenow.momentum.toFixed(4) : '—'} color={results?.clenow?.trend === 'positive' ? 'green' : results?.clenow?.trend === 'negative' ? 'red' : 'blue'} icon="⇄" />
      </div>

      <div className="grid grid-2">
        <Panel title="Ichimoku Cloud" icon={PANELS.ichimoku.icon}><IchimokuPanel data={results?.ichimoku} /></Panel>
        <Panel title="Fibonacci Retracement" icon={PANELS.fibonacci.icon}><FibonacciPanel data={results?.fibonacci} /></Panel>
        <Panel title="DeMark Sequential" icon={PANELS.demark.icon}><DemarkPanel data={results?.demark} /></Panel>
        <Panel title={`Donchian Channel (${results?.donchian?.period || 20})`} icon={PANELS.donchian.icon}><DonchianPanel data={results?.donchian} /></Panel>
        <Panel title="Clenow Momentum" icon={PANELS.clenow.icon} sub="Regression slope × R² × ann. volatility"><ClenowPanel data={results?.clenow} /></Panel>
        <Panel title="Volatility Cones" icon={PANELS['volatility-cones'].icon} sub="Realized vol percentiles"><VolConesPanel data={results?.['volatility-cones']} /></Panel>
        <Panel title="Relative Rotation (RRG)" icon={PANELS['relative-rotation'].icon} sub={`vs ${benchmark}`}><RotationPanel data={results?.['relative-rotation']} /></Panel>
      </div>
    </div>
  );
}
