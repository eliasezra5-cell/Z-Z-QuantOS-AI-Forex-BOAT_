import { useState } from 'react';
import { useFetch, useLiveQuotes, fmt, fmtPct } from '../api.js';
import { Panel, Badge, Loading, ErrorMsg } from '../components/ui.jsx';
import CandleChart from '../components/CandleChart.jsx';
import { useSymbol } from '../symbols.jsx';

const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1'];

export default function MarketData() {
  const { symbol, setSymbol } = useSymbol();
  const [tf, setTf] = useState('H1');
  const { data: instruments, loading: iLoad } = useFetch('/market/instruments');
  const { data: quotes, loading: qLoad } = useFetch('/market/quotes');
  const { data: candles, loading: cLoad } = useFetch(`/market/candles/${symbol}?timeframe=${tf}&count=150`, [symbol, tf]);
  const { data: orderbook } = useFetch(`/market/orderbook/${symbol}?depth=8`, [symbol]);
  const { data: trades } = useFetch(`/market/trades/${symbol}?count=25`, [symbol]);
  const { data: sessions } = useFetch('/market/sessions');
  const live = useLiveQuotes();

  const q = live[symbol] || (quotes || []).find((x) => x.symbol === symbol);

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Market Data Engine</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {(instruments || []).map((i) => <option key={i.symbol} value={i.symbol}>{i.symbol}</option>)}
          </select>
          <select value={tf} onChange={(e) => setTf(e.target.value)}>
            {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          {q && <span className={`pill ${q.change24h >= 0 ? 'green' : 'red'}`}>{fmtPct(q.change24h)} 24h</span>}
        </div>
      </div>

      <div className="grid grid-4">
        <Stat label="Bid" value={q ? fmt(q.bid) : '…'} color="green" />
        <Stat label="Ask" value={q ? fmt(q.ask) : '…'} color="red" />
        <Stat label="Spread" value={q ? fmt(q.spread) : '…'} />
        <Stat label="Volume (24h)" value={q ? q.volume.toLocaleString() : '…'} />
      </div>

      <div style={{ height: 16 }} />

      <div className="grid grid-3">
        <Panel title={`${symbol} · ${tf} Chart`} sub="Live OHLC candles" style={{ gridColumn: 'span 2' }}>
          {cLoad ? <Loading /> : <CandleChart candles={candles} height={300} />}
        </Panel>
        <Panel title="Order Book" sub={`Depth ${orderbook?.bids?.length || 0} levels`}>
          <table>
            <thead><tr><th>Bids</th><th></th><th>Asks</th></tr></thead>
            <tbody>
              {[...Array(Math.max(orderbook?.bids?.length || 0, orderbook?.asks?.length || 0))].map((_, i) => (
                <tr key={i}>
                  <td className="green">{orderbook?.bids?.[i] ? fmt(orderbook.bids[i].price, 4) : ''}</td>
                  <td className="muted">{orderbook?.bids?.[i]?.size || ''}</td>
                  <td className="red">{orderbook?.asks?.[i] ? fmt(orderbook.asks[i].price, 4) : ''}</td>
                  <td className="muted">{orderbook?.asks?.[i]?.size || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      <div style={{ height: 16 }} />

      <div className="grid grid-2">
        <Panel title="Recent Trades" sub="Live trade tape">
          <table>
            <thead><tr><th>Time</th><th>Side</th><th>Price</th><th>Size</th></tr></thead>
            <tbody>
              {(trades || []).map((t) => (
                <tr key={t.id}>
                  <td className="muted">{new Date(t.time).toLocaleTimeString()}</td>
                  <td><Badge type={t.side === 'buy' ? 'buy' : 'sell'}>{t.side}</Badge></td>
                  <td>{fmt(t.price)}</td>
                  <td>{t.size}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Market Sessions" sub="Global trading sessions">
          {(sessions?.sessions || []).map((s) => (
            <div key={s.name} className="list-item">
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontWeight: 600 }}>{s.name}</span>
                <Badge type={s.active ? 'buy' : 'neutral'}>{s.active ? 'ACTIVE' : 'closed'}</Badge>
              </div>
              <div className="muted" style={{ fontSize: 10.5 }}>{s.open}:00 – {s.close}:00 UTC</div>
            </div>
          ))}
          <div className="muted" style={{ marginTop: 8, fontSize: 11 }}>
            UTC Time: {sessions?.utcTime}h · Active: {sessions?.activeSessions?.join(', ')}
          </div>
        </Panel>
      </div>

      <div style={{ height: 16 }} />
      <Panel title="Instrument Directory" sub="All supported market providers & instruments">
        {iLoad ? <Loading /> : (
          <table>
            <thead><tr><th>Symbol</th><th>Name</th><th>Asset Class</th><th>Bid</th><th>Ask</th><th>Digits</th></tr></thead>
            <tbody>
              {(instruments || []).map((i) => (
                <tr key={i.symbol} onClick={() => setSymbol(i.symbol)} style={{ cursor: 'pointer' }}>
                  <td style={{ fontWeight: 700 }}>{i.symbol}</td>
                  <td>{i.name}</td>
                  <td><Badge type="info">{i.type}</Badge></td>
                  <td className="green">{fmt(live[i.symbol]?.bid ?? i.base, i.digits)}</td>
                  <td className="red">{fmt(live[i.symbol]?.ask ?? i.base, i.digits)}</td>
                  <td className="muted">{i.digits}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}

function Stat({ label, value, color = '' }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${color}`}>{value}</div>
    </div>
  );
}
