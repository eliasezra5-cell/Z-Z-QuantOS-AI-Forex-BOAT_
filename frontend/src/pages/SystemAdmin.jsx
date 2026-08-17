import { useState } from 'react';
import { useFetch, post } from '../api.js';
import { Panel, Badge, Loading, StatCard, Meter } from '../components/ui.jsx';

export default function SystemAdmin() {
  const [tab, setTab] = useState('monitoring');
  const { data: health } = useFetch('/monitoring/health');
  const { data: metrics } = useFetch('/system/metrics?name=app.requests&limit=30');
  const { data: scheduler } = useFetch('/system/scheduler');
  const { data: queues } = useFetch('/system/queues');
  const { data: workers } = useFetch('/system/workers');
  const { data: admin } = useFetch('/admin/dashboard');
  const { data: config } = useFetch('/admin/config');
  const { data: security } = useFetch('/security/dashboard');
  const { data: keys } = useFetch('/security/keys');
  const { data: audit } = useFetch('/admin/audit?limit=10');
  const { data: users } = useFetch('/users');
  const { data: orgs } = useFetch('/users/organizations');
  const { data: integrations, refresh: refreshInt } = useFetch('/integrations');
  const { data: assets } = useFetch('/assets/overview');

  const testIntegration = async (id) => {
    await post(`/integrations/${id}/test`, {});
    refreshInt();
  };

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Admin & Infrastructure</div>
        <div className="tabs">
          {[['monitoring', 'Monitoring'], ['admin', 'System'], ['security', 'Security'], ['users', 'Users & Orgs'], ['integrations', 'Integrations'], ['assets', 'Multi-Asset']].map(([id, label]) => (
            <div key={id} className={`tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>{label}</div>
          ))}
        </div>
      </div>

      {tab === 'monitoring' && (
        <div className="grid grid-2">
          <Panel title="System Health" sub="Component checks">
            {(health?.checks || []).map((c) => (
              <div key={c.name} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                <span style={{ fontWeight: 600, fontSize: 12 }}>{c.name}</span>
                <Badge type={c.status === 'up' ? 'buy' : 'sell'}>{c.status}</Badge>
              </div>
            ))}
            <div className="muted" style={{ marginTop: 8, fontSize: 11 }}>Uptime: {Math.round(health?.uptime / 60)} min</div>
          </Panel>
          <Panel title="Request Metrics" sub="app.requests">
            <Meter label="Request Rate" value={metrics?.length || 0} pct={Math.min((metrics?.length || 0) * 3, 100)} color="var(--accent)" />
            <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
              {metrics?.map((m) => <span key={m.id} style={{ marginRight: 4 }}>{m.value}</span>)}
            </div>
          </Panel>
          <Panel title="Scheduler Jobs">
            {(scheduler || []).map((j) => (
              <div key={j.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                <div>
                  <span style={{ fontWeight: 600, fontSize: 12 }}>{j.id}</span>
                  <div className="muted" style={{ fontSize: 10 }}>Runs: {j.runs}</div>
                </div>
                <Badge type={j.enabled ? 'buy' : 'neutral'}>{j.enabled ? 'active' : 'paused'}</Badge>
              </div>
            ))}
          </Panel>
          <Panel title="Queues & Workers">
            <div className="kv">
              <dt>Active Workers</dt><dd>{workers?.active} / {workers?.size}</dd>
              <dt>Total Tasks</dt><dd>{workers?.stats?.total}</dd>
              <dt>Failed</dt><dd className="red">{workers?.stats?.failed}</dd>
            </div>
            {(queues?.queues || []).map((q) => (
              <div key={q.name} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                <span style={{ fontSize: 12 }}>{q.name}</span>
                <span className="muted">{q.tasks} queued · {q.active} active</span>
              </div>
            ))}
          </Panel>
        </div>
      )}

      {tab === 'admin' && (
        <div className="grid grid-2">
          <Panel title="System Dashboard" sub="Enterprise overview">
            <div className="kv">
              <dt>Status</dt><dd className="green">{admin?.health?.status}</dd>
              <dt>Uptime</dt><dd>{Math.round(admin?.health?.uptime || 0)}s</dd>
              <dt>Pipelines</dt><dd>{admin?.pipelines?.length}</dd>
              <dt>Integrations</dt><dd>{admin?.integrations?.length}</dd>
              <dt>DB Collections</dt><dd>{admin?.db?.collections}</dd>
              <dt>Heap Memory</dt><dd>{admin?.db?.memory}</dd>
            </div>
          </Panel>
          <Panel title="System Configuration" sub="Tunable parameters">
            {(config || []).map((c) => (
              <div key={c.key} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                <span style={{ fontSize: 12 }}>{c.key}</span>
                <Badge type="info">{String(c.value)}</Badge>
              </div>
            ))}
          </Panel>
        </div>
      )}

      {tab === 'security' && (
        <div className="grid grid-2">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Panel title="Security Dashboard" sub="Enterprise security posture">
              <div className="kv">
                <dt>API Keys</dt><dd>{security?.apiKeys}</dd>
                <dt>Active Sessions</dt><dd>{security?.activeSessions}</dd>
                <dt>Audit Events</dt><dd>{security?.auditEvents}</dd>
                <dt>Encryption</dt><dd>{security?.encryption}</dd>
                <dt>Password Policy</dt><dd>{security?.passwordPolicy}</dd>
                <dt>MFA</dt><dd>{security?.mfaEnabled ? 'Enabled' : 'Not configured'}</dd>
              </div>
            </Panel>
            <Panel title="API Keys" sub="RBAC-scoped credentials">
              {(keys || []).map((k) => (
                <div key={k.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                  <span style={{ fontSize: 12, fontWeight: 600 }}>{k.name}</span>
                  <Badge type="info">{k.role}</Badge>
                </div>
              ))}
            </Panel>
          </div>
          <Panel title="Audit Logs" sub="Activity trail">
            {(audit || []).map((l, i) => (
              <div key={i} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0' }}>
                <span style={{ fontSize: 12 }}>{l.action}</span>
                <span className="muted" style={{ fontSize: 10.5 }}>{new Date(l.timestamp).toLocaleString()}</span>
              </div>
            ))}
          </Panel>
        </div>
      )}

      {tab === 'users' && (
        <div className="grid grid-2">
          <Panel title="Users & Roles" sub="RBAC management">
            <table>
              <thead><tr><th>Username</th><th>Email</th><th>Role</th><th>Status</th></tr></thead>
              <tbody>
                {(users || []).map((u) => (
                  <tr key={u.id}>
                    <td style={{ fontWeight: 600 }}>{u.username}</td>
                    <td className="muted">{u.email}</td>
                    <td><Badge type={u.role === 'admin' ? 'high' : u.role === 'trader' ? 'buy' : 'info'}>{u.role}</Badge></td>
                    <td><Badge type={u.active ? 'buy' : 'neutral'}>{u.active ? 'Active' : 'Disabled'}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
          <Panel title="Organizations & Teams" sub="Enterprise structure">
            {(orgs || []).map((o) => (
              <div key={o.id} className="list-item">
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontWeight: 600 }}>{o.name}</span>
                  <Badge type="info">{o.plan}</Badge>
                </div>
                <div className="muted" style={{ fontSize: 11 }}>{o.teams.join(' · ')} · {o.members} members</div>
              </div>
            ))}
          </Panel>
        </div>
      )}

      {tab === 'integrations' && (
        <Panel title="Integration Hub" sub="Broker, notification & storage connectors">
          <table>
            <thead><tr><th>Integration</th><th>Type</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {(integrations || []).map((i) => (
                <tr key={i.id}>
                  <td style={{ fontWeight: 600 }}>{i.name}</td>
                  <td><Badge type="info">{i.type}</Badge></td>
                  <td><Badge type={i.status === 'connected' ? 'buy' : i.status === 'disabled' ? 'neutral' : 'info'}>{i.status}</Badge></td>
                  <td><button className="btn btn-sm" onClick={() => testIntegration(i.id)}>Test</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}

      {tab === 'assets' && (
        <Panel title="Multi-Asset Expansion" sub="9 asset classes · all supported instruments">
          <table>
            <thead><tr><th>Symbol</th><th>Name</th><th>Class</th><th>Bid</th><th>Ask</th><th>Change 24h</th></tr></thead>
            <tbody>
              {(assets?.instruments || []).map((a) => (
                <tr key={a.symbol}>
                  <td style={{ fontWeight: 700 }}>{a.symbol}</td>
                  <td>{a.name}</td>
                  <td><Badge type="info">{a.assetClass}</Badge></td>
                  <td className="green">{a.bid}</td>
                  <td className="red">{a.ask}</td>
                  <td className={a.change24h >= 0 ? 'green' : 'red'}>{a.change24h}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="muted" style={{ marginTop: 8, fontSize: 11 }}>
            Asset classes: {assets?.classes?.map((c) => `${c.label} (${c.instruments.length})`).join(' · ')}
          </div>
        </Panel>
      )}
    </div>
  );
}
