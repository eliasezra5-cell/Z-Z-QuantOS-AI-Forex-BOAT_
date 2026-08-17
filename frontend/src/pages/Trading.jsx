import { useState, useEffect } from 'react';
import { useFetch, useLiveQuotes, get, post, fmt } from '../api.js';
import { Panel, Badge, Loading, StatCard } from '../components/ui.jsx';
import { useSymbol } from '../symbols.jsx';

export default function Trading() {
  const { symbol, setSymbol } = useSymbol();
  const { data: positions, refresh: refreshPos } = useFetch('/trading/positions');
  const { data: orders } = useFetch('/trading/orders?limit=15');
  const { data: mt5, refresh: refreshMt5 } = useFetch('/mt5/status');
  const { data: mt5Symbols } = useFetch('/mt5/symbols');
  const { data: history } = useFetch('/mt5/history');
  const { data: execModes, refresh: refreshExecModes } = useFetch('/execution/modes');
  const live = useLiveQuotes();
  const [form, setForm] = useState({ side: 'buy', volume: 0.1, stopLoss: '', takeProfit: '' });
  const [mt5Form, setMt5Form] = useState({ login: '', password: '', server: '', bridgeUrl: 'http://host.docker.internal:5001' });
  const [mt5Busy, setMt5Busy] = useState(false);
  const [mt5Result, setMt5Result] = useState(null);
  const [result, setResult] = useState(null);

  useEffect(() => {
    get('/integrations/mt5/connection')
      .then((res) => {
        const c = res.connection;
        if (c) {
          setMt5Form((prev) => ({
            ...prev,
            login: c.login || prev.login,
            server: c.server || prev.server,
            bridgeUrl: c.bridgeUrl || prev.bridgeUrl
          }));
        }
      })
      .catch(() => { /* saved connection prefetch is best-effort */ });
  }, []);

  const connectMt5 = async () => {
    setMt5Busy(true);
    setMt5Result(null);
    try {
      const res = await post('/integrations/mt5/connect', {
        login: mt5Form.login,
        password: mt5Form.password,
        server: mt5Form.server,
        bridgeUrl: mt5Form.bridgeUrl
      });
      setMt5Result(res.status);
      refreshMt5();
      refreshPos();
    } catch (err) {
      setMt5Result({ connected: false, detail: err.message });
    } finally {
      setMt5Busy(false);
    }
  };

  const activeMode = execModes?.mode || 'DISABLED';
  const sym = form.symbol || symbol;
  const symbolMeta = (mt5Symbols || []).find((s) => s.symbol === sym);
  const liveTick = live[sym];

  const placeOrder = async () => {
    const sl = parseFloat(form.stopLoss);
    const tp = parseFloat(form.takeProfit);
    if (!sl) { setResult({ status: 'rejected', violations: ['Stop loss is mandatory'] }); return; }
    if (!tp) { setResult({ status: 'rejected', violations: ['Take profit is mandatory'] }); return; }
    const res = await post('/trading/orders', {
      symbol: sym,
      side: form.side,
      volume: parseFloat(form.volume) || 0.1,
      stopLoss: sl,
      takeProfit: tp,
      comment: 'web-terminal',
      source: 'web-terminal'
    });
    setResult(res);
    refreshPos();
  };

  const closePos = async (id) => {
    await post(`/trading/positions/${id}/close`, { reason: 'manual' });
    refreshPos();
  };

  const toggleMode = async (m) => {
    await post('/execution/modes', {
      mode: m,
      actor: 'admin',
      reason: `Mode selected from Trading Engine UI (${new Date().toISOString()})`
    });
    refreshExecModes();
  };

  const isActiveMode = (m) => activeMode === m;

  const demoMode = !mt5?.connected;

  return (
    <div>
      {!mt5 && <Loading />}
      {demoMode && (
        <div style={{ border: '1px solid var(--amber)', borderRadius: 10, padding: '10px 14px', marginBottom: 16, background: 'rgba(240,180,40,0.08)' }}>
          <b className="amber">MT5 Disconnected · Demo Mode</b>
          <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>
            No live MT5 bridge connected. Account/balance are NOT available and orders run through the paper-trading engine only.
          </span>
        </div>
      )}

      <div className="page-head">
        <div className="section-title">Trading Engine & MT5 Integration</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className="pill">Mode: <b className={activeMode === 'AUTO_FULL' || activeMode === 'SEMI_AUTO' ? 'green' : activeMode === 'EMERGENCY_STOP' ? 'red' : 'amber'}>{activeMode}</b></span>
          <button className={`btn btn-sm ${isActiveMode('ANALYSIS_ONLY') || isActiveMode('DISABLED') ? 'btn-primary' : ''}`} onClick={() => toggleMode('ANALYSIS_ONLY')}>Manual</button>
          <button className={`btn btn-sm ${isActiveMode('SEMI_AUTO') ? 'btn-primary' : ''}`} onClick={() => toggleMode('SEMI_AUTO')}>Semi-Auto</button>
          <button className={`btn btn-sm ${isActiveMode('AUTO_FULL') ? 'btn-primary' : ''}`} onClick={() => toggleMode('AUTO_FULL')}>Auto</button>
        </div>
      </div>

      <div className="grid grid-4">
        <StatCard label="MT5 Status" value={mt5?.connected ? 'Connected' : 'Disconnected'} color={mt5?.connected ? 'green' : 'red'} sub={`Mode: ${mt5?.mode || 'demo'}${mt5?.connected ? ` · Latency ${mt5?.latency || 0}ms` : ''}`} />
        <StatCard label="Account" value={mt5?.account?.login || '—'} sub={mt5?.account?.broker || 'no bridge'} />
        <StatCard label="Balance" value={mt5?.account ? `$${Number(mt5.account.balance || 0).toLocaleString()}` : '—'} color="green" sub={mt5?.account ? undefined : 'unavailable (disconnected)'} />
        <StatCard label="Equity" value={mt5?.account ? `$${Number(mt5.account.equity || 0).toLocaleString()}` : '—'} color="blue" />
      </div>

      <div style={{ height: 16 }} />
      <div className="grid grid-3">
        <Panel title="MT5 Connection" sub="Connect your real account from the dashboard">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <label className="muted" style={{ fontSize: 11 }}>MT5 Login (number)</label>
              <input
                type="number"
                value={mt5Form.login}
                placeholder="123456789"
                onChange={(e) => setMt5Form({ ...mt5Form, login: e.target.value })}
                style={{ width: '100%' }}
              />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 11 }}>MT5 Password</label>
              <input
                type="password"
                value={mt5Form.password}
                placeholder="••••••••"
                onChange={(e) => setMt5Form({ ...mt5Form, password: e.target.value })}
                style={{ width: '100%' }}
              />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 11 }}>MT5 Server</label>
              <input
                type="text"
                value={mt5Form.server}
                placeholder="ICMarkets-Demo"
                onChange={(e) => setMt5Form({ ...mt5Form, server: e.target.value })}
                style={{ width: '100%' }}
              />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 11 }}>MT5 Bridge URL</label>
              <input
                type="text"
                value={mt5Form.bridgeUrl}
                placeholder="http://host.docker.internal:5001"
                onChange={(e) => setMt5Form({ ...mt5Form, bridgeUrl: e.target.value })}
                style={{ width: '100%' }}
              />
            </div>
            <button className="btn btn-primary" onClick={connectMt5} disabled={mt5Busy}>
              {mt5Busy ? 'Connecting…' : 'Connect to MT5'}
            </button>
            {mt5Result && (
              <div className={`list-item ${mt5Result.connected ? 'green' : 'red'}`} style={{ padding: 8, borderRadius: 8, fontSize: 12 }}>
                <b>{mt5Result.connected ? 'CONNECTED' : 'NOT CONNECTED'}</b>
                {mt5Result.detail ? ` — ${mt5Result.detail}` : ''}
              </div>
            )}
            <div className="kv" style={{ marginBottom: 8 }}>
              <dt>Mode</dt><dd><Badge type={mt5?.mode === 'live' ? 'buy' : 'neutral'}>{mt5?.mode || 'demo'}</Badge></dd>
              <dt>Bridge</dt><dd className="muted">{mt5?.bridge ? <a className="green" href={mt5.bridge} target="_blank" rel="noreferrer">{mt5.bridge}</a> : '—'}</dd>
              <dt>Connected</dt><dd className={mt5?.connected ? 'green' : 'red'}>{mt5?.connected ? 'Yes' : 'No'}</dd>
              <dt>Broker</dt><dd className="muted">{mt5?.account?.broker || mt5?.account?.server || '—'}</dd>
            </div>
          </div>
          <div className="muted" style={{ fontSize: 11, lineHeight: 1.6 }}>
            {mt5?.mode === 'live'
              ? 'Live bridge active. Orders below are sent to your MT5 terminal. See docs/MT5_CONNECTION.md.'
              : (
                <>
                  <b>To connect a real MT5 account:</b>
                  <ol style={{ margin: '6px 0 0 16px', padding: 0 }}>
                    <li>Enter your MT5 login / password / server above.</li>
                    <li>Run <code>bridge/mt5_bridge.py</code> on a Windows PC/VPS with your MT5 terminal logged in.</li>
                    <li>Point the Bridge URL at that machine (default <code>http://host.docker.internal:5001</code>), then hit <b>Connect to MT5</b>.</li>
                    <li>This panel will show <span className="green">Connected</span> and the real account/balance.</li>
                  </ol>
                  Full guide: <code>docs/MT5_CONNECTION.md</code>
                </>
              )}
          </div>
        </Panel>

        <Panel title="New Order" sub="Market execution terminal">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <label className="muted" style={{ fontSize: 11 }}>Symbol</label>
              <select value={sym} onChange={(e) => { setSymbol(e.target.value); setForm({ ...form, symbol: e.target.value }); }} style={{ width: '100%' }}>
                {(mt5Symbols || []).map((s) => <option key={s.symbol} value={s.symbol}>{s.symbol} · {fmt(live[s.symbol]?.bid ?? s.bid)}/{fmt(live[s.symbol]?.ask ?? s.ask)}</option>)}
              </select>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <span className="pill" style={{ flex: 1, textAlign: 'center', fontSize: 12 }}>
                Bid <b className="green">{fmt(liveTick?.bid ?? symbolMeta?.bid)}</b> · Ask <b className="blue">{fmt(liveTick?.ask ?? symbolMeta?.ask)}</b>
              </span>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className={`btn ${form.side === 'buy' ? 'btn-primary' : ''}`} style={{ flex: 1 }} onClick={() => setForm({ ...form, side: 'buy' })}>BUY</button>
              <button className={`btn ${form.side === 'sell' ? 'btn-danger' : 'btn-danger'}`} style={{ flex: 1 }} onClick={() => setForm({ ...form, side: 'sell' })}>SELL</button>
            </div>
            <div>
              <label className="muted" style={{ fontSize: 11 }}>Volume (lots)</label>
              <input type="number" step="0.01" value={form.volume} onChange={(e) => setForm({ ...form, volume: e.target.value })} style={{ width: '100%' }} />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input placeholder="Stop Loss * (required)" value={form.stopLoss} onChange={(e) => setForm({ ...form, stopLoss: e.target.value })} style={{ flex: 1 }} />
              <input placeholder="Take Profit * (required)" value={form.takeProfit} onChange={(e) => setForm({ ...form, takeProfit: e.target.value })} style={{ flex: 1 }} />
            </div>
            <button className="btn btn-primary" onClick={placeOrder}>Place Order</button>
            {result && (
              <div className={`list-item ${result.status === 'rejected' ? 'red' : 'green'}`} style={{ padding: 8, borderRadius: 8 }}>
                <b>{result.status.toUpperCase()}</b> {result.violations ? `: ${result.violations.join(', ')}` : ` — ${form.side} ${form.volume} ${sym}`}
              </div>
            )}
          </div>
        </Panel>

        <Panel title="Open Positions" sub="Live P&L monitor" style={{ gridColumn: 'span 2' }}>
          {positions?.length ? (
            <table>
              <thead><tr><th>Symbol</th><th>Side</th><th>Volume</th><th>Entry</th><th>SL</th><th>TP</th><th>Profit</th><th>Source</th><th></th></tr></thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id}>
                    <td style={{ fontWeight: 700 }}>{p.symbol}</td>
                    <td><Badge type={p.side}>{p.side}</Badge></td>
                    <td>{p.volume}</td>
                    <td>{p.entryPrice}</td>
                    <td className="red">{p.stopLoss ?? '—'}</td>
                    <td className="green">{p.takeProfit ?? '—'}</td>
                    <td className={p.profit >= 0 ? 'green' : 'red'} style={{ fontWeight: 700 }}>${p.profit}</td>
                    <td className="muted">{p.source}</td>
                    <td><button className="btn btn-sm btn-danger" onClick={() => closePos(p.id)}>Close</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="empty">No open positions</div>}
        </Panel>
      </div>

      <div style={{ height: 16 }} />
      <div className="grid grid-2">
        <Panel title="Recent Orders" sub="Order execution log">
          <table>
            <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Volume</th><th>Price</th><th>Status</th><th>Reason</th></tr></thead>
            <tbody>
              {(orders || []).slice(0, 10).map((o) => (
                <tr key={o.id}>
                  <td className="muted">{new Date(o.timestamp).toLocaleTimeString()}</td>
                  <td style={{ fontWeight: 600 }}>{o.symbol}</td>
                  <td><Badge type={o.side}>{o.side}</Badge></td>
                  <td>{o.volume}</td>
                  <td>{o.price}</td>
                  <td><Badge type={o.status === 'filled' ? 'buy' : o.status === 'rejected' ? 'sell' : 'neutral'}>{o.status}</Badge></td>
                  <td>
                    {o.status === 'rejected'
                      ? <span className="muted" style={{ fontSize: 11 }} title={o.rejectReason}>{o.rejectReason || '—'}</span>
                      : <span className="muted" style={{ fontSize: 11 }}>—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Trade History" sub="Closed positions (MT5)">
          <table>
            <thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>Profit</th><th>Reason</th></tr></thead>
            <tbody>
              {(history || []).slice(0, 10).map((h) => (
                <tr key={h.id}>
                  <td style={{ fontWeight: 600 }}>{h.symbol}</td>
                  <td><Badge type={h.side}>{h.side}</Badge></td>
                  <td>{h.entryPrice}</td>
                  <td>{h.exitPrice}</td>
                  <td className={h.profit >= 0 ? 'green' : 'red'} style={{ fontWeight: 700 }}>${h.profit}</td>
                  <td className="muted">{h.closeReason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </div>
  );
}
