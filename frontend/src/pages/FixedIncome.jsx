import { useEffect, useState } from 'react';
import { get, fmt } from '../api.js';
import { Panel, Badge, Loading, StatCard } from '../components/ui.jsx';

const HISTORY_SERIES = [
  ['DGS10', 'US 10Y'],
  ['DGS2', 'US 2Y'],
  ['DGS30', 'US 30Y'],
  ['T10Y2Y', '2s10s Spread'],
  ['T10YIE', '10Y Breakeven'],
];

function CurveTable({ curve }) {
  if (!curve || !curve.length) return <div className="empty">No curve data.</div>;
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="table" style={{ minWidth: 380 }}>
        <thead>
          <tr><th>Maturity</th><th>Yield</th><th>FRED Series</th></tr>
        </thead>
        <tbody>
          {curve.map((p) => (
            <tr key={p.maturity}>
              <td><b>{p.maturity.toUpperCase()}</b></td>
              <td style={{ fontWeight: 700 }}>{p.yieldPct != null ? `${p.yieldPct.toFixed(2)}%` : '—'}</td>
              <td className="muted">{p.label}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SpreadBar({ spreads }) {
  if (!spreads) return null;
  const entries = Object.entries(spreads).filter(([, v]) => v != null);
  if (!entries.length) return <div className="empty">No spread data.</div>;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
      {entries.map(([name, v]) => {
        const inverted = v < 0;
        return (
          <div key={name} style={{ textAlign: 'center', padding: 8, border: '1px solid var(--border)', borderRadius: 8 }}>
            <div className="muted" style={{ fontSize: 10.5 }}>{name}</div>
            <div style={{ fontSize: 18, fontWeight: 800, color: inverted ? 'var(--red)' : 'var(--green)' }}>
              {v.toFixed(2)}%
            </div>
            <Badge type={inverted ? 'warn' : 'ok'}>{inverted ? 'INVERTED' : 'POSITIVE'}</Badge>
          </div>
        );
      })}
    </div>
  );
}

function HistoryChart({ data }) {
  if (!data || !data.data || !data.data.length) return <div className="empty">No history data.</div>;
  const values = data.data.map((d) => d.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = Math.max(1, Math.floor(values.length / 48));
  const points = [];
  for (let i = 0; i < values.length; i += step) {
    const v = values[i];
    const x = (i / (values.length - 1)) * 100;
    const y = 100 - ((v - min) / range) * 80 - 10;
    points.push({ x, y, v });
  }
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const last = data.data[data.data.length - 1];
  const first = data.data[0];
  const rising = last.value >= first.value;
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 11 }}>
        <span className="muted">{data.series} · {data.source}</span>
        <span style={{ fontWeight: 700, color: rising ? 'var(--green)' : 'var(--red)' }}>
          {last.value.toFixed(2)} {rising ? '▲' : '▼'}
        </span>
      </div>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: '100%', height: 120, display: 'block' }}>
        <line x1="0" y1="90" x2="100" y2="90" stroke="var(--border)" strokeWidth="0.5" />
        <line x1="0" y1="50" x2="100" y2="50" stroke="var(--border)" strokeWidth="0.3" strokeDasharray="2 2" />
        <line x1="0" y1="10" x2="100" y2="10" stroke="var(--border)" strokeWidth="0.5" />
        <path d={path} fill="none" stroke={rising ? 'var(--green)' : 'var(--red)'} strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}

