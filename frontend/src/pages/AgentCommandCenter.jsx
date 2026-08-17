import { useEffect, useRef, useState } from 'react';
import { get, fmt, fmtPct, fmtMoney, fmtTime } from '../api.js';
import { Panel, Badge, Loading, StatCard } from '../components/ui.jsx';

const POLL_MS = 4000;
const MODELS_POLL_MS = 10000;

const STATUS_COLUMNS = ['idle', 'analyzing', 'voted', 'done'];

const AGENT_ICONS = {
  news: '◈',
  historical: '▦',
  macro: '◉',
  technical: '◮',
  risk: '⚔',
  sentiment: '✦',
  fundamentals: '▤',
  trend_agent: '⇄',
  indicator_agent: '▧',
  pattern_agent: '◭',
  smc_agent: '◈',
};

const DECISION_LABEL = {
  buy: 'BUY',
  sell: 'SELL',
  neutral: 'HOLD',
  abstain: 'ABSTAIN',
};

const DECISION_COLOR = {
  buy: 'var(--green)',
  sell: 'var(--red)',
  neutral: 'var(--amber)',
  abstain: 'var(--muted)',
};

function decisionLabel(d) {
  return DECISION_LABEL[(d || '').toLowerCase()] || (d || '—').toUpperCase();
}

function AgentCard({ agent, modelMap }) {
  const [showReason, setShowReason] = useState(false);
  const info = modelMap[agent.agent_id] || {};
  const confidence = agent.confidence != null ? agent.confidence * 100 : null;
  const icon = AGENT_ICONS[agent.agent_id] || '▣';

  return (
    <div className="panel" style={{ marginBottom: 10, cursor: 'grab', userSelect: 'none' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 18 }}>{icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 13 }}>{agent.name || agent.agent_id}</div>
          <div className="muted" style={{ fontSize: 10.5 }}>{agent.agent_id}</div>
        </div>
      </div>

      <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        <Badge type="info">{info.providerName || 'Local / Rule-Based'}</Badge>
        {info.model && <Badge type="info">{info.model}</Badge>}
      </div>

      <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 12 }}>
          Last decision:{' '}
          <span style={{ fontWeight: 800, color: DECISION_COLOR[decisionLabel(agent.decision).toLowerCase()] || 'var(--accent)' }}>
            {decisionLabel(agent.decision)}
          </span>
        </span>
        <span style={{ fontSize: 12, fontWeight: 700 }}>{confidence != null ? `${confidence.toFixed(0)}%` : '—'}</span>
      </div>

      <button
        className="btn"
        style={{ marginTop: 10, width: '100%', padding: '4px 0', fontSize: 11 }}
        onClick={() => setShowReason((v) => !v)}
      >
        {showReason ? 'Hide reasoning' : 'View reasoning'}
      </button>
      {showReason && (
        <div className="muted" style={{ marginTop: 8, fontSize: 11, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
          {agent.reasoning || 'No reasoning recorded yet.'}
        </div>
      )}
    </div>
  );
}

export default function AgentCommandCenter() {
  const [statuses, setStatuses] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastSync, setLastSync] = useState(null);
  const [models, setModels] = useState({ agents: [], cost: null });
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const loadStatus = async () => {
      try {
        const res = await get('/pro/agents/status');
        if (!mounted.current) return;
        setStatuses(res.agents || []);
        setError(null);
        setLastSync(Date.now());
      } catch (e) {
        if (mounted.current) setError(e.message);
      } finally {
        if (mounted.current) setLoading(false);
      }
    };

    const loadModels = async () => {
      try {
        const res = await get('/pro/agents/models-in-use');
        if (mounted.current) setModels(res);
      } catch (e) {
        /* models strip is optional; ignore failures */
      }
    };

    loadStatus();
    loadModels();
    const statusTimer = setInterval(loadStatus, POLL_MS);
    const modelsTimer = setInterval(loadModels, MODELS_POLL_MS);
    return () => {
      mounted.current = false;
      clearInterval(statusTimer);
      clearInterval(modelsTimer);
    };
  }, []);

  const modelMap = (models.agents || []).reduce((acc, a) => ({ ...acc, [a.agent_id]: a }), {});
  const cost = models.cost || {};
  const costTotal = cost.totalEstimatedCostUsd;

  const columns = STATUS_COLUMNS.map((col) => ({
    key: col,
    label: col.charAt(0).toUpperCase() + col.slice(1),
    agents: (statuses || []).filter((a) => (a.status || 'idle') === col),
  }));

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Agent Command Center</div>
        {lastSync && <span className="muted" style={{ fontSize: 11 }}>Live · synced {fmtTime(lastSync)}</span>}
      </div>

      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <StatCard label="Total Agents" value={statuses ? statuses.length : '…'} icon="✧" />
        <StatCard label="Analyzing" value={columns.find((c) => c.key === 'analyzing').agents.length} color="blue" icon="◉" />
        <StatCard label="Last Decision" value={(statuses || []).filter((a) => a.status === 'done').length ? 'Done' : '—'} icon="✓" />
        <StatCard label="Cost This Session" value={costTotal != null ? fmtMoney(costTotal) : '—'} sub={cost.totalTokens ? `${cost.totalTokens.toLocaleString()} tokens` : null} icon="▤" />
      </div>

      <Panel title="AI Models in Use" sub="Agent → provider/model mapping (read from registry)">
        {models.agents && models.agents.length ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {models.agents.map((a) => (
              <span key={a.agent_id} className="pill" style={{ fontSize: 10.5 }}>
                {a.name || a.agent_id} → {a.providerName || a.provider}: {a.model || '—'}
              </span>
            ))}
          </div>
        ) : (
          <div className="empty">No model mapping available.</div>
        )}
        {cost.providers && Object.keys(cost.providers).length > 0 && (
          <div className="muted" style={{ marginTop: 10, fontSize: 10.5 }}>
            {Object.entries(cost.providers).map(([pid, row]) => (
              <span key={pid} style={{ marginRight: 12 }}>{pid}: {fmtMoney(row.estimatedCostUsd)} ({row.calls} calls)</span>
            ))}
          </div>
        )}
      </Panel>

      <div style={{ height: 16 }} />

      {error && <div className="empty" style={{ color: 'var(--red)' }}>Error: {error}</div>}

      {loading && !statuses ? (
        <Loading />
      ) : (
        <div className="grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, alignItems: 'start' }}>
          {columns.map((col) => (
            <div key={col.key} className="panel" style={{ minHeight: 120 }}>
              <div className="panel-title">
                <span>{col.label}</span>
                <span className="badge" style={{ marginLeft: 'auto' }}>{col.agents.length}</span>
              </div>
              <div style={{ marginTop: 10 }}>
                {col.agents.length ? (
                  col.agents.map((a) => <AgentCard key={a.agent_id} agent={a} modelMap={modelMap} />)
                ) : (
                  <div className="empty">No agents</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
