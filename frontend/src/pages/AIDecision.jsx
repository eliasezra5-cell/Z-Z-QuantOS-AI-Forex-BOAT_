import { useState } from 'react';
import { useFetch, get, normalizeDecision } from '../api.js';
import { Panel, Badge, Loading, StatCard, Bar } from '../components/ui.jsx';
import { SYMBOL_LIST, useSymbol } from '../symbols.jsx';

export default function AIDecision() {
  const { symbol, setSymbol } = useSymbol();
  const [analysis, setAnalysis] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const { data: decisions } = useFetch('/ai/decisions?limit=15');
  const { data: memory } = useFetch('/ai/memory?limit=10');
  const { data: learning } = useFetch('/ai/learning');
  const { data: rag } = useFetch('/ai/rag?q=' + symbol + '&k=4');

  const run = async () => {
    setAnalyzing(true);
    try {
      const d = await get(`/ai/analyze/${symbol}`);
      setAnalysis(normalizeDecision(d));
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div>
      <div className="page-head">
        <div className="section-title">AI Decision Center</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {SYMBOL_LIST.map(([s]) => <option key={s}>{s}</option>)}
          </select>
          <button className="btn btn-primary" onClick={run} disabled={analyzing}>{analyzing ? 'Analyzing...' : 'Run Multi-Agent Analysis'}</button>
        </div>
      </div>

      {analysis && (
        <>
          <div className="grid grid-4">
            <StatCard label="Consensus Direction" value={analysis.consensus?.direction?.toUpperCase()} color={analysis.consensus?.direction === 'buy' ? 'green' : analysis.consensus?.direction === 'sell' ? 'red' : 'amber'} />
            <StatCard label="Confidence" value={`${analysis.confidence?.score}`} color={analysis.confidence?.level === 'high' ? 'green' : analysis.confidence?.level === 'medium' ? 'amber' : 'red'} sub={`Level: ${analysis.confidence?.level}`} />
            <StatCard label="Agreement" value={`${Math.round(analysis.consensus?.agreement * 100)}%`} sub={`${analysis.consensus?.buyWeight} buy / ${analysis.consensus?.sellWeight} sell`} />
            <StatCard label="Recommendation" value={analysis.recommendation?.action?.toUpperCase()} color="purple" sub={analysis.recommendation?.reason} />
          </div>

          <div style={{ height: 16 }} />
          <div className="grid grid-3">
            <Panel title="Trade Recommendation" sub="With expected risk & pips">
              <div className="kv">
                <dt>Action</dt><dd className="purple" style={{ fontWeight: 700 }}>{analysis.recommendation?.action}</dd>
                <dt>Direction</dt><dd>{analysis.recommendation?.direction}</dd>
                <dt>Entry</dt><dd>{analysis.recommendation?.entry}</dd>
                <dt>Stop Loss</dt><dd className="red">{analysis.recommendation?.stopLoss}</dd>
                <dt>Take Profit</dt><dd className="green">{analysis.recommendation?.takeProfit}</dd>
                <dt>Risk/Reward</dt><dd>{analysis.recommendation?.rrRatio}</dd>
                <dt>Expected Pips</dt><dd className="blue">{analysis.recommendation?.expectedPips}</dd>
                <dt>Expected Risk</dt><dd className="red">{analysis.recommendation?.expectedRisk}</dd>
              </div>
            </Panel>

            <Panel title="Multi-Agent Consensus" sub="5 agents weighted voting + custom">
              {analysis.agents?.map((a) => (
                <div key={a.id} className="list-item" style={{ padding: '6px 0' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, fontSize: 12 }}>{a.name || a.id.replace('_agent', '').replace(/_/g, ' ')}</span>
                    <Badge type={a.direction}>{a.direction}</Badge>
                  </div>
                  <div className="muted" style={{ fontSize: 10.5, marginTop: 2 }}>{a.reasoning}</div>
                </div>
              ))}
            </Panel>

            <Panel title="Explainable AI (XAI)" sub="Decision transparency">
              <div className="list-item">
                <div style={{ fontWeight: 600, marginBottom: 6 }}>Decision Timeline</div>
                {analysis.xai?.timeline?.map((t, i) => (
                  <div key={i} style={{ fontSize: 11, padding: '3px 0', borderLeft: '2px solid var(--border2)', paddingLeft: 10, marginBottom: 2 }}>
                    <span className="muted" style={{ fontSize: 10 }}>{i + 1}.</span> <span style={{ fontWeight: 600 }}>{t.step}</span>
                    <div className="muted">{t.detail}</div>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 10 }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>Confidence Breakdown</div>
                <Bar pct={Math.round((analysis.consensus?.agreement || 0) * 100)} color="var(--accent)" /><span className="muted" style={{ fontSize: 10 }}>Agreement {Math.round((analysis.consensus?.agreement || 0) * 100)}%</span>
                <div style={{ height: 4 }} />
                <Bar pct={Math.round((analysis.confidence?.score || 0) * 100)} color="var(--purple)" /><span className="muted" style={{ fontSize: 10 }}>Agent Confidence {Math.round((analysis.confidence?.score || 0) * 100)}%</span>
                <div style={{ height: 4 }} />
                <Bar pct={Math.round((analysis.confidence?.score || 0) * 100)} color="var(--amber)" /><span className="muted" style={{ fontSize: 10 }}>Context Quality {Math.round((analysis.confidence?.score || 0) * 100)}%</span>
              </div>
            </Panel>
          </div>
        </>
      )}

      <div style={{ height: 16 }} />
      <div className="grid grid-3">
        <Panel title="Recent AI Decisions" sub="Consensus log (real pipeline)">
          {(decisions || []).map((d) => { const nd = normalizeDecision(d); return (
            <div key={nd.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <span style={{ fontWeight: 700 }}>{nd.symbol}</span>
                <div className="muted" style={{ fontSize: 10.5 }}>{new Date(nd.timestamp).toLocaleString()}</div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <Badge type={nd.consensus.direction}>{nd.consensus.direction}</Badge>
                <span className={nd.confidence.score >= 0.6 ? 'green' : 'amber'} style={{ fontWeight: 700 }}>{nd.confidence.score}</span>
              </div>
            </div>
          ); })}
        </Panel>

        <Panel title="RAG Knowledge Context" sub="Vector memory retrieval">
          {(rag?.context || []).map((c, i) => (
            <div key={i} className="list-item">
              <div style={{ fontSize: 11.5 }}>{c.text}</div>
              <div className="muted" style={{ fontSize: 10 }}>Relevance: {c.score}</div>
            </div>
          ))}
        </Panel>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Panel title="AI Learning Engine" sub="Model weights & training">
            <div className="kv">
              <dt>Version</dt><dd>{learning?.version}</dd>
              <dt>Samples</dt><dd>{learning?.sampleCount}</dd>
              <dt>Win Rate</dt><dd className="green">{learning?.performance?.winRate}%</dd>
              <dt>Avg Profit</dt><dd>{learning?.performance?.avgProfit}</dd>
            </div>
            <div style={{ marginTop: 8 }}>
              {Object.entries(learning?.weights || {}).map(([k, v]) => (
                <div key={k} className="meter-row">
                  <span className="meter-label">{k}</span>
                  <div style={{ flex: 1 }}><Bar pct={v * 50} color="var(--purple)" /></div>
                  <span className="meter-val">{v}</span>
                </div>
              ))}
            </div>
          </Panel>
          <Panel title="AI Memory" sub="Short & long-term">
            {(memory || []).slice(0, 6).map((m, i) => (
              <div key={i} className="list-item" style={{ padding: '4px 0', fontSize: 11 }}>
                <span style={{ fontWeight: 600 }}>{m.key}</span>
                <div className="muted" style={{ fontSize: 10 }}>{new Date(m.rememberedAt).toLocaleTimeString()}</div>
              </div>
            ))}
          </Panel>
        </div>
      </div>
    </div>
  );
}
