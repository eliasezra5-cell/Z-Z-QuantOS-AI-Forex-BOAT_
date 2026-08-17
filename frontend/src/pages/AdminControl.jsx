import { useEffect, useState, Fragment } from 'react';
import { api, post, useFetch } from '../api.js';
import { Panel, Badge, StatCard, Loading } from '../components/ui.jsx';

const SECTIONS = [
  { key: 'risk', label: 'Risk Control', icon: '◉' },
  { key: 'trading', label: 'Manual Trading', icon: '⇄' },
  { key: 'suggested', label: 'Suggested Trades', icon: '✦' },
  { key: 'ai', label: 'AI Control', icon: '✧' },
  { key: 'data', label: 'Data Sources', icon: '▣' },
  { key: 'safety', label: 'Safety Center', icon: '■' }
];

const KILL_SWITCHES = [
  'daily_loss_limit',
  'weekly_loss_limit',
  'equity_below_80pct',
  'max_drawdown_exceeded',
  'five_consecutive_losses',
  'mt5_disconnected',
  'market_data_stale',
  'ai_provider_failure',
  'weekend',
  'major_news_in_30m',
  'capital_shield_red'
];

const FAIL_CLOSED_TRIGGERS = ['mt5-disconnected', 'market-data-stale', 'ai-providers-down', 'reconciliation-mismatch'];

export default function AdminControl() {
  const [active, setActive] = useState('risk');
  return (
    <div>
      <div className="page-head">
        <div className="section-title">Admin Control Panel</div>
        <Badge type="info">6 Control Sections</Badge>
      </div>
      <div className="tabs">
        {SECTIONS.map((s) => (
          <div key={s.key} className={`tab ${active === s.key ? 'active' : ''}`} onClick={() => setActive(s.key)}>
            {s.icon} {s.label}
          </div>
        ))}
      </div>
      {active === 'risk' && <RiskControl />}
      {active === 'trading' && <ManualTrading />}
      {active === 'suggested' && <SuggestedTrades />}
      {active === 'ai' && <AIControl />}
      {active === 'data' && <DataSources />}
      {active === 'safety' && <SafetyCenter />}
    </div>
  );
}

function useToast() {
  const [toast, setToast] = useState(null);
  const showToast = (type, message) => {
    setToast({ type, message });
    window.clearTimeout(showToast._t);
    showToast._t = window.setTimeout(() => setToast(null), 5000);
  };
  const node = toast && (
    <div
      style={{
        position: 'fixed', right: 20, bottom: 20, zIndex: 100, maxWidth: 480,
        padding: '10px 14px', borderRadius: 8, fontSize: 12,
        background: 'var(--bg3)',
        border: `1px solid ${toast.type === 'success' ? 'var(--green)' : 'var(--red)'}`,
        color: toast.type === 'success' ? 'var(--green)' : 'var(--red)',
        boxShadow: '0 4px 16px rgba(0,0,0,0.4)'
      }}
    >
      {toast.message}
    </div>
  );
  return { showToast, node };
}

function Row({ label, children }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
      <div style={{ width: 220, fontSize: 12, color: 'var(--muted)', flexShrink: 0 }}>{label}</div>
      <div style={{ flex: 1 }}>{children}</div>
    </div>
  );
}

function Toggle({ on, onClick, disabled }) {
  return (
    <button
      className={`btn btn-sm ${on ? 'btn-primary' : ''}`}
      style={on ? {} : { color: 'var(--muted)' }}
      onClick={onClick}
      disabled={disabled}
    >
      {on ? 'ON' : 'OFF'}
    </button>
  );
}

