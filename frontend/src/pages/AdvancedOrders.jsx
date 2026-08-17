import { useEffect, useState } from 'react';
import { get, post } from '../api.js';
import { Panel, Badge, Loading } from '../components/ui.jsx';

const ALL_SYMBOLS = ['XAUUSD', 'XAGUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'BTCUSD', 'ETHUSD', 'US500', 'NAS100', 'US30', 'WTI', 'AAPL', 'TSLA'];
const ORDER_TYPES = ['market', 'limit', 'stop-market', 'stop-limit', 'bracket', 'oco'];
const TIF_VALUES = ['GTC', 'IOC', 'FOK', 'DAY'];

function CheckRow({ check }) {
  if (!check || typeof check !== 'object') return null;
  const badge = check.passed ? 'ok' : check.level === 'fail' ? 'critical' : 'warn';
  return (
    <tr>
      <td><b>{check.name}</b></td>
      <td><Badge type={badge}>{check.passed ? 'PASS' : check.level === 'fail' ? 'FAIL' : 'WARN'}</Badge></td>
      <td style={{ fontSize: 11, color: 'var(--text-2)' }}>{check.message}</td>
    </tr>
  );
}

function CheckResult({ result }) {
  if (!result || typeof result !== 'object') return null;
  if (result.status === 'error') return <div className="empty">{result.error || 'Check failed'}</div>;
  const checks = Array.isArray(result.checks) ? result.checks : [];
  const approved = result.status === 'approved';
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <Badge type={approved ? 'ok' : 'critical'}>{approved ? 'APPROVED' : 'REJECTED'}</Badge>
        <span className="muted" style={{ fontSize: 11 }}>{checks.length} checks</span>
      </div>
      <table className="table">
        <thead>
          <tr><th>Check</th><th>Status</th><th>Detail</th></tr>
        </thead>
        <tbody>
          {checks.map((c) => <CheckRow key={c.id} check={c} />)}
        </tbody>
      </table>
      {result.violations && result.violations.length ? (
        <div className="empty" style={{ marginTop: 8 }}>
          <b>Violations:</b> {result.violations.join('; ')}
        </div>
      ) : null}
      {result.warnings && result.warnings.length ? (
        <div className="muted" style={{ marginTop: 6, fontSize: 11 }}>Warnings: {result.warnings.join('; ')}</div>
      ) : null}
    </div>
  );
}

