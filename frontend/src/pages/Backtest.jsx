import { useState } from 'react';
import { useFetch, post } from '../api.js';
import { Panel, Badge, Loading, StatCard, Sparkline } from '../components/ui.jsx';
import { SYMBOL_LIST, useSymbol } from '../symbols.jsx';

const STRATEGIES = ['trend-follow', 'rsi-mean-reversion', 'bollinger-reversion', 'macd-cross', 'breakout-donchian', 'smc-liquidity'];

const fmtPct2 = (n) => (n == null ? '—' : `${Number(n) >= 0 ? '+' : ''}${Number(n).toFixed(2)}%`);
const fmtN = (n, d = 2) => (n == null ? '—' : Number(n).toFixed(d));

function DrawdownChart({ series }) {
  const pts = Array.isArray(series) ? series : [];
  if (!pts.length) return <div className="empty">No drawdown data.</div>;
  const W = 760;
  const H = 130;
  const pad = { top: 8, right: 12, bottom: 20, left: 40 };
  const iw = W - pad.left - pad.right;
  const ih = H - pad.top - pad.bottom;
  const dds = pts.map((p) => Number(p.drawdownPct));
  const min = Math.min(...dds, 0);
  const max = 0;
  const x = (i) => pad.left + (i / Math.max(pts.length - 1, 1)) * iw;
  const y = (v) => pad.top + ((max - v) / Math.max(max - min, 1e-9)) * ih;
  const poly = pts.map((p, i) => `${x(i).toFixed(1)},${y(Number(p.drawdownPct)).toFixed(1)}`).join(' ');
  const ticks = Array.from({ length: 4 }, (_, i) => min + ((max - min) * i) / 3);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }}>
      {ticks.map((v) => (
        <g key={v}>
          <line x1={pad.left} x2={W - pad.right} y1={y(v)} y2={y(v)} stroke="rgba(148,163,184,0.15)" />
          <text x={pad.left - 6} y={y(v) + 3} textAnchor="end" fontSize={9} fill="#94a3b8">{v.toFixed(0)}%</text>
        </g>
      ))}
      <polyline points={poly} fill="none" stroke="#ef4444" strokeWidth={1.6} />
      <polygon points={`${pad.left},${y(0)} ${poly} ${x(pts.length - 1)},${y(0)}`} fill="rgba(239,68,68,0.12)" />
    </svg>
  );
}

