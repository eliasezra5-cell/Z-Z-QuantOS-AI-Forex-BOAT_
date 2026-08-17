import { useState } from 'react';
import { useFetch, post } from '../api.js';
import { Panel, Badge, Loading, StatCard, Meter, KeyValue } from '../components/ui.jsx';
import { fmtMoney, fmtTime } from '../api.js';

export default function CloudInfrastructure() {
  const [tab, setTab] = useState('overview');
  const { data: overview, loading, refresh } = useFetch('/cloud/overview');
  const { data: backups, refresh: refreshBackups } = useFetch('/cloud/backups');
  const { data: restores } = useFetch('/cloud/restores');

  const act = async (fn) => { await fn(); refresh(); refreshBackups(); };

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Cloud Infrastructure</div>
        <div className="tabs">
          {[['overview', 'Overview'], ['providers', 'Providers'], ['storage', 'Storage & Backups'], ['cdn', 'CDN & Scaling']].map(([id, label]) => (
            <div key={id} className={`tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>{label}</div>
          ))}
        </div>
      </div>

      {loading && <Loading />}

      {tab === 'overview' && overview && (
        <div>
          <div className="grid grid-4">
            <StatCard label="Cloud Providers" value={overview.summary.providers} sub={`${overview.summary.healthy} healthy · ${overview.summary.degraded} degraded`} icon="☁" />
            <StatCard label="Total Instances" value={overview.summary.totalInstances} sub={`across ${overview.summary.providers} clouds`} icon="▣" />
            <StatCard label="Monthly Cost" value={fmtMoney(overview.summary.totalCost)} sub="all providers" icon="₿" color="green" />
            <StatCard label="Object Storage" value={`${overview.summary.objectStorageGb} GB`} sub={`${overview.summary.totalBackups} backups`} icon="◫" />
          </div>
          <Panel title="Provider Fleet" sub="Multi-cloud topology">
            <table>
              <thead><tr><th>Provider</th><th>Status</th><th>Instances</th><th>Latency</th><th>CDN</th><th>Est. Cost/mo</th></tr></thead>
              <tbody>
                {overview.providers.map((p) => (
                  <tr key={p.id}>
                    <td style={{ fontWeight: 700 }}>{p.name}</td>
                    <td><Badge type={p.status === 'healthy' ? 'buy' : 'sell'}>{p.status}</Badge></td>
                    <td>{p.instances}</td>
                    <td>{p.latency}ms</td>
                    <td>{p.cdn?.edgeLocations} edges · {p.cdn?.cacheHitRate}% hit</td>
                    <td className="green">{fmtMoney(p.cost?.monthly)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>
      )}

      {tab === 'providers' && overview && (
        <div className="grid grid-2">
          {overview.providers.map((p) => (
            <Panel key={p.id} title={p.name} sub={`${p.regions.length} regions · ${p.services.length} services`}>
              <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                <Badge type={p.status === 'healthy' ? 'buy' : 'sell'}>{p.status}</Badge>
                <Badge type="info">{p.instances} instances</Badge>
              </div>
              <div className="kv">
                <dt>Regions</dt><dd>{p.regions.join(', ')}</dd>
                <dt>Services</dt><dd>{p.services.join(', ')}</dd>
                <dt>Base cost / instance</dt><dd>${p.costPerInstance}/hr</dd>
                <dt>Latency</dt><dd>{p.latency}ms</dd>
                <dt>Auto-scaling</dt><dd>{p.autoScaling.enabled ? `on · ${p.autoScaling.min}-${p.autoScaling.max} · ${p.autoScaling.targetCpu}% CPU` : 'off'}</dd>
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                <button className="btn btn-sm" onClick={() => act(() => post(`/cloud/providers/${p.provider}/scale`, { delta: 1 }))}>Scale +1</button>
                <button className="btn btn-sm" onClick={() => act(() => post(`/cloud/providers/${p.provider}/scale`, { delta: -1 }))}>Scale -1</button>
                <button className="btn btn-sm btn-danger" onClick={() => act(() => post(`/cloud/providers/${p.provider}/failure`, {}))}>Simulate Failure</button>
              </div>
            </Panel>
          ))}
        </div>
      )}

      {tab === 'storage' && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <button className="btn btn-sm" onClick={() => act(() => post('/cloud/backups', {}))}>Create Backup</button>
          </div>
          <Panel title="Object Storage" sub="Encrypted buckets per provider">
            <table>
              <thead><tr><th>Bucket</th><th>Provider</th><th>Region</th><th>Size</th><th>Objects</th><th>Tier</th><th>Encrypted</th></tr></thead>
              <tbody>
                {overview?.providers?.flatMap((p) => (p.storage || []).map((b) => ({ ...b, provider: p.name }))).map((b) => (
                  <tr key={b.id}>
                    <td style={{ fontWeight: 600 }}>{b.name}</td>
                    <td>{b.provider}</td>
                    <td className="muted">{b.region}</td>
                    <td>{b.sizeGb} GB</td>
                    <td>{b.objects.toLocaleString()}</td>
                    <td><Badge type={b.tier === 'hot' ? 'buy' : 'info'}>{b.tier}</Badge></td>
                    <td><Badge type={b.encrypted ? 'buy' : 'sell'}>{b.encrypted ? 'Yes' : 'No'}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
          <Panel title="Backups & Restores" sub="Snapshot lifecycle">
            <table>
              <thead><tr><th>Backup</th><th>Provider</th><th>Status</th><th>Size</th><th>Created</th><th>Retention</th><th></th></tr></thead>
              <tbody>
                {(backups || []).map((b) => (
                  <tr key={b.id}>
                    <td style={{ fontWeight: 600 }}>{b.name}</td>
                    <td>{b.provider}</td>
                    <td><Badge type={b.status === 'completed' ? 'buy' : b.status === 'running' ? 'info' : 'sell'}>{b.status}</Badge></td>
                    <td>{b.sizeGb} GB</td>
                    <td className="muted">{fmtTime(b.createdAt)}</td>
                    <td>{b.retentionDays}d</td>
                    <td><button className="btn btn-sm" disabled={b.status !== 'completed'} onClick={() => act(() => post(`/cloud/backups/${b.id}/restore`, {}))}>Restore</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(restores || []).length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div className="section-title" style={{ fontSize: 13 }}>Recent Restores</div>
                {restores.map((r) => (
                  <div key={r.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                    <span style={{ fontSize: 12 }}>backup {r.backupId.slice(0, 8)}</span>
                    <Badge type={r.status === 'completed' ? 'buy' : 'info'}>{r.status}</Badge>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      )}

      {tab === 'cdn' && overview && (
        <div className="grid grid-2">
          {overview.providers.map((p) => (
            <Panel key={p.id} title={`${p.name} · CDN & Load Balancers`} sub="Edge delivery">
              <Meter label="Cache Hit Rate" value={`${p.cdn?.cacheHitRate}%`} pct={p.cdn?.cacheHitRate} color="var(--accent)" />
              <Meter label="Bandwidth" value={`${p.cdn?.bandwidth} GB/h`} pct={Math.min(p.cdn?.bandwidth, 100)} color="var(--blue)" />
              <div className="kv" style={{ marginTop: 8 }}>
                <dt>Edge Locations</dt><dd>{p.cdn?.edgeLocations}</dd>
                <dt>Load Balancers</dt><dd>{p.loadBalancers?.length}</dd>
              </div>
              {p.loadBalancers?.map((lb) => (
                <div key={lb.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                  <span style={{ fontSize: 12 }}>{lb.name} · {lb.region}</span>
                  <span className="muted">{lb.healthyNodes}/{lb.nodes} healthy · {lb.requestsPerSec} rps</span>
                </div>
              ))}
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}