function PlaceResult({ result }) {
  if (!result || typeof result !== 'object') return null;
  if (result.status === 'error') return <div className="empty">{result.error || 'Placement failed'}</div>;
  if (result.status === 'rejected') {
    return <div className="empty"><b>Order rejected:</b> {result.reason || 'pre-trade checks failed'}</div>;
  }
  const placed = Array.isArray(result.placed) ? result.placed : [];
  return (
    <div style={{ marginTop: 12 }}>
      <Badge type="ok">PLACED {placed.length > 1 ? `(${placed.length} legs)` : ''}</Badge>
      {result.ocoId ? <span className="muted" style={{ marginLeft: 8, fontSize: 11 }}>OCO id {result.ocoId}</span> : null}
      <table className="table" style={{ marginTop: 8 }}>
        <thead>
          <tr><th>Leg</th><th>Symbol</th><th>Side</th><th>Type</th><th>Volume</th><th>Result</th></tr>
        </thead>
        <tbody>
          {placed.map((p, i) => (
            <tr key={i}>
              <td>{p.kind}</td>
              <td><b>{p.order.symbol}</b></td>
              <td>{p.order.side}</td>
              <td>{p.order.type}</td>
              <td>{p.order.volume}</td>
              <td style={{ fontSize: 11 }}>{(p.result && (p.result.status || p.result.ticket)) || 'sent'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function AdvancedOrders() {
  const [capabilities, setCapabilities] = useState({});
  const [symbol, setSymbol] = useState('XAUUSD');
  const [side, setSide] = useState('buy');
  const [type, setType] = useState('market');
  const [volume, setVolume] = useState('0.10');
  const [price, setPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [takeProfit, setTakeProfit] = useState('');
  const [timeInForce, setTimeInForce] = useState('GTC');
  const [checkResult, setCheckResult] = useState({});
  const [placeResult, setPlaceResult] = useState({});
  const [checking, setChecking] = useState(false);
  const [placing, setPlacing] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    get('/pro/advanced-orders/capabilities')
      .then((res) => {
        if (alive) setCapabilities(res && typeof res === 'object' ? res : {});
      })
      .catch(() => {
        if (alive) setCapabilities({});
      });
    return () => { alive = false; };
  }, []);

  const buildPayload = () => {
    const payload = {
      symbol,
      side,
      type,
      volume: Number(volume) || 0.1,
      timeInForce,
      comment: 'advanced-order',
    };
    if (price !== '') payload.price = Number(price);
    if (stopLoss !== '') payload.stopLoss = Number(stopLoss);
    if (takeProfit !== '') payload.takeProfit = Number(takeProfit);
    return payload;
  };

  const runCheck = async () => {
    setChecking(true);
    setError('');
    try {
      const res = await post('/pro/advanced-orders/check', buildPayload());
      setCheckResult(res && typeof res === 'object' ? res : {});
    } catch (e) {
      setError(e.message);
      setCheckResult({});
    } finally {
      setChecking(false);
    }
  };

  const placeOrder = async () => {
    setPlacing(true);
    setError('');
    try {
      const res = await post('/pro/advanced-orders/place', buildPayload());
      setPlaceResult(res && typeof res === 'object' ? res : {});
    } catch (e) {
      setError(e.message);
      setPlaceResult({});
    } finally {
      setPlacing(false);
    }
  };

  const types = Array.isArray(capabilities.orderTypes) ? capabilities.orderTypes : ORDER_TYPES;
  const tifs = Array.isArray(capabilities.timeInForce) ? capabilities.timeInForce : TIF_VALUES;

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Advanced Orders</div>
        <span className="muted" style={{ fontSize: 11 }}>
          Order types + pre-trade checklist · <Badge type="info">PRO</Badge>
        </span>
      </div>

      <Panel title="Order" icon="⇄" sub="market · limit · stop-market · stop-limit · bracket (SL+TP) · OCO + time-in-force">
        <div className="grid grid-2">
          <div>
            <div className="muted" style={{ fontSize: 10.5, marginBottom: 6 }}>Symbol</div>
            <select className="select" value={symbol} onChange={(e) => setSymbol(e.target.value)} style={{ width: '100%', fontSize: 11, padding: '4px 8px' }}>
              {ALL_SYMBOLS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 10.5, marginBottom: 6 }}>Side</div>
            <select className="select" value={side} onChange={(e) => setSide(e.target.value)} style={{ width: '100%', fontSize: 11, padding: '4px 8px' }}>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 10.5, marginBottom: 6 }}>Type</div>
            <select className="select" value={type} onChange={(e) => setType(e.target.value)} style={{ width: '100%', fontSize: 11, padding: '4px 8px' }}>
              {types.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 10.5, marginBottom: 6 }}>Time in force</div>
            <select className="select" value={timeInForce} onChange={(e) => setTimeInForce(e.target.value)} style={{ width: '100%', fontSize: 11, padding: '4px 8px' }}>
              {tifs.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 10.5, marginBottom: 6 }}>Volume (lots)</div>
            <input className="input" value={volume} onChange={(e) => setVolume(e.target.value)} style={{ width: '100%', fontSize: 11, padding: '4px 8px' }} />
          </div>
          <div>
            <div className="muted" style={{ fontSize: 10.5, marginBottom: 6 }}>Price (limit/stop)</div>
            <input className="input" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="optional" style={{ width: '100%', fontSize: 11, padding: '4px 8px' }} />
          </div>
          <div>
            <div className="muted" style={{ fontSize: 10.5, marginBottom: 6 }}>Stop loss</div>
            <input className="input" value={stopLoss} onChange={(e) => setStopLoss(e.target.value)} placeholder="optional" style={{ width: '100%', fontSize: 11, padding: '4px 8px' }} />
          </div>
          <div>
            <div className="muted" style={{ fontSize: 10.5, marginBottom: 6 }}>Take profit</div>
            <input className="input" value={takeProfit} onChange={(e) => setTakeProfit(e.target.value)} placeholder="optional" style={{ width: '100%', fontSize: 11, padding: '4px 8px' }} />
          </div>
        </div>

        {error ? <div className="empty" style={{ marginTop: 10 }}>{error}</div> : null}

        <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
          <button className="btn" onClick={runCheck} disabled={checking}>
            {checking ? 'Checking…' : 'Dry-run Checks'}
          </button>
          <button className="btn btn-primary" onClick={placeOrder} disabled={placing}>
            {placing ? 'Placing…' : 'Place Order'}
          </button>
        </div>

        {checking ? <Loading /> : null}
        <CheckResult result={checkResult} />
        <PlaceResult result={placeResult} />
      </Panel>
    </div>
  );
}
