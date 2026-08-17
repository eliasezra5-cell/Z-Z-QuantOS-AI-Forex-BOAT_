import { useEffect, useState } from 'react';
import { get, post, fmtPct } from '../api.js';
import { Panel, Badge, Loading } from '../components/ui.jsx';

const ALL_SYMBOLS = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD', 'ETHUSD', 'US500', 'NAS100', 'US30', 'WTI', 'AAPL', 'TSLA'];

const wPct = (w) => (w == null ? '—' : `${(Number(w) * 100).toFixed(1)}%`);

function WeightTable({ weights, riskStats }) {
  const entries = weights && typeof weights === 'object' ? Object.entries(weights) : [];
  if (!entries.length) return <div className="empty">No allocation yet — run Optimize first.</div>;
  const maxW = Math.max(...entries.map(([, v]) => Number(v) || 0), 0.001);
  return (
    <div>
      {riskStats && (
        <div className="muted" style={{ fontSize: 10.5, marginBottom: 8 }}>
          Expected Volatility <b>{fmtPct(riskStats.expectedVolatility)}</b> · CVaR (95%) <b>{fmtPct(riskStats.cvar)}</b>
        </div>
      )}
      <table className="table">
        <thead>
          <tr><th>Symbol</th><th>Weight</th><th style={{ width: '45%' }}>Allocation</th></tr>
        </thead>
        <tbody>
          {entries.map(([sym, w]) => (
            <tr key={sym}>
              <td><b>{sym}</b></td>
              <td>{wPct(w)}</td>
              <td>
                <div style={{ background: 'var(--accent)', height: 8, borderRadius: 4, width: `${Math.max((Number(w) / maxW) * 100, 2)}%` }} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PerAssetRisk({ perAsset }) {
  const rows = perAsset && typeof perAsset === 'object' ? Object.entries(perAsset) : [];
  if (!rows.length) return <div className="empty">No per-asset risk data.</div>;
  return (
    <table className="table">
      <thead>
        <tr><th>Symbol</th><th>Expected Volatility</th><th>CVaR (95%)</th></tr>
      </thead>
      <tbody>
        {rows.map(([sym, m]) => (
          <tr key={sym}>
            <td><b>{sym}</b></td>
            <td>{fmtPct(m.expectedVolatility)}</td>
            <td>{fmtPct(m.cvar)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StressResult({ result, scenarioName }) {
  if (!result || typeof result !== 'object' || !result.scenario) return null;
  if (result.status === 'degraded') {
    return <div className="empty">Stress test unavailable: {result.error || 'unknown error'}</div>;
  }
  const loss = Number(result.portfolioLossPct);
  const negative = loss < 0;
  const rows = Array.isArray(result.perSymbol) ? result.perSymbol : [];
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <Badge type={negative ? 'warn' : 'ok'}>{negative ? 'LOSS' : 'GAIN'}</Badge>
        <div>
          <div className="muted" style={{ fontSize: 11 }}>Estimated portfolio loss under</div>
          <div style={{ fontSize: 15, fontWeight: 800 }}>{(result.scenario.name || scenarioName)}</div>
        </div>
        <div style={{ marginLeft: 'auto', fontSize: 26, fontWeight: 900, color: negative ? 'var(--red)' : 'var(--green)' }}>
          {negative ? '-' : '+'}{Math.abs(loss).toFixed(2)}%
        </div>
      </div>
      <div className="muted" style={{ fontSize: 10.5, marginBottom: 10 }}>
        Method: <Badge type="info">{result.method === 'skfolio_vine_copula' ? 'skfolio synthetic-data' : 'factor shock model'}</Badge> · Drawdown estimate {fmtPct(result.drawdownEstimatePct)}
      </div>
      {rows.length ? (
        <table className="table">
          <thead>
            <tr><th>Symbol</th><th>Weight</th><th>Shocked Return</th><th>Contribution</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol}>
                <td><b>{r.symbol}</b></td>
                <td>{wPct(r.weight)}</td>
                <td>{fmtPct(r.shockedReturnPct)}</td>
                <td>{fmtPct(r.contributionPct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}

export default function PortfolioOptimizer() {
  const [scenarios, setScenarios] = useState([]);
  const [scenario, setScenario] = useState('');
  const [selectedSymbols, setSelectedSymbols] = useState(['XAUUSD', 'US500', 'WTI']);
  const [allocation, setAllocation] = useState({});
  const [stressResult, setStressResult] = useState({});
  const [optimizing, setOptimizing] = useState(false);
  const [stressing, setStressing] = useState(false);
  const [optError, setOptError] = useState('');
  const [stressError, setStressError] = useState('');
  const [loadingScenarios, setLoadingScenarios] = useState(true);

  useEffect(() => {
    let alive = true;
    get('/pro/portfolio-optimizer/stress-scenarios')
      .then((res) => {
        if (!alive) return;
        const list = Array.isArray(res.scenarios) ? res.scenarios : [];
        setScenarios(list);
        if (list.length && !scenario) setScenario(list[0].id);
      })
      .catch(() => {
        if (alive) setScenarios([]);
      })
      .finally(() => {
        if (alive) setLoadingScenarios(false);
      });
    return () => { alive = false; };
  }, []);

  const toggleSymbol = (sym) => {
    setSelectedSymbols((prev) => (prev.includes(sym) ? prev.filter((s) => s !== sym) : [...prev, sym]));
  };

  const optimize = async () => {
    if (selectedSymbols.length < 2) return;
    setOptimizing(true);
    setOptError('');
    try {
      const res = await post('/pro/portfolio-optimizer/allocate', { symbols: selectedSymbols, lookback: 250 });
      if (res.status === 'degraded') setOptError(res.error || 'Allocation unavailable');
      setAllocation(res);
    } catch (e) {
      setOptError(e.message);
    } finally {
      setOptimizing(false);
    }
  };

  const runStressTest = async () => {
    if (!scenario || selectedSymbols.length === 0) return;
    setStressing(true);
    setStressError('');
    const weights = allocation.status === 'ok' && allocation.hrp ? allocation.hrp.weights : {};
    const effectiveWeights = Object.keys(weights).length
      ? weights
      : Object.fromEntries(selectedSymbols.map((s) => [s, 1 / selectedSymbols.length]));
    try {
      const res = await post('/pro/portfolio-optimizer/stress-test', {
        symbols: selectedSymbols,
        weights: effectiveWeights,
        scenario,
      });
      setStressResult(res);
      if (res.status === 'degraded') setStressError(res.error || 'Stress test unavailable');
    } catch (e) {
      setStressError(e.message);
    } finally {
      setStressing(false);
    }
  };

  const usingEqualWeights = !(allocation.status === 'ok' && allocation.hrp && Object.keys(allocation.hrp.weights || {}).length);

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Portfolio Optimizer</div>
        <span className="muted" style={{ fontSize: 11 }}>
          Risk-based allocation + stress-testing · <Badge type="info">PRO</Badge>
        </span>
      </div>

      <Panel title="1 · Allocation" icon="▨" sub="Pick symbols → risk-balanced HRP & CVaR weight split">
        <div className="muted" style={{ fontSize: 10.5, marginBottom: 8 }}>Active symbols (select at least 2):</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
          {ALL_SYMBOLS.map((sym) => {
            const on = selectedSymbols.includes(sym);
            return (
              <button
                key={sym}
                className={on ? 'btn btn-primary' : 'btn'}
                style={{ fontSize: 11, padding: '4px 10px' }}
                onClick={() => toggleSymbol(sym)}
              >
                {sym} {on ? '✓' : ''}
              </button>
            );
          })}
        </div>
        <button className="btn btn-primary" onClick={optimize} disabled={optimizing || selectedSymbols.length < 2}>
          {optimizing ? 'Optimizing…' : 'Optimize'}
        </button>
        {optError ? <div className="empty" style={{ marginTop: 10 }}>{optError}</div> : null}
        {allocation.status === 'ok' ? (
          <div style={{ marginTop: 14 }}>
            <div className="muted" style={{ fontSize: 10.5, marginBottom: 6 }}>
              Based on {allocation.lookback} daily candles · {allocation.symbols.join(', ')}
            </div>
            <div className="grid grid-2">
              <Panel title="Hierarchical Risk Parity" icon="∿">
                <WeightTable weights={allocation.hrp.weights} riskStats={allocation.hrp.riskStats} />
              </Panel>
              <Panel title="CVaR-Minimizing" icon="▤">
                <WeightTable weights={allocation.cvar.weights} riskStats={allocation.cvar.riskStats} />
              </Panel>
            </div>
            <div style={{ marginTop: 12 }}>
              <Panel title="Per-Asset Risk" icon="◈">
                <PerAssetRisk perAsset={allocation.riskStats?.perAsset} />
              </Panel>
            </div>
          </div>
        ) : null}
      </Panel>

      <div style={{ height: 16 }} />

      <Panel title="2 · Stress Test" icon="⚡" sub="Crisis scenarios mapped to per-asset factor shocks">
        {loadingScenarios ? <Loading text="Loading stress scenarios…" /> : null}
        {!loadingScenarios && !scenarios.length ? (
          <div className="empty">Stress scenarios unavailable — check the /stress-scenarios endpoint.</div>
        ) : (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
              <select className="select" value={scenario} onChange={(e) => setScenario(e.target.value)} style={{ fontSize: 11, padding: '4px 8px' }}>
                {scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
              <Badge type="warn">{usingEqualWeights ? 'Equal weights (run Optimize first)' : 'Using current HRP allocation'}</Badge>
              <button className="btn btn-primary" onClick={runStressTest} disabled={stressing || !scenario || selectedSymbols.length === 0}>
                {stressing ? 'Running…' : 'Run Stress Test'}
              </button>
            </div>
            {stressError ? <div className="empty">{stressError}</div> : null}
            <StressResult result={stressResult} scenarioName={scenario} />
          </div>
        )}
      </Panel>
    </div>
  );
}
