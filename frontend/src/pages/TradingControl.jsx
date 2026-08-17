import { useState } from 'react';
import { useFetch, post } from '../api.js';
import { Panel, Badge, StatCard, Loading, KeyValue } from '../components/ui.jsx';

const MODES = [
  {
    key: 'ANALYSIS_ONLY',
    label: 'ANALYSIS ONLY',
    tag: 'Manual',
    icon: '◉',
    desc: 'Full AI analysis and consensus scoring. No orders are placed.',
    color: 'blue'
  },
  {
    key: 'SEMI_AUTO',
    label: 'SEMI-AUTO',
    tag: 'AI Suggests · User Approves',
    icon: '⇄',
    desc: 'AI builds suggested trades and requests your approval before execution.',
    color: 'amber'
  },
  {
    key: 'AUTO_FULL',
    label: 'AUTO FULL',
    tag: 'AI Executes if Conf ≥ 90%',
    icon: '✦',
    desc: 'AI executes automatically when confidence is ≥ 90% and all risk gates are open.',
    color: 'green'
  },
  {
    key: 'EMERGENCY_STOP',
    label: 'EMERGENCY STOP',
    tag: 'Kill Switch',
    icon: '■',
    desc: 'Instantly halts all trading, closes positions, and blocks new orders.',
    color: 'red'
  }
];

const MODE_COLORS = {
  blue: 'var(--blue)',
  amber: 'var(--amber)',
  green: 'var(--green)',
  red: 'var(--red)'
};

