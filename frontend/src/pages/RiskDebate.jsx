import { useFetch } from '../api.js';
import { Panel, Badge, StatCard } from '../components/ui.jsx';
import { SYMBOL_LIST, useSymbol } from '../symbols.jsx';

const officerColor = (stance) => ({ aggressive: 'red', conservative: 'green', neutral: 'amber' }[stance] || 'neutral');
const verdictBadge = (v) => ({ approve: 'buy', reduce: 'amber', reject: 'sell', abstain: 'neutral' }[v] || 'neutral');

export default function RiskDebate() {
  const { symbol, setSymbol } = useSymbol();
  const { data: latest, refresh } = useFetch(`/risk/debate/${symbol}/latest`);
  const { data: history } = useFetch('/risk/debate/history?limit=10');
  const gate = latest && latest.verdict ? latest : null;

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Risk Debate Team</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {SYMBOL_LIST.map(([s]) => <option key={s}>{s}</option>)}
          </select>
          <button className="btn btn-primary" onClick={refresh}>Refresh</button>
        </div>
      </div>

      {!gate && (
        <Panel title="No Risk Debate Recorded" sub="Every placed order runs through the risk debate + portfolio gate">
          <div className="empty">No risk debate stored for {symbol} yet. Place an order to trigger the gate.</div>
        </Panel>
      )}

      {gate && (
        <>
          <div className="grid grid-4">
            <StatCard label="Gate Verdict" value={(gate.verdict || '—').toUpperCase()} color={gate.verdict === 'approve' ? 'green' : gate.verdict === 'reduce' ? 'amber' : 'red'} />
            <StatCard label="Approved" value={gate.approved ? 'YES' : 'NO'} color={gate.approved ? 'green' : 'red'} />
            <StatCard label="Volume" value={gate.maxVolume ?? '—'} sub={`requested ${gate.requestedVolume ?? '—'}`} color={gate.verdict === 'reduce' ? 'amber' : 'blue'} />
            <StatCard label="Reason" value={gate.reason ? 'See panel' : '—'} sub="conservative resolution" />
          </div>

          <div style={{ height: 16 }} />
          <div className="grid grid-3">
            {(gate.officers || []).map((o) => (
              <Panel key={o.stance} title={`${o.stance.charAt(0).toUpperCase() + o.stance.slice(1)} Risk Officer`} sub={`Confidence ${o.confidence ?? '—'}`}>
                <Badge type={verdictBadge(o.verdict)}>{String(o.verdict).toUpperCase()}</Badge>
                <div style={{ marginTop: 10, fontSize: 12.5, lineHeight: 1.6 }}>{o.rationale}</div>
              </Panel>
            ))}
            {(gate.officers || []).length === 0 && <Panel title="Officers"><div className="empty">No officer votes recorded.</div></Panel>}
          </div>

          <div style={{ height: 16 }} />
          <Panel title="Portfolio Gate Resolution" sub={`Debate ${gate.debateId || ''}`}>
            <div className="kv">
              <dt>Verdict</dt><dd className="purple" style={{ fontWeight: 700 }}>{gate.verdict}</dd>
              <dt>Reason</dt><dd style={{ textAlign: 'left', fontWeight: 400 }}>{gate.reason}</dd>
              <dt>Risk (% equity)</dt><dd>{gate.context?.riskAmountPct != null ? `${gate.context.riskAmountPct}%` : '—'}</dd>
              <dt>Notional (% equity)</dt><dd>{gate.context?.notionalPct != null ? `${gate.context.notionalPct}%` : '—'}</dd>
              <dt>Confidence</dt><dd>{gate.context?.confidence ?? '—'}</dd>
            </div>
          </Panel>
        </>
      )}

      <div style={{ height: 16 }} />
      <Panel title="Risk Debate History" sub={`Latest ${(history || []).length} gate runs (all symbols)`}>
        {(history || []).map((d, i) => (
          <div key={i} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontWeight: 700 }}>{d.symbol}</span>
              <span className="muted"> · {d.verdict}</span>
              <span className="muted" style={{ marginLeft: 6 }}>· vol {d.requestedVolume}→{d.maxVolume}</span>
              <div className="muted" style={{ fontSize: 10.5 }}>{new Date(d.timestamp).toLocaleString()}</div>
            </div>
            <Badge type={gate && d.id === gate.debateId ? 'buy' : 'neutral'}>{gate && d.id === gate.debateId ? 'current' : d.verdict}</Badge>
          </div>
        ))}
        {(history || []).length === 0 && <div className="empty">No risk debate history yet.</div>}
      </Panel>
    </div>
  );
}
