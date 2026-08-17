import { useEffect, useState } from 'react';
import { post, fmtPct, fmt } from '../api.js';
import { Panel, Badge, Loading, StatCard } from '../components/ui.jsx';

const SYMBOLS = ['XAUUSD', 'US500', 'NAS100', 'GER40', 'BTCUSD', 'ETHUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'USOIL', 'US30', 'UK100'];
const TIMEFRAMES = ['M15', 'H1', 'H4', 'D', 'W'];
const CORR_METHODS = ['pearson', 'spearman', 'kendall'];

function BoolBadge({ value, label }) {
  return <Badge type={value ? 'ok' : 'warn'}>{label || (value ? 'YES' : 'NO')}</Badge>;
}

function CapmPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
      {[['Alpha', data.alpha], ['Beta', data.beta], ['Correlation', data.correlation],
        ['R²', data.rSquared], ['Ann. Volatility', data.assetVolatilityAnnualized], ['N', data.n]].map(([label, v]) => (
        <div key={label}>
          <div className="muted" style={{ fontSize: 10.5 }}>{label}</div>
          <div style={{ fontSize: 13, fontWeight: 700 }}>{v != null ? (typeof v === 'number' ? v.toFixed(4) : v) : '—'}</div>
        </div>
      ))}
    </div>
  );
}

function NormalityPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  const sh = data.shapiro;
  const dg = data.dagostino;
  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <span style={{ fontSize: 12 }}>Verdict: </span>
        <Badge type={data.verdict === 'normal' ? 'ok' : 'warn'}>{data.verdict}</Badge>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        {[['Skewness', data.skewness], ['Kurtosis', data.kurtosis], ['N', data.n]].map(([label, v]) => (
          <div key={label}>
            <div className="muted" style={{ fontSize: 10.5 }}>{label}</div>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{v != null ? v.toFixed(4) : '—'}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 8, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <div>
          <div className="muted" style={{ fontSize: 10.5 }}>Shapiro-Wilk</div>
          {sh && !sh.error ? (
            <div style={{ fontSize: 12 }}>W = {sh.statistic} · p = {sh.pValue} <BoolBadge value={sh.normal} label={sh.normal ? 'normal' : 'non-normal'} /></div>
          ) : <span className="muted" style={{ fontSize: 11 }}>{sh && sh.error ? 'skipped (n too large)' : '—'}</span>}
        </div>
        <div>
          <div className="muted" style={{ fontSize: 10.5 }}>D’Agostino K²</div>
          {dg && !dg.error ? (
            <div style={{ fontSize: 12 }}>K² = {dg.statistic} · p = {dg.pValue} <BoolBadge value={dg.normal} label={dg.normal ? 'normal' : 'non-normal'} /></div>
          ) : <span className="muted" style={{ fontSize: 11 }}>{dg && dg.error ? 'skipped (n too small)' : '—'}</span>}
        </div>
      </div>
    </div>
  );
}

function UnitRootPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  const adf = data.adf || {};
  const kpss = data.kpss || {};
  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <span style={{ fontSize: 12 }}>Verdict: </span>
        <Badge type={data.verdict === 'stationary' ? 'ok' : 'warn'}>{data.verdict}</Badge>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 4 }}>ADF</div>
          {!adf.error ? (
            <>
              <div style={{ fontSize: 12 }}>Stat = {adf.statistic} · p = {adf.pValue}</div>
              <div style={{ fontSize: 11, marginTop: 4 }} className="muted">
                <BoolBadge value={adf.stationary} label={adf.stationary ? 'stationary' : 'unit-root present'} />
              </div>
            </>
          ) : <span className="muted" style={{ fontSize: 11 }}>{adf.error}</span>}
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 4 }}>KPSS</div>
          {!kpss.error ? (
            <>
              <div style={{ fontSize: 12 }}>Stat = {kpss.statistic} · p = {kpss.pValue}</div>
              <div style={{ fontSize: 11, marginTop: 4 }} className="muted">
                <BoolBadge value={kpss.stationary} label={kpss.stationary ? 'stationary' : 'unit-root present'} />
              </div>
            </>
          ) : <span className="muted" style={{ fontSize: 11 }}>{kpss.error}</span>}
        </div>
      </div>
    </div>
  );
}

function RollingPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  const c = data.current || {};
  const z = c.zScore;
  const zColor = z != null ? (Math.abs(z) >= 2 ? 'var(--amber)' : 'var(--muted)') : 'var(--muted)';
  return (
    <div>
      <div style={{ marginBottom: 8, fontSize: 12 }}>
        Window <b>{data.window}</b> · Z-score{' '}
        <span style={{ fontWeight: 800, color: zColor }}>{z != null ? z.toFixed(2) : '—'}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        {[['Mean', c.mean], ['Std', c.std], ['Min', c.min], ['Max', c.max], ['Skew', c.skewness], ['Kurt', c.kurtosis]].map(([label, v]) => (
          <div key={label}>
            <div className="muted" style={{ fontSize: 10.5 }}>{label}</div>
            <div style={{ fontSize: 12, fontWeight: 700 }}>{v != null ? v.toFixed(5) : '—'}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CorrPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  const color = data.coefficient >= 0 ? 'var(--green)' : 'var(--red)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-around' }}>
      <div style={{ textAlign: 'center' }}>
        <div className="muted" style={{ fontSize: 10.5 }}>COEFFICIENT</div>
        <div style={{ fontSize: 26, fontWeight: 800, color }}>{data.coefficient != null ? data.coefficient.toFixed(4) : '—'}</div>
      </div>
      <div style={{ textAlign: 'center' }}>
        <div className="muted" style={{ fontSize: 10.5 }}>P-VALUE</div>
        <div style={{ fontSize: 20, fontWeight: 700 }}>{data.pValue != null ? data.pValue.toFixed(4) : '—'}</div>
      </div>
      <div style={{ textAlign: 'center' }}>
        <div className="muted" style={{ fontSize: 10.5 }}>SIGNIFICANT</div>
        <div><BoolBadge value={(data.pValue ?? 1) < 0.05} /></div>
      </div>
    </div>
  );
}

function CointegrationPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <span style={{ fontSize: 12 }}>Engle-Granger · </span>
        <Badge type={data.cointegrated ? 'ok' : 'warn'}>{data.cointegrated ? 'COINTEGRATED' : 'NOT COINTEGRATED'}</Badge>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
        {[['Statistic', data.statistic], ['p-value', data.pValue], ['Crit 1%', data.criticalValues && data.criticalValues['1%']], ['Crit 5%', data.criticalValues && data.criticalValues['5%']]].map(([label, v]) => (
          <div key={label}>
            <div className="muted" style={{ fontSize: 10.5 }}>{label}</div>
            <div style={{ fontSize: 12, fontWeight: 700 }}>{v != null ? v.toFixed(4) : '—'}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function OlsPanel({ data }) {
  if (!data || !data.available) return <div className="empty">{data && data.reason ? `Unavailable: ${data.reason}` : 'Loading…'}</div>;
  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 8, fontSize: 12, flexWrap: 'wrap' }}>
        <span>R² <b>{data.rSquared != null ? data.rSquared.toFixed(4) : '—'}</b></span>
        <span>Adj R² <b>{data.adjRSquared != null ? data.adjRSquared.toFixed(4) : '—'}</b></span>
        <span>F <b>{data.fStatistic != null ? data.fStatistic.toFixed(2) : '—'}</b></span>
        <span>DW <b>{data.dw != null ? data.dw.toFixed(3) : '—'}</b></span>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table className="table" style={{ minWidth: 380 }}>
          <thead>
            <tr><th>Term</th><th>Coef</th><th>Std Err</th><th>t</th><th>p</th><th>Sig</th></tr>
          </thead>
          <tbody>
            {(data.coefficients || []).map((c) => (
              <tr key={c.name}>
                <td><b>{c.name}</b></td>
                <td>{c.coefficient != null ? c.coefficient.toExponential(2) : '—'}</td>
                <td>{c.stdError != null ? c.stdError.toExponential(2) : '—'}</td>
                <td>{c.tStatistic != null ? c.tStatistic.toFixed(2) : '—'}</td>
                <td>{c.pValue != null ? c.pValue.toFixed(4) : '—'}</td>
                <td><BoolBadge value={(c.pValue ?? 1) < 0.05} label={c.pValue < 0.05 ? '***' : '—'} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function QuantStats() {
  const [symbol, setSymbol] = useState('XAUUSD');
  const [benchmark, setBenchmark] = useState('US500');
  const [timeframe, setTimeframe] = useState('D');
  const [method, setMethod] = useState('pearson');
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const loadAll = async () => {
      const out = {};
      const base = { symbol, benchmark, timeframe, method, count: 250 };
      const tests = [
        ['capm', {}],
        ['normality', {}],
        ['unit-root', {}],
        ['rolling-stats', { window: 20 }],
        ['correlation', { method }],
        ['cointegration', {}],
        ['ols', {}],
      ];
      await Promise.all(
        tests.map(async ([key, extra]) => {
          try {
            const res = await post(`/pro/quant/${key}`, { ...base, ...extra });
            if (alive) out[key] = res;
          } catch (e) {
            if (alive) out[key] = { available: false, reason: 'request-failed' };
          }
        })
      );
      if (alive) {
        setResults(out);
        setLoading(false);
      }
    };
    loadAll();
    return () => {
      alive = false;
    };
  }, [symbol, benchmark, timeframe, method]);

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Quant Stats</div>
        <span className="muted" style={{ fontSize: 11 }}>CAPM · Normality · Unit-Root · Rolling Stats · Correlation · Cointegration · OLS</span>
      </div>

      <div className="panel" style={{ marginBottom: 16, display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        <label className="muted" style={{ fontSize: 11 }}>Asset</label>
        <select className="select" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          {SYMBOLS.map((s) => <option key={s}>{s}</option>)}
        </select>
        <label className="muted" style={{ fontSize: 11 }}>Benchmark</label>
        <select className="select" value={benchmark} onChange={(e) => setBenchmark(e.target.value)}>
          {SYMBOLS.filter((s) => s !== symbol).map((s) => <option key={s}>{s}</option>)}
        </select>
        <label className="muted" style={{ fontSize: 11 }}>Timeframe</label>
        <select className="select" value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
          {TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}
        </select>
        <label className="muted" style={{ fontSize: 11 }}>Correlation</label>
        <select className="select" value={method} onChange={(e) => setMethod(e.target.value)}>
          {CORR_METHODS.map((m) => <option key={m}>{m}</option>)}
        </select>
        <Badge type="info">{symbol} vs {benchmark} · {timeframe}</Badge>
      </div>

      {loading ? <Loading text="Running statistical analysis…" /> : null}

      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <StatCard label="CAPM Beta" value={results?.capm?.available ? results.capm.beta.toFixed(3) : '—'} color={results?.capm?.beta > 0 ? 'green' : results?.capm?.beta < 0 ? 'red' : 'blue'} icon="⇄" />
        <StatCard label="Return Normality" value={results?.normality?.available ? (results.normality.verdict === 'normal' ? 'Normal' : 'Non-Normal') : '—'} color={results?.normality?.verdict === 'normal' ? 'green' : 'red'} icon="∿" />
        <StatCard label="Stationarity" value={results?.['unit-root']?.available ? (results['unit-root'].verdict === 'stationary' ? 'Stationary' : 'Unit-Root') : '—'} color={results?.['unit-root']?.verdict === 'stationary' ? 'green' : 'amber'} icon="↯" />
        <StatCard label="Correlation" value={results?.correlation?.available ? results.correlation.coefficient.toFixed(3) : '—'} color={results?.correlation?.coefficient >= 0 ? 'green' : 'red'} icon="◈" />
      </div>

      <div className="grid grid-2">
        <Panel title="CAPM Regression" icon="⇄" sub={`${symbol} vs ${benchmark}`}><CapmPanel data={results?.capm} /></Panel>
        <Panel title="Return Normality" icon="∿" sub="Shapiro-Wilk + D’Agostino"><NormalityPanel data={results?.normality} /></Panel>
        <Panel title="Unit-Root Tests" icon="↯" sub="ADF + KPSS on price series"><UnitRootPanel data={results?.['unit-root']} /></Panel>
        <Panel title="Rolling Statistics" icon="◔" sub="20-period window"><RollingPanel data={results?.['rolling-stats']} /></Panel>
        <Panel title={`Correlation (${method})`} icon="◈" sub={`${symbol} vs ${benchmark} returns`}><CorrPanel data={results?.correlation} /></Panel>
        <Panel title="Cointegration" icon="⚓" sub={`${symbol} vs ${benchmark} prices`}><CointegrationPanel data={results?.cointegration} /></Panel>
        <Panel title="OLS Regression" icon="▧" sub={`${symbol} ~ ${benchmark}`}><OlsPanel data={results?.ols} /></Panel>
      </div>
    </div>
  );
}