export default function TradingControl() {
  const { data: modes, refresh } = useFetch('/execution/modes');
  const { data: mt5 } = useFetch('/mt5/status');
  const { data: capital } = useFetch('/capital/status');
  const [sending, setSending] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);

  const activeMode = modes?.mode || 'DISABLED';
  const state = modes?.state || {};
  const killSwitches = modes?.kill_switches || {};
  const activeKillSwitches = Object.entries(killSwitches).filter(([, v]) => !!v && v.active !== false);

  const dailyLossPct = Number(state.max_daily_loss_pct) || 5;
  const dailyLossNow = Number(state.daily_loss) || 0;
  const dailyLimitPct = Math.min(Math.max((Math.abs(dailyLossNow) / dailyLimit()) * 100, 0), 100);
  const shield = capital?.shield_level || 'GREEN';

  function dailyLimit() {
    return Math.max(dailyLossPct, 1);
  }

  const clearKillSwitches = async () => {
    setClearing(true);
    setError(null);
    setNotice(null);
    try {
      const res = await post('/execution/kill-switches/clear', { actor: 'admin' });
      if (res.status === 'ok') {
        setNotice(`Kill switches cleared (${res.cleared?.length || 0}) — mode reset to ${res.mode}`);
      } else {
        setError(res.status || 'Failed to clear kill switches');
      }
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setClearing(false);
    }
  };

  const selectMode = async (modeKey) => {
    setSending(true);
    setError(null);
    setNotice(null);
    try {
      const res = await post('/execution/modes', {
        mode: modeKey,
        actor: 'admin',
        reason: `Selected from Trading Control UI (${new Date().toISOString()})`
      });
      if (res.status === 'ok' || res.status === 'promoted') {
        setNotice(`Trading mode set to ${res.mode || modeKey}`);
      } else {
        setError(res.status || 'Unknown response from trading mode API');
      }
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setSending(false);
    }
  };

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Trading Control</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Badge type={activeMode === 'EMERGENCY_STOP' ? 'critical' : activeMode === 'AUTO_FULL' ? 'buy' : 'info'}>
            Active Mode: {activeMode}
          </Badge>
          <button className="btn btn-sm" onClick={refresh}>Refresh</button>
        </div>
      </div>

      <div className="grid grid-4">
        <StatCard
          label="Active Mode"
          value={activeMode}
          color={activeMode === 'EMERGENCY_STOP' ? 'red' : activeMode === 'AUTO_FULL' ? 'green' : activeMode === 'SEMI_AUTO' ? 'amber' : 'blue'}
          sub={`Profile: ${modes?.profile?.name || modes?.profile || 'conservative'}`}
        />
        <StatCard
          label="MT5 Connection"
          value={mt5?.connected ? 'Connected' : 'Offline'}
          color={mt5?.connected ? 'green' : 'red'}
          sub={`Mode: ${mt5?.mode || '—'} · ${mt5?.account?.broker || mt5?.account?.server || 'no bridge'}`}
        />
        <StatCard
          label="Daily P&L Limit"
          value={`${Math.abs(dailyLossNow).toFixed(2)} / ${dailyLimitPct.toFixed(0)}%`}
          color={dailyLimitPct >= 100 ? 'red' : dailyLimitPct >= 75 ? 'amber' : 'green'}
          sub={`Max daily loss ${dailyLimitPct.toFixed(0)}% · ${capital?.daily_locked ? 'Day locked' : 'Open'}`}
        />
        <StatCard
          label="Capital Shield"
          value={shield}
          color={shield === 'RED' ? 'red' : shield === 'ORANGE' ? 'amber' : 'green'}
          sub={capital?.emergency_stop ? 'EMERGENCY STOP ACTIVE' : 'Protection nominal'}
        />
      </div>

      {activeKillSwitches.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="list-item" style={{ border: '1px solid var(--red)', borderRadius: 10, padding: 10 }}>
            <b className="red">Active kill switches:</b>{' '}
            {activeKillSwitches.map(([k, v]) => <Badge key={k} type="critical">{k}</Badge>)}
            <button
              className="btn btn-sm btn-danger"
              style={{ marginLeft: 8 }}
              onClick={clearKillSwitches}
              disabled={clearing}
            >
              {clearing ? 'Clearing...' : 'Clear Kill Switches'}
            </button>
          </div>
        </div>
      )}

      <div style={{ height: 16 }} />

      <Panel title="Trading Mode Selector" sub="Send mode updates to the execution engine">
        {sending && <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>Sending mode update...</div>}
        {error && <div className="empty" style={{ color: 'var(--red)', padding: 10, textAlign: 'left' }}>Error: {error}</div>}
        {notice && <div className="empty" style={{ color: 'var(--green)', padding: 10, textAlign: 'left' }}>{notice}</div>}
        <div className="mode-grid">
          {MODES.map((m) => {
            const isActive = activeMode === m.key;
            const accent = MODE_COLORS[m.color];
            return (
              <button
                key={m.key}
                className={`mode-card ${isActive ? 'active' : ''} ${m.key === 'EMERGENCY_STOP' ? 'danger' : ''}`}
                onClick={() => selectMode(m.key)}
                disabled={sending}
                style={{ '--mode-accent': accent }}
              >
                <div className="mode-card-icon">{m.icon}</div>
                <div className="mode-card-label">{m.label}</div>
                <div className="mode-card-tag" style={{ color: accent }}>{m.tag}</div>
                <div className="mode-card-desc">{m.desc}</div>
                {isActive && <div className="mode-card-current" style={{ background: accent }}>CURRENT</div>}
              </button>
            );
          })}
        </div>
      </Panel>

      <div style={{ height: 16 }} />

      {activeMode === 'SEMI_AUTO' && (
        <div className="list-item" style={{ border: '1px solid var(--amber)', borderRadius: 10, padding: 12 }}>
          <span className="badge warning">SEMI-AUTO NOTIFICATIONS</span>{' '}
          <span style={{ fontWeight: 600, fontSize: 12 }}>Approval requests will be sent to your WhatsApp &amp; Telegram</span>
        </div>
      )}

      <div style={{ height: 16 }} />

      <div className="grid grid-2">
        <Panel title="Mode Status" sub="Trading mode manager state">
          {modes ? (
            <KeyValue rows={[
              ['Mode', activeMode],
              ['Profile', modes?.profile?.name || modes?.profile || '—'],
              ['Blocked Reasons', (modes?.blocked_reasons || []).join(', ') || 'None'],
              ['Consecutive Losses', state.consecutive_losses ?? 0],
              ['Daily Loss', Math.abs(dailyLossNow).toFixed(2)],
              ['Max Daily Loss', `${dailyLimitPct.toFixed(2)}%`],
              ['Max Drawdown', `${state.max_drawdown_pct ?? 0}%`]
            ]} />
          ) : <Loading />}
        </Panel>
        <Panel title="Capital Protection" sub="Risk shield & emergency stops">
          {capital ? (
            <KeyValue rows={[
              ['Shield Level', shield],
              ['Emergency Stop', capital.emergency_stop ? 'ACTIVE' : 'Off'],
              ['Emergency Reason', capital.emergency_reason || '—'],
              ['Daily Locked', capital.daily_locked ? 'Yes' : 'No'],
              ['Fail Closed', (capital.fail_closed || []).join(', ') || 'None']
            ]} />
          ) : <Loading />}
        </Panel>
      </div>
    </div>
  );
}