function OvernightRates({ rates }) {
  if (!rates) return <div className="empty">No overnight rate data.</div>;
  const entries = Object.entries(rates.rates || {}).filter(([, v]) => v && v.value != null);
  if (!entries.length) return <div className="empty">No overnight rate data.</div>;
  return (
    <div>
      {rates.note && <div className="muted" style={{ fontSize: 10.5, marginBottom: 8 }}>{rates.note}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        {entries.map(([name, v]) => (
          <div key={name} style={{ padding: 8, border: '1px solid var(--border)', borderRadius: 8, textAlign: 'center' }}>
            <div className="muted" style={{ fontSize: 10.5 }}>{name.toUpperCase()}</div>
            <div style={{ fontSize: 16, fontWeight: 800 }}>{v.value.toFixed(2)}%</div>
            {v.date && <div className="muted" style={{ fontSize: 9.5 }}>{v.date}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

function SpreadSummary({ spreads }) {
  if (!spreads) return <div className="empty">No spread data.</div>;
  const s = spreads.spreads || {};
  const entries = Object.entries(s).filter(([, v]) => typeof v === 'number');
  if (!entries.length) return <div className="empty">No spread data.</div>;
  return (
    <div>
      {s.note && <div className="muted" style={{ fontSize: 10.5, marginBottom: 8 }}>{s.note}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        {entries.map(([name, v]) => (
          <div key={name} style={{ padding: 8, border: '1px solid var(--border)', borderRadius: 8, textAlign: 'center' }}>
            <div className="muted" style={{ fontSize: 10.5 }}>{name}</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: v < 0 ? 'var(--red)' : 'var(--green)' }}>{v.toFixed(2)}%</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function YieldCurveBars({ curve }) {
  if (!curve || !curve.curve || !curve.curve.length) return <div className="empty">No yield-curve data.</div>;
  const rows = curve.curve;
  const maxY = Math.max(...rows.map((p) => p.yieldPct || 0), 0.1);
  return (
    <div>
      {curve.note && <div className="muted" style={{ fontSize: 10.5, marginBottom: 8 }}>{curve.note}</div>}
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10, height: 110, paddingTop: 6 }}>
        {rows.map((p) => (
          <div key={p.maturity} style={{ flex: 1, textAlign: 'center' }}>
            <div style={{ fontSize: 11, fontWeight: 700 }}>{p.yieldPct != null ? p.yieldPct.toFixed(2) : '—'}</div>
            <div style={{ height: `${Math.max((p.yieldPct || 0) / maxY * 70, 3)}px`, background: 'var(--accent)', borderRadius: 4, marginTop: 4 }} />
            <div className="muted" style={{ fontSize: 10 }}>{p.maturity.toUpperCase()}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function FixedIncome() {
  const [curve, setCurve] = useState({});
  const [overview, setOverview] = useState({});
  const [history, setHistory] = useState({});
  const [historySeries, setHistorySeries] = useState('DGS10');
  const [spec, setSpec] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [c, o, h] = await Promise.all([
          get('/pro/fixedincome/curve'),
          get('/pro/fixedincome/overview'),
          get(`/pro/fixedincome/history?series=${historySeries}&count=250`),
        ]);
        if (alive) {
          setCurve(c.data || {});
          setOverview(o.data || {});
          setHistory(h.data || {});
        }
        try {
          const [yc, rt, sp] = await Promise.all([
            get('/pro/fixedincome/yield-curve'),
            get('/pro/fixedincome/rates'),
            get('/pro/fixedincome/spreads'),
          ]);
          if (alive) setSpec({ curve: yc.data, rates: rt.data, spreads: sp.data });
        } catch (e2) {
          /* spec section renders empty */
        }
      } catch (e) {
        /* panels render empty state */
      } finally {
        if (alive) setLoading(false);
      }
    };
    load();
    return () => { alive = false; };
  }, [historySeries]);

  const curveData = curve.curve || [];
  const source = curve.source || overview.source || '—';

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Fixed Income</div>
        <span className="muted" style={{ fontSize: 11 }}>
          {source === 'fred' ? 'Live FRED data' : 'Simulated curve (FRED key not set)'} · <Badge type={source === 'fred' ? 'ok' : 'warn'}>{source}</Badge>
        </span>
      </div>

      {overview.note && <div className="muted" style={{ fontSize: 11, marginBottom: 12 }}>{overview.note}</div>}

      {loading ? <Loading text="Loading fixed income data…" /> : null}

      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <StatCard label="US 10Y" value={overview.us10y != null ? `${overview.us10y.toFixed(2)}%` : '—'} icon="◉" />
        <StatCard label="US 2Y" value={overview.us2y != null ? `${overview.us2y.toFixed(2)}%` : '—'} icon="◉" />
        <StatCard label="2s10s Spread" value={overview.spread2s10s != null ? `${overview.spread2s10s.toFixed(2)}%` : '—'} color={overview.spread2s10s != null && overview.spread2s10s < 0 ? 'red' : 'green'} icon="⇄" />
        <StatCard label="Curve" value={overview.invertedCurve ? 'INVERTED' : 'NORMAL'} color={overview.invertedCurve ? 'red' : 'green'} icon="⌃" />
      </div>

      <div className="grid grid-2">
        <Panel title="US Treasury Yield Curve" icon="⌃" sub="1M → 30Y">
          <CurveTable curve={curveData} />
        </Panel>
        <div>
          <Panel title="Key Spreads" icon="⇄" sub="Negative = inverted" style={{ marginBottom: 16 }}>
            <SpreadBar spreads={curve.spreads} />
          </Panel>
          <Panel title="Money Rates" icon="▤">
            {curve.rates && Object.keys(curve.rates).length ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                {Object.entries(curve.rates).filter(([, v]) => v != null).map(([name, v]) => (
                  <div key={name} style={{ textAlign: 'center' }}>
                    <div className="muted" style={{ fontSize: 10.5 }}>{name}</div>
                    <div style={{ fontSize: 15, fontWeight: 700 }}>{v.toFixed(2)}%</div>
                  </div>
                ))}
              </div>
            ) : <div className="empty">No money rate data.</div>}
          </Panel>
        </div>
        <Panel title="Yield History" icon="∿" sub={
          <select className="select" value={historySeries} onChange={(e) => setHistorySeries(e.target.value)} style={{ fontSize: 11, padding: '2px 6px' }}>
            {HISTORY_SERIES.map(([sid, label]) => <option key={sid} value={sid}>{label}</option>)}
          </select>
        }>
          <HistoryChart data={history} />
        </Panel>
        <Panel title="Policy & Inflation" icon="◈">
          {curve.rates && curve.rates.fedFunds != null ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <div>
                <div className="muted" style={{ fontSize: 10.5 }}>Fed Funds Target</div>
                <div style={{ fontSize: 20, fontWeight: 800 }}>{curve.rates.fedFunds.toFixed(2)}%</div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 10.5 }}>Breakeven 10Y (BEI)</div>
                <div style={{ fontSize: 20, fontWeight: 800 }}>{curve.breakevens && curve.breakevens.breakeven10y != null ? `${curve.breakevens.breakeven10y.toFixed(2)}%` : '—'}</div>
              </div>
            </div>
          ) : <div className="empty">No policy data.</div>}
        </Panel>
      </div>

      <div style={{ height: 16 }} />
      <div className="section-title" style={{ fontSize: 14 }}>Spec Rates Surface</div>
      <div className="grid grid-3" style={{ marginTop: 10 }}>
        <Panel title="Yield Curve" icon="⌃" sub="2Y · 5Y · 10Y · 30Y (FRED)">
          <YieldCurveBars curve={spec?.curve} />
        </Panel>
        <Panel title="Overnight Rates" icon="▤" sub="SOFR · EFFR · ESTR · SONIA">
          <OvernightRates rates={spec?.rates} />
        </Panel>
        <Panel title="Spreads" icon="⇄" sub="Treasury-EFFR · HQM corporate">
          <SpreadSummary spreads={spec?.spreads} />
        </Panel>
      </div>
    </div>
  );
}
