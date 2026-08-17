import { useFetch, post } from '../api.js';
import { Panel, Badge, Loading, StatCard } from '../components/ui.jsx';

export default function Alerts() {
  const { data: alerts, loading } = useFetch('/alerts?limit=50');
  const { data: rules } = useFetch('/alerts/rules');
  const { data: stats } = useFetch('/alerts/stats');
  const { data: channels } = useFetch('/alerts?limit=1');

  const notify = async () => {
    await post('/alerts/notify', { subject: 'Manual Test Alert', message: 'Notification channels are operational', severity: 'info', channels: ['web', 'telegram'] });
  };

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Alerts & Notifications Center</div>
        <button className="btn btn-primary" onClick={notify}>Send Test Notification</button>
      </div>

      <div className="grid grid-4">
        <StatCard label="Total Alerts" value={stats?.total} />
        <StatCard label="Unread" value={stats?.unread} color="amber" />
        <StatCard label="Critical" value={stats?.bySeverity?.critical} color="red" />
        <StatCard label="Channels" value="8" sub="Email · TG · WA · Push · Desktop · MT5 · Web" />
      </div>

      <div style={{ height: 16 }} />
      <div className="grid grid-3">
        <Panel title="Alert Feed" sub="Real-time notifications" style={{ gridColumn: 'span 2' }}>
          {loading ? <Loading /> : (alerts || []).map((a) => (
            <div key={a.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
              <div>
                <div style={{ fontWeight: 600 }}>{a.title}</div>
                <div className="muted" style={{ fontSize: 11 }}>{a.message}</div>
              </div>
              <div style={{ textAlign: 'right', flexShrink: 0 }}>
                <Badge type={a.severity}>{a.severity}</Badge>
                <div className="muted" style={{ fontSize: 10, marginTop: 2 }}>{new Date(a.timestamp).toLocaleString()}</div>
              </div>
            </div>
          ))}
        </Panel>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Panel title="Notification Channels">
            {['Email', 'Telegram', 'WhatsApp', 'Push', 'Desktop', 'MT5 Alerts', 'Web', 'AI Recommendations'].map((c) => (
              <div key={c} className="list-item" style={{ padding: '6px 0', display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 12 }}>{c}</span>
                <Badge type="buy">Active</Badge>
              </div>
            ))}
          </Panel>
          <Panel title="Custom Alert Rules" sub="Condition-based triggers">
            {(rules || []).map((r) => (
              <div key={r.id} className="list-item" style={{ padding: '6px 0' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontWeight: 600, fontSize: 12 }}>{r.name}</span>
                  <Badge type={r.enabled ? 'buy' : 'neutral'}>{r.enabled ? 'ON' : 'OFF'}</Badge>
                </div>
                <div className="muted" style={{ fontSize: 10 }}>
                  {r.condition} · threshold {r.threshold} · {r.channels.join(', ')}
                </div>
              </div>
            ))}
          </Panel>
        </div>
      </div>
    </div>
  );
}
