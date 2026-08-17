import { useFetch } from '../api.js';
import { Panel, Badge, Loading, StatCard, Meter, Sparkline } from '../components/ui.jsx';

export default function Portfolio() {
  const { data: portfolio, loading } = useFetch('/portfolio/overview');
  const { data: curve } = useFetch('/portfolio/equity-curve');
  const { data: daily } = useFetch('/portfolio/daily?days=14');
  const { data: risk } = useFetch('/risk/settings');

  return (
    <div>
      <div className="page-head"><div className="section-title">Portfolio Management & Performance</div></div>
      {loading ? <Loading /> : (
        <>
          <div className="grid grid-4">
            <StatCard label="Balance" value={`$${portfolio.balance?.toLocaleString()}`} color="green" />
            <StatCard label="Equity" value={`$${portfolio.equity?.toLocaleString()}`} color="blue" />
            <StatCard label="Unrealized P&L" value={`$${portfolio.unrealizedPnL}`} color={portfolio.unrealizedPnL >= 0 ? 'green' : 'red'} />
            <StatCard label="Daily P&L" value={`$${portfolio.dailyPnL}`} color={portfolio.dailyPnL >= 0 ? 'green' : 'red'} sub={`Loss: $${portfolio.dailyLoss}`} />
          </div>

          <div style={{ height: 16 }} />
          <div className="grid grid-3">
            <Panel title="Equity Curve" sub="Performance over time" style={{ gridColumn: 'span 2' }}>
              <Sparkline data={(curve || []).map((c) => c.value)} color="var(--accent)" height={160} />
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
                <span className="muted">Peak: ${Math.max(...(curve || []).map((c) => c.value), 0)?.toLocaleString()}</span>
                <span className="muted">Latest: ${curve?.slice(-1)[0]?.value?.toLocaleString()}</span>
              </div>
            </Panel>

            <Panel title="Exposure & Margin">
              <Meter label="Exposure" value={`${Math.round((portfolio.exposure / portfolio.equity) * 100)}%`} pct={(portfolio.exposure / portfolio.equity) * 100} color="var(--blue)" />
              <Meter label="Margin Used" value={`${Math.round((portfolio.marginUsed / portfolio.equity) * 100)}%`} pct={(portfolio.marginUsed / portfolio.equity) * 100} color="var(--amber)" />
              <Meter label="Daily Loss Used" value={`${Math.round(portfolio.capitalProtection?.dailyLossPct || 0)}%`} pct={portfolio.capitalProtection?.dailyLossPct || 0} color="var(--red)" />
              <div className="kv" style={{ marginTop: 8 }}>
                <dt>Margin Free</dt><dd>${portfolio.marginFree?.toLocaleString()}</dd>
                <dt>Open Positions</dt><dd>{portfolio.openPositions}</dd>
                <dt>Total Trades</dt><dd>{portfolio.totalTrades}</dd>
                <dt>Win Rate</dt><dd className="green">{portfolio.winRate}%</dd>
              </div>
            </Panel>
          </div>

          <div style={{ height: 16 }} />
          <div className="grid grid-2">
            <Panel title="Risk Engine Settings" sub="Capital protection rules">
              {(risk || []).map((r) => (
                <div key={r.id} className="list-item" style={{ padding: '6px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <span style={{ fontWeight: 600, fontSize: 12 }}>{r.description}</span>
                    <div className="muted" style={{ fontSize: 10 }}>{r.id}</div>
                  </div>
                  <Badge type={r.enabled ? 'buy' : 'neutral'}>{r.enabled ? r.value : 'OFF'}</Badge>
                </div>
              ))}
            </Panel>

            <Panel title="Capital Protection Status" sub="Automatic risk halting">
              <div style={{ textAlign: 'center', padding: 20 }}>
                <div className={`stat-value ${portfolio.capitalProtection?.haltTrading ? 'red' : 'green'}`} style={{ fontSize: 28 }}>
                  {portfolio.capitalProtection?.haltTrading ? 'TRADING HALTED' : 'PROTECTED'}
                </div>
                <div className="muted" style={{ marginTop: 8 }}>
                  Daily loss limit: {portfolio.capitalProtection?.dailyLossLimit}%
                </div>
                <div className="muted" style={{ fontSize: 11 }}>
                  Current: {portfolio.capitalProtection?.dailyLossPct?.toFixed(2)}%
                </div>
                {portfolio.capitalProtection?.reason && <div className="red" style={{ marginTop: 8 }}>{portfolio.capitalProtection.reason}</div>}
              </div>
            </Panel>
          </div>

          <div style={{ height: 16 }} />
          <Panel title="Daily Performance" sub="P&L by day">
            <table>
              <thead><tr><th>Date</th><th>P&L</th><th>Trades</th><th>Win Rate</th><th>Trend</th></tr></thead>
              <tbody>
                {(daily || []).slice(-14).map((d) => (
                  <tr key={d.date}>
                    <td>{d.date}</td>
                    <td className={d.pnl >= 0 ? 'green' : 'red'} style={{ fontWeight: 700 }}>${d.pnl}</td>
                    <td>{d.trades}</td>
                    <td>{d.winRate}%</td>
                    <td><Sparkline data={[0, d.pnl]} color={d.pnl >= 0 ? 'var(--green)' : 'var(--red)'} height={20} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}
    </div>
  );
}
