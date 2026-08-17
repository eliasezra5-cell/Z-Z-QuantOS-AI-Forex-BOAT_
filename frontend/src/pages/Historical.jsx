import { useFetch } from '../api.js';
import { Panel, Badge, Loading, StatCard, Sparkline } from '../components/ui.jsx';
import { useSymbol } from '../symbols.jsx';

export default function Historical() {
  const { symbol } = useSymbol();
  const { data: hist, loading } = useFetch('/historical/overview');
  const { data: replay } = useFetch(`/historical/replay?symbol=${symbol}&timeframe=H1&count=200`, [symbol]);
  const { data: patterns } = useFetch(`/historical/patterns?symbol=${symbol}`, [symbol]);

  return (
    <div>
      <div className="page-head"><div className="section-title">Historical Intelligence</div></div>
      {loading ? <Loading /> : (
        <>
          <div className="grid grid-4">
            <StatCard label="Total Trades" value={hist?.stats?.total} icon="⇄" />
            <StatCard label="Win Rate" value={`${hist?.stats?.winRate}%`} color="green" />
            <StatCard label="Total Profit" value={`$${hist?.stats?.totalProfit}`} color={hist?.stats?.totalProfit >= 0 ? 'green' : 'red'} />
            <StatCard label="Best Trade" value={hist?.stats?.bestTrade ? `$${hist?.stats?.bestTrade.profit}` : '—'} color="green" sub={hist?.stats?.bestTrade?.symbol} />
          </div>

          <div style={{ height: 16 }} />
          <div className="grid grid-3">
            <Panel title="Strategy Performance" sub="Historical breakdown" style={{ gridColumn: 'span 2' }}>
              {(hist?.stats?.strategyBreakdown || []).map((s) => (
                <div key={s.strategy} className="list-item">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <span style={{ fontWeight: 600 }}>{s.strategy}</span>
                      <span className="muted" style={{ marginLeft: 8, fontSize: 11 }}>{s.count} trades</span>
                    </div>
                    <div style={{ display: 'flex', gap: 14 }}>
                      <span className={s.profit >= 0 ? 'green' : 'red'} style={{ fontWeight: 700 }}>${s.profit}</span>
                      <Badge type={s.winRate >= 0.5 ? 'buy' : 'sell'}>{s.winRate} WR</Badge>
                    </div>
                  </div>
                </div>
              ))}
            </Panel>

            <Panel title="Replay Engine" sub="Market replay progression">
              {(replay?.replay || []).map((r) => (
                <div key={r.bar} className="list-item" style={{ padding: '5px 0', display: 'flex', justifyContent: 'space-between' }}>
                  <span className="muted">Bar {r.bar}</span>
                  <span>{r.price?.toFixed(4)}</span>
                  <Badge type={r.signal === 'bullish' ? 'buy' : r.signal === 'bearish' ? 'sell' : 'neutral'}>{r.signal}</Badge>
                </div>
              ))}
            </Panel>
          </div>

          <div style={{ height: 16 }} />
          <div className="grid grid-2">
            <Panel title="Pattern Matching" sub="Similar historical setups">
              {(patterns?.matches || []).map((m) => (
                <div key={m.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontWeight: 600 }}>{m.symbol} {m.direction}</div>
                    <div className="muted" style={{ fontSize: 10.5 }}>{m.strategy} · ${m.profit}</div>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <Badge type={m.win ? 'buy' : 'sell'}>{m.win ? 'WIN' : 'LOSS'}</Badge>
                    <span className="muted" style={{ fontSize: 11 }}>{m.similarity} sim</span>
                  </div>
                </div>
              ))}
            </Panel>
            <Panel title="Market Memory & AI Knowledge Base" sub="What the system has learned">
              <div className="list-item">
                <div style={{ fontWeight: 600 }}>Current Context</div>
                <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>{patterns?.currentSignal || 'Gathering context...'}</div>
              </div>
              <div className="list-item">
                <div style={{ fontWeight: 600 }}>Recurring Patterns</div>
                <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>
                  The system matches current setups against {hist?.stats?.total || 0} historical trades to identify statistical edges per strategy.
                </div>
              </div>
              <div className="list-item">
                <div style={{ fontWeight: 600 }}>AI Knowledge Base</div>
                <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>
                  Vector-embedded trade outcomes power the RAG memory used by the AI Decision Center.
                </div>
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