function MonthlyTable({ rows }) {
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) return <div className="empty">No monthly data.</div>;
  return (
    <table className="table">
      <thead>
        <tr><th>Month</th><th>Start</th><th>End</th><th>Return</th></tr>
      </thead>
      <tbody>
        {list.map((m) => (
          <tr key={m.month}>
            <td><b>{m.month}</b></td>
            <td>${m.startEquity.toLocaleString()}</td>
            <td>${m.endEquity.toLocaleString()}</td>
            <td className={m.returnPct >= 0 ? 'green' : 'red'} style={{ fontWeight: 700 }}>{fmtPct2(m.returnPct)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TradeStatsTable({ stats }) {
  if (!stats || typeof stats !== 'object') return <div className="empty">No trade stats.</div>;
  const rows = [
    ['Total Trades', stats.totalTrades ?? '—'],
    ['Win Rate', `${fmtN(stats.winRate, 1)}%`],
    ['Profit Factor', fmtN(stats.profitFactor)],
    ['Expectancy', `$${fmtN(stats.expectancy)}`],
    ['Avg Win', `$${fmtN(stats.avgWin)}`],
    ['Avg Loss', `$${fmtN(stats.avgLoss)}`],
    ['Largest Win', `$${fmtN(stats.largestWin)}`],
    ['Largest Loss', `$${fmtN(stats.largestLoss)}`],
    ['Longest Win Streak', stats.longestWinStreak ?? '—'],
    ['Longest Loss Streak', stats.longestLossStreak ?? '—'],
  ];
  const byReason = stats.byReason && typeof stats.byReason === 'object' ? stats.byReason : {};
  return (
    <div>
      <div className="kv">
        {rows.map(([k, v]) => <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0' }}><dt>{k}</dt><dd>{v}</dd></div>)}
      </div>
      {Object.keys(byReason).length ? (
        <div style={{ marginTop: 10 }}>
          <div className="muted" style={{ fontSize: 10.5, marginBottom: 6 }}>By exit reason</div>
          <table className="table">
            <thead><tr><th>Reason</th><th>Count</th><th>Net</th><th>Avg</th></tr></thead>
            <tbody>
              {Object.entries(byReason).map(([reason, r]) => (
                <tr key={reason}>
                  <td><b>{reason}</b></td>
                  <td>{r.count}</td>
                  <td className={r.netProfit >= 0 ? 'green' : 'red'}>{`$${r.netProfit.toFixed(2)}`}</td>
                  <td>{`$${r.avgProfit.toFixed(2)}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

export default function Backtest() {
  const { symbol, setSymbol } = useSymbol();
  const [tab, setTab] = useState('lab');
  const [params, setParams] = useState({ strategy: 'trend-follow', timeframe: 'H1', candles: 500, riskPerTrade: 0.02 });
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [tearsheet, setTearsheet] = useState({});
  const [tsRunning, setTsRunning] = useState(false);
  const { data: compare, refresh: refreshCompare } = useFetch(`/backtest/compare?symbol=${symbol}&timeframe=H1`, [symbol]);

  const run = async () => {
    setRunning(true);
    try {
      const res = await post('/backtest/run', { ...params, symbol, candles: parseInt(params.candles, 10), riskPerTrade: parseFloat(params.riskPerTrade) });
      setResult(res);
      refreshCompare();
    } finally {
      setRunning(false);
    }
  };

  const runTearsheet = async () => {
    setTsRunning(true);
    try {
      const res = await post('/pro/backtest/tearsheet', {
        symbol,
        strategy: params.strategy,
        timeframe: params.timeframe,
        candles: parseInt(params.candles, 10) || 500,
        riskPerTrade: parseFloat(params.riskPerTrade) || 0.02,
      });
      setTearsheet(res && typeof res === 'object' ? res : {});
    } finally {
      setTsRunning(false);
    }
  };

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Backtesting Lab</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {SYMBOL_LIST.map(([s]) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={params.strategy} onChange={(e) => setParams({ ...params, strategy: e.target.value })}>
            {STRATEGIES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={params.timeframe} onChange={(e) => setParams({ ...params, timeframe: e.target.value })}>
            {['M15', 'M30', 'H1', 'H4', 'D1'].map((t) => <option key={t}>{t}</option>)}
          </select>
          <select value={params.candles} onChange={(e) => setParams({ ...params, candles: e.target.value })}>
            {[300, 500, 1000].map((c) => <option key={c} value={c}>{c} bars</option>)}
          </select>
          {tab === 'lab' ? (
            <button className="btn btn-primary" onClick={run} disabled={running}>{running ? 'Running...' : 'Run Backtest'}</button>
          ) : (
            <button className="btn btn-primary" onClick={runTearsheet} disabled={tsRunning}>{tsRunning ? 'Building...' : 'Build Tearsheet'}</button>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
        <button className={`btn ${tab === 'lab' ? 'btn-primary' : ''}`} onClick={() => setTab('lab')}>Lab</button>
        <button className={`btn ${tab === 'tearsheet' ? 'btn-primary' : ''}`} onClick={() => setTab('tearsheet')}>Tearsheet</button>
      </div>

      {tab === 'lab' && (
        <>
          {result && (
            <>
              <div className="grid grid-4">
                <StatCard label="Net Profit" value={`$${result.netProfit}`} color={result.netProfit >= 0 ? 'green' : 'red'} sub={`${result.returnPct}% return`} />
                <StatCard label="Win Rate" value={`${result.winRate}%`} color="blue" />
                <StatCard label="Profit Factor" value={result.profitFactor} color="purple" />
                <StatCard label="Max Drawdown" value={`${result.maxDrawdown}%`} color="red" />
              </div>
              <div style={{ height: 16 }} />
              <div className="grid grid-3">
                <Panel title="Equity Curve" sub={`${params.strategy} on ${symbol} ${params.timeframe}`} style={{ gridColumn: 'span 2' }}>
                  <Sparkline data={(result.equityCurve || []).map((e) => e.value)} color="var(--accent)" height={180} />
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }} className="muted">
                    <span>Start: ${result.initialCapital.toLocaleString()}</span>
                    <span>Final: ${result.finalCapital.toLocaleString()}</span>
                    <span>Trades: {result.totalTrades}</span>
                  </div>
                </Panel>
                <Panel title="Summary">
                  <div className="kv">
                    <dt>Strategy</dt><dd>{result.strategy}</dd>
                    <dt>Symbol</dt><dd>{result.symbol}</dd>
                    <dt>Timeframe</dt><dd>{result.timeframe}</dd>
                    <dt>Avg Trade</dt><dd>${result.avgTrade}</dd>
                    <dt>Profit Factor</dt><dd>{result.profitFactor}</dd>
                    <dt>Max DD</dt><dd className="red">{result.maxDrawdown}%</dd>
                  </div>
                </Panel>
              </div>

              <div style={{ height: 16 }} />
              <Panel title="Trade List" sub="Last 15 trades">
                <table>
                  <thead><tr><th>Side</th><th>Entry</th><th>Exit</th><th>Volume</th><th>Profit</th><th>Reason</th></tr></thead>
                  <tbody>
                    {(result.trades || []).slice(-15).map((t, i) => (
                      <tr key={i}>
                        <td><Badge type={t.side}>{t.side}</Badge></td>
                        <td>{t.entryPrice?.toFixed(5)}</td>
                        <td>{t.exitPrice?.toFixed(5)}</td>
                        <td>{t.volume}</td>
                        <td className={t.profit >= 0 ? 'green' : 'red'} style={{ fontWeight: 700 }}>${t.profit}</td>
                        <td className="muted">{t.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
            </>
          )}

          <div style={{ height: 16 }} />
          <Panel title="Strategy Comparison" sub="Head-to-head across all strategies">
            <table>
              <thead><tr><th>Strategy</th><th>Net Profit</th><th>Return</th><th>Win Rate</th><th>PF</th><th>Max DD</th><th>Trades</th></tr></thead>
              <tbody>
                {(compare || []).map((c) => (
                  <tr key={c.strategy}>
                    <td style={{ fontWeight: 600 }}>{c.strategy}</td>
                    <td className={c.netProfit >= 0 ? 'green' : 'red'} style={{ fontWeight: 700 }}>${c.netProfit}</td>
                    <td>{c.returnPct}%</td>
                    <td>{c.winRate}%</td>
                    <td>{c.profitFactor}</td>
                    <td>{c.maxDrawdown}%</td>
                    <td>{c.totalTrades}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}

      {tab === 'tearsheet' && (
        <>
          {tsRunning ? <Loading /> : null}
          {!tsRunning && tearsheet.status === 'degraded' ? <div className="empty">Tearsheet unavailable: {tearsheet.error || 'unknown error'}</div> : null}
          {!tsRunning && tearsheet.status === 'ok' ? (
            <>
              <div className="grid grid-4">
                <StatCard label="CAGR" value={fmtPct2(tearsheet.performance.cagrPct)} color={tearsheet.performance.cagrPct >= 0 ? 'green' : 'red'} />
                <StatCard label="Sharpe" value={fmtN(tearsheet.performance.sharpe)} color="blue" sub={`Sortino ${fmtN(tearsheet.performance.sortino)}`} />
                <StatCard label="Calmar" value={fmtN(tearsheet.performance.calmar)} color="purple" />
                <StatCard label="Max Drawdown" value={fmtPct2(tearsheet.performance.maxDrawdownPct)} color="red" sub={`Vol ${fmtN(tearsheet.performance.volatilityPct, 1)}%`} />
              </div>
              <div style={{ height: 16 }} />
              <div className="grid grid-3">
                <Panel title="Drawdown" sub={`${tearsheet.summary.strategy} on ${tearsheet.summary.symbol} ${tearsheet.summary.timeframe}`} style={{ gridColumn: 'span 2' }}>
                  <DrawdownChart series={tearsheet.drawdownSeries} />
                  <div className="muted" style={{ fontSize: 10.5, marginTop: 6 }}>
                    Net profit <b className={tearsheet.summary.netProfit >= 0 ? 'green' : 'red'}>${tearsheet.summary.netProfit.toLocaleString()}</b> · {fmtPct2(tearsheet.summary.returnPct)} · {tearsheet.summary.totalTrades} trades
                  </div>
                </Panel>
                <Panel title="Trade Stats">
                  <TradeStatsTable stats={tearsheet.tradeStats} />
                </Panel>
              </div>
              <div style={{ height: 16 }} />
              <Panel title="Monthly Returns">
                <MonthlyTable rows={tearsheet.monthlyReturns} />
              </Panel>
            </>
          ) : null}
        </>
      )}
    </div>
  );
}