// --------------------------------------------------------------------------- //
// Section 1: Risk Control
// --------------------------------------------------------------------------- //
function RiskControl() {
  const { data: settings, refresh: refreshSettings } = useFetch('/risk/settings');
  const { data: modes, refresh: refreshModes } = useFetch('/execution/modes');
  const { data: capital, refresh: refreshCapital } = useFetch('/capital/status');
  const { data: profiles } = useFetch('/execution/profiles');
  const { showToast, node } = useToast();
  const [form, setForm] = useState({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (settings) setForm((prev) => ({ ...prev, ...Object.fromEntries(settings.map((s) => [s.id, s.value])) }));
  }, [settings]);

  const applyAll = async () => {
    setBusy(true);
    let saved = 0;
    for (const s of settings || []) {
      if (s.value === form[s.id]) continue;
      try {
        await post(`/risk/settings/${s.id}`, { value: form[s.id] });
        saved += 1;
      } catch (e) {
        showToast('error', `${s.id}: ${e.message}`);
      }
    }
    refreshSettings();
    showToast('success', saved ? `Applied ${saved} risk setting(s)` : 'No changes to apply');
    setBusy(false);
  };

  const saveToggle = async (id, enabled) => {
    try {
      await post(`/risk/settings/${id}`, { value: enabled });
      showToast('success', `${id} ${enabled ? 'enabled' : 'disabled'}`);
    } catch (e) {
      showToast('error', e.message);
    }
    refreshSettings();
  };

  const setProfile = async (profileId) => {
    try {
      const res = await post('/execution/profiles', { profile_id: profileId });
      showToast('success', res.status === 'ok' ? `Profile set to ${res.profile?.name || profileId}` : res.status);
      refreshModes();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const emergencyStop = async (activate) => {
    if (activate && !window.confirm('ACTIVATE EMERGENCY STOP? All trading halts immediately.')) return;
    try {
      const res = activate
        ? await post('/capital/emergency-stop', { reason: 'Admin Control Panel' })
        : await post('/capital/emergency-stop/clear', { actor: 'admin' });
      showToast('success', activate ? 'EMERGENCY STOP activated' : 'Emergency stop cleared');
      refreshCapital();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const failClosed = async (trigger, on) => {
    try {
      await post(on ? `/capital/fail-closed/${trigger}` : `/capital/fail-closed/${trigger}/clear`, {});
      showToast('success', `${trigger} ${on ? 'raised' : 'cleared'}`);
      refreshCapital();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const killSwitch = async (name, active) => {
    try {
      await post(`/execution/kill-switches/${name}`, { active });
      showToast('success', `${name} ${active ? 'triggered' : 'cleared'}`);
      refreshModes();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const killSwitches = modes?.kill_switches || {};
  const activeFailClosed = capital?.fail_closed || [];

  return (
    <div>
      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <StatCard label="Risk Profile" value={modes?.profile?.name || modes?.profile || '—'} sub="Execution profile" />
        <StatCard label="Capital Shield" value={capital?.shield_level || '—'} color={capital?.shield_level === 'RED' ? 'red' : 'green'} sub={capital?.emergency_stop ? 'EMERGENCY STOP' : 'Nominal'} />
        <StatCard label="Fail Closed" value={activeFailClosed.length || 0} sub={activeFailClosed.join(', ') || 'None active'} />
        <StatCard label="Kill Switches" value={Object.values(killSwitches).filter((v) => v && v.active !== false).length} sub="Active count" />
      </div>

      <div className="grid grid-2">
        <Panel title="Risk Settings" sub="Percent of equity · save via Apply All">
          {(settings || []).map((s) => {
            const isBool = typeof s.value === 'boolean' || s.id.includes('required');
            const value = form[s.id];
            return (
              <Row key={s.id} label={`${s.id} — ${s.description}`}>
                {isBool ? (
                  <Toggle on={!!value} onClick={() => saveToggle(s.id, !value)} />
                ) : (
                  <input
                    type="number"
                    value={value ?? ''}
                    onChange={(e) => setForm((f) => ({ ...f, [s.id]: Number(e.target.value) }))}
                  />
                )}
              </Row>
            );
          })}
          <button className="btn btn-primary" onClick={applyAll} disabled={busy || !settings}>
            {busy ? 'Applying…' : 'Apply All'}
          </button>
        </Panel>

        <Panel title="Risk Profile Selector" sub="Preset execution risk profiles">
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {(profiles || []).map((p) => {
              const current = (modes?.profile?.id || modes?.profile) === p.id;
              return (
                <button key={p.id} className={`btn btn-sm ${current ? 'btn-primary' : ''}`} onClick={() => setProfile(p.id)}>
                  {p.name} · conf {p.min_confidence}
                </button>
              );
            })}
          </div>
          <div style={{ height: 16 }} />
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-danger" onClick={() => emergencyStop(true)}>Emergency Stop</button>
            <button className="btn" onClick={() => emergencyStop(false)}>Clear Emergency Stop</button>
          </div>
          <div style={{ height: 16 }} />
          <div className="muted" style={{ fontSize: 11 }}>Fail-closed triggers (disable new trades):</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 6 }}>
            {FAIL_CLOSED_TRIGGERS.map((t) => (
              <Toggle key={t} on={activeFailClosed.includes(t)} onClick={() => failClosed(t, !activeFailClosed.includes(t))} />
            ))}
          </div>
        </Panel>
      </div>

      <div style={{ height: 16 }} />
      <Panel title="Kill Switches" sub="Force-halt conditions (execution manager)">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
          {KILL_SWITCHES.map((name) => {
            const v = killSwitches[name];
            const active = !!v && v.active !== false;
            return (
              <div key={name} className="list-item" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 12 }}>{name}</span>
                <Toggle on={active} onClick={() => killSwitch(name, !active)} />
              </div>
            );
          })}
        </div>
        <button className="btn btn-danger" style={{ marginTop: 10 }} onClick={async () => {
          const res = await post('/execution/kill-switches/clear', { actor: 'admin' });
          showToast('success', `Cleared ${res.cleared?.length || 0} kill switch(es)`);
          refreshModes();
        }}>
          Clear All Kill Switches
        </button>
      </Panel>
      {node}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Section 2: Manual Trading
// --------------------------------------------------------------------------- //
function ManualTrading() {
  const { data: positions, refresh } = useFetch('/trading/positions');
  const { data: schedulesData, refresh: refreshSchedules } = useFetch('/execution/schedules');
  const { showToast, node } = useToast();
  const [order, setOrder] = useState({ symbol: 'XAUUSD', side: 'buy', volume: 0.1, stopLoss: '', takeProfit: '' });
  const [sched, setSched] = useState({ start: 8, end: 20, days: [], enabled: true });
  const [busy, setBusy] = useState(false);

  const placeOrder = async () => {
    setBusy(true);
    try {
      const body = {
        symbol: order.symbol.toUpperCase(),
        side: order.side,
        type: 'market',
        volume: Number(order.volume) || 0.1,
        source: 'manual'
      };
      if (order.stopLoss !== '') body.stopLoss = Number(order.stopLoss);
      if (order.takeProfit !== '') body.takeProfit = Number(order.takeProfit);
      const res = await post('/trading/orders', body);
      if (res.status === 'rejected') showToast('error', `Order rejected: ${(res.violations || []).join('; ') || 'safety gate'}`);
      else showToast('success', `Order ${res.status || 'placed'} for ${body.symbol}`);
      refresh();
    } catch (e) {
      showToast('error', e.message);
    } finally {
      setBusy(false);
    }
  };

  const positionAction = async (id, action, extra = {}) => {
    try {
      const res = await post(`/trading/positions/${id}/${action}`, extra);
      showToast('success', `${action} → ${res?.status || 'ok'}`);
      refresh();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const addSchedule = async () => {
    try {
      await post('/execution/schedules', {
        start: Number(sched.start),
        end: Number(sched.end),
        days: sched.days,
        enabled: sched.enabled,
        comment: 'Admin Control Panel'
      });
      showToast('success', 'Schedule added');
      refreshSchedules();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const schedules = schedulesData?.schedules || [];
  const daysOfWeek = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  return (
    <div className="grid grid-2">
      <Panel title="Place Manual Order" sub="Market order via trading engine (risk-gated)">
        <Row label="Symbol"><input value={order.symbol} onChange={(e) => setOrder({ ...order, symbol: e.target.value })} /></Row>
        <Row label="Direction">
          <select value={order.side} onChange={(e) => setOrder({ ...order, side: e.target.value })}>
            <option value="buy">BUY</option>
            <option value="sell">SELL</option>
          </select>
        </Row>
        <Row label="Lot Size"><input type="number" step="0.01" value={order.volume} onChange={(e) => setOrder({ ...order, volume: e.target.value })} /></Row>
        <Row label="Stop Loss"><input type="number" step="0.001" value={order.stopLoss} onChange={(e) => setOrder({ ...order, stopLoss: e.target.value })} /></Row>
        <Row label="Take Profit"><input type="number" step="0.001" value={order.takeProfit} onChange={(e) => setOrder({ ...order, takeProfit: e.target.value })} /></Row>
        <button className="btn btn-primary" onClick={placeOrder} disabled={busy}>{busy ? 'Placing…' : 'Place Order'}</button>
      </Panel>

      <Panel title="Trade Schedules" sub="Time slots when the bot may trade (hour of day, UTC)">
        <Row label="Start Hour"><input type="number" min="0" max="23" value={sched.start} onChange={(e) => setSched({ ...sched, start: e.target.value })} /></Row>
        <Row label="End Hour"><input type="number" min="0" max="23" value={sched.end} onChange={(e) => setSched({ ...sched, end: e.target.value })} /></Row>
        <Row label="Days">
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {daysOfWeek.map((d, i) => (
              <button
                key={d}
                className={`btn btn-sm ${sched.days.includes(i) ? 'btn-primary' : ''}`}
                onClick={() => setSched({
                  ...sched,
                  days: sched.days.includes(i) ? sched.days.filter((x) => x !== i) : [...sched.days, i]
                })}
              >
                {d}
              </button>
            ))}
          </div>
        </Row>
        <button className="btn" onClick={addSchedule}>Add Schedule</button>
        <div style={{ height: 12 }} />
        {schedules.length === 0 ? <div className="muted" style={{ fontSize: 11 }}>No schedules (trading unrestricted).</div> : schedules.map((s) => (
          <div key={s.id} className="list-item" style={{ fontSize: 12 }}>
            {s.start}:00–{s.end}:00 {s.days?.length ? `· days ${s.days.map((d) => daysOfWeek[d]).join(',')}` : '· all days'} · {s.enabled ? 'enabled' : 'disabled'}
          </div>
        ))}
      </Panel>

      <Panel title="Open Positions" sub="Live positions with management actions" className="">
        {positions === null ? <Loading /> : (positions || []).length === 0 ? (
          <div className="empty">No open positions</div>
        ) : (
          (positions || []).map((p) => (
            <div key={p.id} className="list-item">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <div>
                  <b>{p.symbol}</b> {p.side} · vol {p.volume}
                  {p.stopLoss ? ` · SL ${p.stopLoss}` : ''}{p.takeProfit ? ` · TP ${p.takeProfit}` : ''}
                  <div className="muted" style={{ fontSize: 11 }}>profit: {p.profit ?? '—'}</div>
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  <button className="btn btn-sm btn-danger" onClick={() => positionAction(p.id, 'close', { reason: 'manual' })}>Close</button>
                  <button className="btn btn-sm" onClick={() => positionAction(p.id, 'reverse')}>Reverse</button>
                  <button className="btn btn-sm" onClick={() => {
                    const sl = window.prompt('New SL:', p.stopLoss ?? '');
                    if (sl !== null) positionAction(p.id, 'modify', { stopLoss: Number(sl) });
                  }}>SL</button>
                  <button className="btn btn-sm" onClick={() => {
                    const pct = window.prompt('Partial % (e.g. 50):', '50');
                    if (pct !== null) positionAction(p.id, 'partial', { percent: Number(pct) });
                  }}>Partial</button>
                </div>
              </div>
            </div>
          ))
        )}
      </Panel>
      {node}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Section 3: Suggested Trades
// --------------------------------------------------------------------------- //
function SuggestedTrades() {
  const { data: suggested, refresh } = useFetch('/execution/suggested');
  const { showToast, node } = useToast();
  const [evalResult, setEvalResult] = useState(null);
  const [running, setRunning] = useState(false);

  const act = async (id, action) => {
    try {
      await post(`/execution/suggested/${id}/${action}`, {});
      showToast('success', `${action} executed`);
      refresh();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const runEvaluation = async () => {
    setRunning(true);
    try {
      const res = await post('/execution/evaluate', { decision: {}, context: {} });
      setEvalResult(res);
      showToast('success', 'Evaluation pass completed');
    } catch (e) {
      showToast('error', e.message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div>
      <div className="page-head" style={{ marginBottom: 12 }}>
        <div className="muted" style={{ fontSize: 12 }}>Pending AI suggestions (70–89% confidence band)</div>
        <button className="btn" onClick={runEvaluation} disabled={running}>{running ? 'Evaluating…' : 'Run Evaluation Now'}</button>
      </div>
      {evalResult && (
        <Panel title="Last Evaluation" sub="Auto-trade controller verdict">
          <div className="kv">
            <dt>Verdict</dt><dd>{evalResult[0] ?? '—'}</dd>
            <dt>Reasons</dt><dd>{((evalResult[1] || [])).join('; ') || '—'}</dd>
          </div>
        </Panel>
      )}
      <div style={{ height: 12 }} />
      <Panel title="Suggested Trades">
        {suggested === null ? <Loading /> : (suggested || []).length === 0 ? (
          <div className="empty">No suggested trades</div>
        ) : (
          (suggested || []).map((t) => (
            <div key={t.id} className="list-item">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <div>
                  <b>{t.symbol}</b> {t.side} · <Badge type={t.confidence >= 0.8 ? 'buy' : 'neutral'}>{Math.round((t.confidence || 0) * 100)}%</Badge>
                  <div className="muted" style={{ fontSize: 11 }}>{t.reasoning || '—'} · status: {t.status}</div>
                </div>
                {t.status === 'pending' && (
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn btn-sm btn-primary" onClick={() => act(t.id, 'approve')}>Approve</button>
                    <button className="btn btn-sm btn-danger" onClick={() => act(t.id, 'reject')}>Reject</button>
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </Panel>
      {node}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Section 4: AI Control
// --------------------------------------------------------------------------- //
function AIControl() {
  const { data: agents, refresh: refreshAgents } = useFetch('/ai/agents');
  const { data: models, refresh: refreshModels } = useFetch('/ai/models');
  const { data: memory, refresh: refreshMemory } = useFetch('/ai/memory?limit=10');
  const { showToast, node } = useToast();
  const [symbol, setSymbol] = useState('XAUUSD');
  const [analysis, setAnalysis] = useState(null);
  const [memKey, setMemKey] = useState('');
  const [memValue, setMemValue] = useState('');

  const toggleAgent = async (a) => {
    try {
      await api(`/ai/agents/${a.id}`, { method: 'PUT', body: JSON.stringify({ enabled: !a.enabled }) });
      showToast('success', `${a.name} ${a.enabled ? 'disabled' : 'enabled'}`);
      refreshAgents();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const modelAction = async (id, action, body = {}) => {
    try {
      await post(`/ai/models/${id}/${action}`, body);
      showToast('success', `Model ${action}`);
      refreshModels();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const runAnalysis = async () => {
    try {
      const res = await post(`/ai/analyze/${symbol.toUpperCase()}`, {});
      setAnalysis(res);
      showToast('success', `Analysis complete for ${symbol.toUpperCase()}`);
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const addMemory = async () => {
    if (!memKey || !memValue) return showToast('error', 'Key and value required');
    try {
      await post('/ai/memory', { key: memKey, value: memValue, ttlMs: 0 });
      showToast('success', 'Memory saved');
      setMemKey(''); setMemValue('');
      refreshMemory();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const modelList = models?.models || [];

  return (
    <div className="grid grid-2">
      <Panel title="Custom Agents" sub="On/off control for AI agents">
        {agents === null ? <Loading /> : (agents || []).length === 0 ? (
          <div className="empty">No custom agents</div>
        ) : (agents || []).map((a) => (
          <div key={a.id} className="list-item" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 12 }}>{a.name} <span className="muted">· {a.provider_type}</span></span>
            <Toggle on={a.enabled} onClick={() => toggleAgent(a)} />
          </div>
        ))}
      </Panel>

      <Panel title="Model Governance" sub="Registry approve / reject / promote / rollback">
        {models === null ? <Loading /> : (modelList.length === 0 ? (
          <div className="empty">No models registered</div>
        ) : modelList.slice(0, 8).map((m) => (
          <div key={m.id} className="list-item">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ fontSize: 12 }}>
                {m.name || m.id} <Badge type={m.status === 'approved' ? 'buy' : m.status === 'pending' ? 'neutral' : 'info'}>{m.status || '—'}</Badge>
              </span>
              <div style={{ display: 'flex', gap: 4 }}>
                {m.status === 'pending' && (
                  <>
                    <button className="btn btn-sm btn-primary" onClick={() => modelAction(m.id, 'approve', { reviewer: 'admin' })}>Approve</button>
                    <button className="btn btn-sm btn-danger" onClick={() => modelAction(m.id, 'reject', { reviewer: 'admin' })}>Reject</button>
                  </>
                )}
                <button className="btn btn-sm" onClick={() => modelAction(m.id, 'promote')}>Promote</button>
              </div>
            </div>
          </div>
        )))}
        <button className="btn btn-sm" style={{ marginTop: 8 }} onClick={async () => {
          try {
            await post('/ai/models/rollback', {});
            showToast('success', 'Rollback executed');
            refreshModels();
          } catch (e) { showToast('error', e.message); }
        }}>Rollback Model</button>
      </Panel>

      <Panel title="Manual Analysis" sub="Trigger the full multi-agent decision pipeline">
        <Row label="Symbol"><input value={symbol} onChange={(e) => setSymbol(e.target.value)} /></Row>
        <button className="btn btn-primary" onClick={runAnalysis}>Analyze</button>
        {analysis && (
          <div style={{ marginTop: 10 }}>
            <div className="kv">
              <dt>Symbol</dt><dd>{analysis.symbol}</dd>
              <dt>Direction</dt><dd>{(analysis.direction || '—').toUpperCase()}</dd>
              <dt>Confidence</dt><dd>{Math.round((analysis.confidence ?? 0) * 100)}%</dd>
              <dt>Status</dt><dd>{analysis.status || '—'}</dd>
            </div>
          </div>
        )}
      </Panel>

      <Panel title="AI Memory" sub="Add a memory entry + recent entries">
        <Row label="Key"><input value={memKey} onChange={(e) => setMemKey(e.target.value)} placeholder="e.g. user_preference" /></Row>
        <Row label="Value"><input value={memValue} onChange={(e) => setMemValue(e.target.value)} placeholder="e.g. never trade GBPUSD" /></Row>
        <button className="btn btn-primary" onClick={addMemory}>Save Memory</button>
        <div style={{ height: 12 }} />
        {memory === null ? <Loading /> : (memory || []).slice(0, 8).map((m) => (
          <div key={m.id} className="list-item" style={{ fontSize: 11 }}>
            <span className="muted">{m.key}</span> — {m.value}
          </div>
        ))}
      </Panel>
      {node}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Section 5: Data Sources
// --------------------------------------------------------------------------- //
function DataSources() {
  const { data: sources, refresh } = useFetch('/news/sources');
  const { data: oppositeActions, refresh: refreshOpposite } = useFetch('/news/opposite-actions');
  const { showToast, node } = useToast();
  const [collectorResult, setCollectorResult] = useState(null);
  const [ingest, setIngest] = useState({ title: '', summary: '', url: '' });
  const [translate, setTranslate] = useState({ id: '', lang: 'ur' });

  const runCollectors = async () => {
    try {
      const res = await post('/news/collectors/run', { limit: 10 });
      setCollectorResult(res);
      showToast('success', 'Collectors run completed');
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const newsIngest = async () => {
    if (!ingest.title) return showToast('error', 'Title required');
    try {
      await post('/news/ingest', { ...ingest, source: 'manual' });
      showToast('success', 'News item queued');
      setIngest({ title: '', summary: '', url: '' });
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const doTranslate = async () => {
    if (!translate.id) return showToast('error', 'Item ID required');
    try {
      const res = await post(`/news/${translate.id}/translate?lang=${translate.lang}`, {});
      showToast('success', res.status === 'ok' ? `Translated → ${res.lang}` : res.reason || 'done');
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const removeSource = async (id) => {
    try {
      await fetch(`/api/news/sources/${id}`, { method: 'DELETE' });
      showToast('success', 'Source removed');
      refresh();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const toggleSource = async (s) => {
    try {
      await fetch(`/api/news/sources/${s.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !s.enabled })
      });
      showToast('success', `${s.name} ${s.enabled ? 'disabled' : 'enabled'}`);
      refresh();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const reverseOpposite = async (o) => {
    try {
      await post('/news/opposite-action/reverse', { position_id: o.positionId || o.position_id });
      showToast('success', 'Reverse allowed');
      refreshOpposite();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  return (
    <div>
      <Panel title="News Collectors" sub="Run all realtime collectors">
        <button className="btn btn-primary" onClick={runCollectors}>Run All Collectors</button>
        {collectorResult && (
          <div style={{ marginTop: 10 }}>
            <div className="kv">
              {Object.entries(collectorResult).filter(([k]) => k !== 'status').slice(0, 8).map(([k, v]) => (
                <Fragment key={k}><dt>{k}</dt><dd>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd></Fragment>
              ))}
            </div>
          </div>
        )}
      </Panel>
      <div style={{ height: 16 }} />
      <div className="grid grid-2">
        <Panel title="Manual News Ingest" sub="Queue a news item into the pipeline">
          <Row label="Title"><input value={ingest.title} onChange={(e) => setIngest({ ...ingest, title: e.target.value })} /></Row>
          <Row label="Summary"><textarea rows="3" value={ingest.summary} onChange={(e) => setIngest({ ...ingest, summary: e.target.value })} /></Row>
          <Row label="URL"><input value={ingest.url} onChange={(e) => setIngest({ ...ingest, url: e.target.value })} /></Row>
          <button className="btn btn-primary" onClick={newsIngest}>Ingest</button>
        </Panel>
        <Panel title="Translate News Item" sub="Translate a stored news item">
          <Row label="Item ID"><input value={translate.id} onChange={(e) => setTranslate({ ...translate, id: e.target.value })} /></Row>
          <Row label="Language">
            <select value={translate.lang} onChange={(e) => setTranslate({ ...translate, lang: e.target.value })}>
              <option value="ur">Urdu</option><option value="hi">Hindi</option>
              <option value="en">English</option><option value="ar">Arabic</option>
              <option value="es">Spanish</option>
            </select>
          </Row>
          <button className="btn" onClick={doTranslate}>Translate</button>
        </Panel>
      </div>
      <div style={{ height: 16 }} />
      <Panel title="News Sources" sub="Registered sources · full CRUD on News Terminal page">
        {sources === null ? <Loading /> : (sources || []).length === 0 ? (
          <div className="empty">No sources configured</div>
        ) : (sources || []).map((s) => (
          <div key={s.id} className="list-item" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <span style={{ fontSize: 12 }}>{s.name} <span className="muted">· {s.type}</span></span>
            <div style={{ display: 'flex', gap: 6 }}>
              <Toggle on={s.enabled !== false} onClick={() => toggleSource(s)} />
              <button className="btn btn-sm btn-danger" onClick={() => removeSource(s.id)}>Remove</button>
            </div>
          </div>
        ))}
      </Panel>
      <div style={{ height: 16 }} />
      <Panel title="Opposite-Action Signals" sub="News-vs-thesis reversal signals">
        {oppositeActions === null ? <Loading /> : (oppositeActions || []).length === 0 ? (
          <div className="empty">No opposite-action signals recorded</div>
        ) : (oppositeActions || []).map((o) => (
          <div key={o.id} className="list-item" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <span style={{ fontSize: 12 }}>{o.positionId || o.position_id || o.id} <span className="muted">· {o.flag || o.signal || 'signal'}</span></span>
            <button className="btn btn-sm" onClick={() => reverseOpposite(o)}>Allow Reverse</button>
          </div>
        ))}
      </Panel>
      {node}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Section 6: Safety Center
// --------------------------------------------------------------------------- //
function SafetyCenter() {
  const { data: brain, refresh: refreshBrain } = useFetch('/brain/kill-switches');
  const { data: frozen, refresh: refreshFrozen } = useFetch('/mt5/safety/frozen');
  const { showToast, node } = useToast();
  const [freezeSymbol, setFreezeSymbol] = useState('XAUUSD');
  const [pauseCond, setPauseCond] = useState('major_news_in_30m');
  const [blocker, setBlocker] = useState('');

  const brainSwitch = async (name, trigger) => {
    try {
      await post(`/brain/kill-switch/${name}/${trigger}`, {});
      showToast('success', `${name} ${trigger}`);
      refreshBrain();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const brainPause = async (clear) => {
    try {
      await post(clear ? `/brain/pause/${pauseCond}/clear` : `/brain/pause/${pauseCond}?minutes=30`, {});
      showToast('success', clear ? 'Pause cleared' : `Paused ${pauseCond}`);
      refreshBrain();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const freeze = async () => {
    try {
      await post(`/mt5/safety/freeze/${freezeSymbol.toUpperCase()}`, { reason: 'Admin Control Panel' });
      showToast('success', `Froze ${freezeSymbol.toUpperCase()}`);
      refreshFrozen();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const unfreeze = async (symbol) => {
    try {
      await post(`/mt5/safety/unfreeze/${symbol}`, {});
      showToast('success', `Unfroze ${symbol}`);
      refreshFrozen();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const hardBlocker = async (clear) => {
    if (!blocker.trim()) return showToast('error', 'Blocker name required');
    try {
      await post(clear ? `/validation/hard-blocker/${blocker.trim()}/clear` : `/validation/hard-blocker/${blocker.trim()}`, {});
      showToast('success', `Hard-blocker ${clear ? 'cleared' : 'raised'}: ${blocker.trim()}`);
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const fired = brain?.detected?.fired || {};

  return (
    <div className="grid grid-2">
      <Panel title="Brain Kill-Switches" sub="AI Brain auto-halt conditions">
        {KILL_SWITCHES.map((name) => {
          const v = fired[name];
          const active = !!v && v.active !== false;
          return (
            <div key={name} className="list-item" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 12 }}>{name}</span>
              {active ? (
                <button className="btn btn-sm btn-danger" onClick={() => brainSwitch(name, 'clear')}>Clear</button>
              ) : (
                <button className="btn btn-sm" onClick={() => brainSwitch(name, 'trigger')}>Trigger</button>
              )}
            </div>
          );
        })}
      </Panel>

      <div>
        <Panel title="Brain Pause Conditions" sub="Temporary pause of a kill-switch condition">
          <Row label="Condition">
            <select value={pauseCond} onChange={(e) => setPauseCond(e.target.value)}>
              {KILL_SWITCHES.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </Row>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn" onClick={() => brainPause(false)}>Pause 30m</button>
            <button className="btn" onClick={() => brainPause(true)}>Clear Pause</button>
          </div>
        </Panel>

        <div style={{ height: 16 }} />
        <Panel title="MT5 Safety" sub="Freeze symbols to block execution">
          <Row label="Symbol"><input value={freezeSymbol} onChange={(e) => setFreezeSymbol(e.target.value)} /></Row>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-danger" onClick={freeze}>Freeze Symbol</button>
            <button className="btn" onClick={async () => {
              try {
                await post('/mt5/safety/reconcile', { local: [], mt5: [] });
                showToast('success', 'Reconciliation requested');
              } catch (e) { showToast('error', e.message); }
            }}>Reconcile</button>
          </div>
          <div style={{ height: 12 }} />
          {frozen === null ? <Loading /> : (frozen?.symbols || frozen || []).length === 0 ? (
            <div className="muted" style={{ fontSize: 11 }}>No frozen symbols</div>
          ) : (frozen?.symbols || frozen || []).map((s) => (
            <div key={s.symbol || s} className="list-item" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 12 }}>{s.symbol || s}</span>
              <button className="btn btn-sm" onClick={() => unfreeze(s.symbol || s)}>Unfreeze</button>
            </div>
          ))}
        </Panel>

        <div style={{ height: 16 }} />
        <Panel title="Validation Hard-Blockers" sub="Raise / clear system-wide hard blockers">
          <Row label="Blocker"><input value={blocker} onChange={(e) => setBlocker(e.target.value)} placeholder="e.g. manual-shutdown" /></Row>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-danger" onClick={() => hardBlocker(false)}>Raise Blocker</button>
            <button className="btn" onClick={() => hardBlocker(true)}>Clear Blocker</button>
          </div>
        </Panel>
      </div>
      {node}
    </div>
  );
}
