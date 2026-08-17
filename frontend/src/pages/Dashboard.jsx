import { useEffect, useState } from 'react';
import { get, useFetch, useLiveQuotes, fmt, fmtPct, fmtMoney, normalizeDecision } from '../api.js';
import { StatCard, Panel, Badge, Bar, Sparkline, Loading, ErrorMsg } from '../components/ui.jsx';
import CandleChart from '../components/CandleChart.jsx';
import TradingViewChart from '../components/TradingViewChart.jsx';
import { SYMBOL_LIST, useSymbol } from '../symbols.jsx';

const TV_TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1'];

export default function Dashboard() {
  const { symbol, setSymbol } = useSymbol();
  const { data: quotes, loading: qLoad } = useFetch('/market/quotes');
  const { data: portfolio, loading: pLoad } = useFetch('/portfolio/overview');
  const { data: news, loading: nLoad } = useFetch('/news?limit=6');
  const { data: events, loading: eLoad } = useFetch('/economic/calendar?limit=6');
  const { data: health, loading: hLoad } = useFetch('/system/overview');
  const { data: mt5, loading: mLoad, refresh: refreshMt5 } = useFetch('/mt5/status');
  const { data: candles } = useFetch(`/market/candles/${symbol}?timeframe=H1&count=120`, [symbol]);
  const { data: aiDecisions } = useFetch('/ai/decisions?limit=4');
  const live = useLiveQuotes();
  const [analysis, setAnalysis] = useState(null);
  const [tvTf, setTvTf] = useState('H1');

  useEffect(() => {
    get(`/technical/multitimeframe/${symbol}`).then(setAnalysis).catch(() => {});
  }, [symbol]);

  const merge = (sym) => live[sym] || (quotes || []).find((q) => q.symbol === sym);

  const runAnalysis = async () => {
    try {
      const d = await get(`/ai/analyze/${symbol}`);
      setAnalysis((p) => ({ ...p, latest: normalizeDecision(d) }));
    } catch (e) { /* surfaced by empty state */ }
  };

  const demoMode = !mt5?.connected;

  return (
    <div>
      {!mLoad && demoMode && (
        <div style={{ border: '1px solid var(--amber)', borderRadius: 10, padding: '10px 14px', marginBottom: 16, background: 'rgba(240,180,40,0.08)' }}>
          <b className="amber">MT5 Disconnected · Demo Mode</b>
          <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>
            No live MT5 bridge is connected (MT5_ENABLED={mt5?.mode || 'demo'}). Balance/equity shown are from the connected bridge only — no simulated account data is presented.
          </span>
        </div>
      )}

      <div className="page-head">
        <div className="section-title">Enterprise Command Center</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <span className="pill"><b className="blue">{symbol}</b></span>
          <button className="btn btn-primary" onClick={runAnalysis}>Run AI Analysis</button>
        </div>
      </div>

      <div className="grid grid-4">
        <StatCard label="Account Balance" value={pLoad ? '…' : fmtMoney(portfolio?.balance)} icon="◈" color="green" sub={portfolio?.demoMode ? 'Demo · no live balance' : portfolio?.source} />
        <StatCard label="Equity" value={pLoad ? '…' : fmtMoney(portfolio?.equity)} icon="▨" />
        <StatCard label="Daily P&L" value={pLoad ? '…' : fmtMoney(portfolio?.dailyPnL)} color={portfolio?.dailyPnL >= 0 ? 'green' : 'red'} />
        <StatCard label="Open Positions" value={pLoad ? '…' : portfolio?.openPositions} icon="⇄" sub={`Win rate ${portfolio?.winRate ?? 0}%`} />
      </div>

      <div style={{ height: 16 }} />

      <Panel
        title="TradingView — Live Pro Chart"
        sub="Real-time advanced charting · indicators · drawing tools · symbol syncs globally"
        style={{ padding: 12 }}
      >
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)} style={{ flex: 1, minWidth: 180 }}>
            {SYMBOL_LIST.map(([sym, name]) => <option key={sym} value={sym}>{sym} · {name}</option>)}
          </select>
          <select value={tvTf} onChange={(e) => setTvTf(e.target.value)} style={{ width: 90 }}>
            {TV_TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
          </select>
          <span className="muted" style={{ fontSize: 11, alignSelf: 'center' }}>
            <b className="green">●</b> Live data from TradingView
          </span>
        </div>
        <div style={{ border: '1px solid var(--bg3)', borderRadius: 8, overflow: 'hidden' }}>
          <TradingViewChart symbol={symbol} timeframe={tvTf} height={460} onSymbolChange={setSymbol} />
        </div>
      </Panel>

      <div style={{ height: 16 }} />

      <div className="grid grid-3">
        <Panel title="Market Overview" sub="Live tick feed · WebSocket" style={{ gridColumn: 'span 2' }}>
          {qLoad ? <Loading /> : (
            <table>
              <thead><tr><th>Symbol</th><th>Name</th><th>Bid</th><th>Ask</th><th>Spread</th><th>24h</th><th>Feed</th></tr></thead>
              <tbody>
                {(quotes || []).slice(0, 12).map((q) => {
                  const m = merge(q.symbol);
                  return (
                    <tr key={q.symbol}>
                      <td style={{ fontWeight: 700 }}>{q.symbol}</td>
                      <td className="muted">{q.name}</td>
                      <td>{fmt((m || q).bid, 4)}</td>
                      <td>{fmt((m || q).ask, 4)}</td>
                      <td className="muted">{fmt((m || q).spread, 4)}</td>
                      <td className={(m || q).change24h >= 0 ? 'green' : 'red'}>{fmtPct((m || q).change24h)}</td>
                      <td>
                        <span className="pill" style={{ fontSize: 10 }}>
                          <b className={(m || q).source === 'simulator' ? 'amber' : 'green'}>
                            {(m || q).source === 'simulator' ? 'SIM' : 'LIVE'}
                          </b>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel title="AI Decision Status" sub="Real 5-Agent Pipeline">
          {analysis?.latest ? (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <div>
                  <Badge type={analysis.latest.consensus.direction}>{analysis.latest.consensus.direction.toUpperCase()}</Badge>
                  <span style={{ marginLeft: 8, fontWeight: 700, fontSize: 16 }}>{analysis.latest.symbol}</span>
                </div>
                <div className="muted" style={{ fontSize: 11 }}>{new Date(analysis.latest.timestamp).toLocaleTimeString()}</div>
              </div>
              <MeterBlock label="Confidence" pct={analysis.latest.confidence.score * 100} color="var(--accent)" />
              <MeterBlock label="Agreement" pct={analysis.latest.consensus.agreement * 100} color="var(--purple)" />
              <div style={{ marginTop: 10 }}>
                {(analysis.latest.xai?.contributions || []).slice(0, 4).map((c) => (
                  <div key={c.agent} className="list-item" style={{ padding: '6px 0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: 11 }}>{c.agent}</span>
                      <Badge type={c.direction}>{c.direction}</Badge>
                    </div>
                    <div className="muted" style={{ fontSize: 10.5, marginTop: 2 }}>{c.reasoning}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div>
              <div className="empty">Click "Run AI Analysis" to get a live 5-agent decision</div>
              {(aiDecisions || []).map((d) => { const nd = normalizeDecision(d); return (
                <div key={nd.id} className="list-item">
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ fontWeight: 600 }}>{nd.symbol}</span>
                    <Badge type={nd.consensus.direction}>{nd.consensus.direction}</Badge>
                  </div>
                  <div className="muted" style={{ fontSize: 10.5 }}>
                    Confidence {nd.confidence.score} · {new Date(nd.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              ); })}
            </div>
          )}
        </Panel>
      </div>

      <div style={{ height: 16 }} />

      <div className="grid grid-3">
        <Panel title={`${symbol} H1 Price Action`} sub="Candlestick + EMA overlay">
          {candles ? <CandleChart candles={candles} height={240} /> : <Loading />}
          {analysis && (
            <div style={{ display: 'flex', gap: 16, marginTop: 10, flexWrap: 'wrap' }}>
              <span>Bias: <Badge type={analysis.bias}>{analysis.bias}</Badge></span>
              <span className="muted">Aligned TFs: {analysis.alignment?.alignedTimeframes?.length}/8</span>
              <span className="muted">Price: {fmt(analysis.summary?.price)}</span>
            </div>
          )}
        </Panel>

        <Panel title="Portfolio Summary" sub="Risk & capital protection">
          {pLoad ? <Loading /> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <MeterBlock label="Exposure" pct={portfolio?.equity ? (portfolio?.exposure / portfolio?.equity) * 100 : 0} color="var(--blue)" />
              <MeterBlock label="Margin Used" pct={portfolio?.equity ? (portfolio?.marginUsed / portfolio?.equity) * 100 : 0} color="var(--amber)" />
              <MeterBlock label="Daily Loss Limit" pct={portfolio?.capitalProtection?.dailyLossPct || 0} color="var(--red)" />
              <div className="kv" style={{ marginTop: 4 }}>
                <dt>Win Rate</dt><dd>{portfolio?.winRate}%</dd>
                <dt>Total Trades</dt><dd>{portfolio?.totalTrades}</dd>
                <dt>Margin Free</dt><dd>{fmtMoney(portfolio?.marginFree)}</dd>
                <dt>Protection</dt><dd className={portfolio?.capitalProtection?.haltTrading ? 'red' : 'green'}>{portfolio?.capitalProtection?.haltTrading ? 'HALTED' : 'Active'}</dd>
              </div>
            </div>
          )}
        </Panel>
      </div>

      <div style={{ height: 16 }} />

      <div className="grid grid-2">
        <Panel title="News Overview" sub="Top market-moving headlines">
          {nLoad ? <Loading /> : (news || []).slice(0, 5).map((n) => (
            <div key={n.id} className="list-item">
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontWeight: 500 }}>{n.title}</span>
                <Badge type={n.sentiment > 0 ? 'buy' : n.sentiment < 0 ? 'sell' : 'neutral'}>{(n.sentiment ?? 0).toFixed(2)}</Badge>
              </div>
              <div className="muted" style={{ fontSize: 10.5 }}>
                {n.source} · Trust {n.trustScore} · Impact {n.marketImpact} · {new Date(n.time).toLocaleTimeString()}
              </div>
            </div>
          ))}
        </Panel>
        <Panel title="Economic Calendar Overview" sub="Upcoming high-impact events">
          {eLoad ? <Loading /> : (events || []).filter((e) => e.status !== 'released').slice(0, 5).map((e) => (
            <div key={e.id} className="list-item">
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontWeight: 500 }}>{e.name}</span>
                <Badge type={e.impact === 3 ? 'high' : e.impact === 2 ? 'warning' : 'info'}>{'●'.repeat(e.impact)}{'○'.repeat(3 - e.impact)}</Badge>
              </div>
              <div className="muted" style={{ fontSize: 10.5 }}>
                {e.currency} · {new Date(e.time).toLocaleString()} · AI: {e.ai?.direction || 'pending'}
              </div>
            </div>
          ))}
        </Panel>
      </div>

      <div style={{ height: 16 }} />

      <div className="grid grid-4">
        <StatCard label="MT5 Connection" value={mLoad ? '…' : mt5?.connected ? 'Connected' : 'Disconnected'} color={mt5?.connected ? 'green' : 'red'} sub={`Mode: ${mt5?.mode || 'demo'}${mt5?.connected ? ` · Latency ${mt5?.latency || 0}ms` : ''}`} />
        <StatCard label="News Items Tracked" value={nLoad ? '…' : (news?.length || 0) + ' recent'} icon="▣" sub="FinBERT + FinLLM sentiment" />
        <StatCard label="System Health" value={hLoad ? '…' : health?.status || '…'} color="green" sub={`${health?.checks?.length || 0} checks`} />
        <StatCard label="AI Decisions" value={aiDecisions?.length || 0} icon="✦" sub="Recent consensus decisions" />
      </div>
    </div>
  );
}

function MeterBlock({ label, pct, color }) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 3 }}>
        <span className="muted">{label}</span>
        <span>{Math.round(pct)}%</span>
      </div>
      <Bar pct={pct} color={color} />
    </div>
  );
}
