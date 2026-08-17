import { useState } from 'react';
import { useFetch, post } from '../api.js';
import { Panel, Badge, Loading, StatCard, Meter } from '../components/ui.jsx';
import { fmtTime } from '../api.js';

export default function DevOps() {
  const [tab, setTab] = useState('pipelines');
  const { data: overview, loading, refresh } = useFetch('/devops/overview');
  const { data: k8s, refresh: refreshK8s } = useFetch('/devops/k8s');

  const act = async (fn) => { await fn(); refresh(); refreshK8s(); };

  return (
    <div>
      <div className="page-head">
        <div className="section-title">DevOps & CI/CD</div>
        <div className="tabs">
          {[['pipelines', 'Pipelines'], ['releases', 'Releases'], ['k8s', 'Kubernetes'], ['deployments', 'Deployments']].map(([id, label]) => (
            <div key={id} className={`tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>{label}</div>
          ))}
        </div>
      </div>

      {loading && <Loading />}

      {tab === 'pipelines' && overview && (
        <div>
          <div className="grid grid-4">
            <StatCard label="CI Pipelines" value={overview.summary.pipelines} sub={`${overview.summary.enabled} enabled`} icon="⇶" />
            <StatCard label="Total Runs" value={overview.summary.totalRuns} sub="all time" icon="▸" />
            <StatCard label="Success Rate" value={`${overview.summary.successRate}%`} sub="recent runs" icon="✓" color="green" />
            <StatCard label="Avg Duration" value={`${overview.summary.avgRunDurationSec}s`} sub="per pipeline run" icon="⏱" />
          </div>
          <Panel title="Pipeline Registry" sub="GitHub Actions · GitLab CI · Docker · K8s · Helm">
            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <button className="btn btn-sm" onClick={() => act(() => post('/devops/pipelines/run-all', {}))}>Run All Pipelines</button>
            </div>
            <table>
              <thead><tr><th>Pipeline</th><th>Platform</th><th>Status</th><th>Workflows</th><th>Last Run</th><th></th></tr></thead>
              <tbody>
                {overview.pipelines.map((p) => (
                  <tr key={p.id}>
                    <td style={{ fontWeight: 700 }}>{p.name}</td>
                    <td><Badge type="info">{p.platform}</Badge></td>
                    <td><Badge type={p.status === 'idle' ? 'neutral' : p.status === 'running' ? 'info' : p.status === 'success' ? 'buy' : 'sell'}>{p.status}</Badge></td>
                    <td className="muted">{(p.workflows || []).join(', ')}</td>
                    <td className="muted">{p.lastRun ? fmtTime(p.lastRun) : 'never'}</td>
                    <td style={{ display: 'flex', gap: 6 }}>
                      <button className="btn btn-sm" onClick={() => act(() => post(`/devops/pipelines/${p.id}/run`, {}))}>Run</button>
                      <button className="btn btn-sm" onClick={() => act(() => post(`/devops/pipelines/${p.id}/toggle`, { enabled: !p.enabled }))}>{p.enabled ? 'Disable' : 'Enable'}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
          <Panel title="Recent Pipeline Runs" sub="Async execution logs">
            {(overview.runs || []).map((r) => (
              <div key={r.id} className="list-item" style={{ padding: '8px 0' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontWeight: 600, fontSize: 13 }}>{r.pipelineName}</span>
                  <Badge type={r.status === 'success' ? 'buy' : r.status === 'running' ? 'info' : r.status === 'failed' ? 'sell' : 'neutral'}>{r.status}</Badge>
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                  {(r.steps || []).map((s, i) => (
                    <Badge key={i} type={s.status === 'success' ? 'buy' : s.status === 'failed' ? 'sell' : s.status === 'running' ? 'info' : 'neutral'}>{s.name}: {s.status}{s.durationSec ? ` · ${s.durationSec}s` : ''}</Badge>
                  ))}
                </div>
                <div className="muted" style={{ fontSize: 10.5, marginTop: 6 }}>{fmtTime(r.startedAt)}</div>
              </div>
            ))}
          </Panel>
        </div>
      )}

      {tab === 'releases' && overview && (
        <div>
          <Panel title="Release Management" sub="Semantic versioning · major / minor / patch / rc / hotfix">
            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              {[['patch', 'Patch'], ['minor', 'Minor'], ['major', 'Major'], ['rc', 'RC'], ['hotfix', 'Hotfix']].map(([type, label]) => (
                <button key={type} className="btn btn-sm" onClick={() => act(() => post('/devops/releases', { type, notes: `${label} release` }))}>New {label}</button>
              ))}
            </div>
            <table>
              <thead><tr><th>Version</th><th>Type</th><th>Branch</th><th>Status</th><th>Artifacts</th><th>Created</th></tr></thead>
              <tbody>
                {(overview.releases || []).map((r) => (
                  <tr key={r.id}>
                    <td style={{ fontWeight: 700 }}>{r.tag}</td>
                    <td><Badge type="info">{r.type}</Badge></td>
                    <td className="muted">{r.branch}</td>
                    <td><Badge type={r.status === 'released' ? 'buy' : 'neutral'}>{r.status}</Badge></td>
                    <td className="muted">{(r.artifacts || []).join(', ')}</td>
                    <td className="muted">{fmtTime(r.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>
      )}

      {tab === 'k8s' && k8s && (
        <div className="grid grid-2">
          {(k8s.clusters || []).map((c) => (
            <Panel key={c.name} title={c.name} sub={`${c.version} · ${c.region}`}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <Badge type={c.status === 'ready' ? 'buy' : 'sell'}>{c.status}</Badge>
                <span className="muted">{c.nodes} nodes · {c.pods} pods</span>
              </div>
              <Meter label="CPU Utilization" value={`${c.cpuUtilization}%`} pct={c.cpuUtilization} color={c.cpuUtilization > 80 ? 'var(--red)' : 'var(--accent)'} />
              <Meter label="Memory Utilization" value={`${c.memoryUtilization}%`} pct={c.memoryUtilization} color="var(--blue)" />
            </Panel>
          ))}
          <Panel title="Helm Charts" sub={`Namespaces: ${(k8s.namespaces || []).join(', ')}`}>
            {k8s.helmSimulated && (
              <div style={{ marginBottom: 8 }}>
                <Badge type="warning">Simulated data</Badge>
                <span className="muted" style={{ fontSize: 10.5, marginLeft: 6 }}>No live Helm/Kubernetes cluster — demo values shown</span>
              </div>
            )}
            {(k8s.helmCharts || []).map((h) => (
              <div key={h.name} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                <div>
                  <span style={{ fontWeight: 600, fontSize: 12 }}>{h.name}</span>
                  <div className="muted" style={{ fontSize: 10 }}>v{h.version} · app v{h.appVersion} · rev {h.revision}</div>
                </div>
                <Badge type={h.status === 'deployed' ? 'buy' : 'info'}>{h.status}</Badge>
              </div>
            ))}
          </Panel>
        </div>
      )}

      {tab === 'deployments' && overview && (
        <Panel title="Deployment Log" sub="Recent rollout history">
          <table>
            <thead><tr><th>App</th><th>Environment</th><th>Version</th><th>Status</th><th>Deployed</th></tr></thead>
            <tbody>
              {(overview.deployments || []).map((d) => (
                <tr key={d.id}>
                  <td style={{ fontWeight: 600 }}>{d.app}</td>
                  <td><Badge type={d.environment === 'production' ? 'high' : 'info'}>{d.environment}</Badge></td>
                  <td>{d.version}</td>
                  <td><Badge type={d.status === 'live' ? 'buy' : d.status === 'rolling' ? 'info' : 'sell'}>{d.status}</Badge></td>
                  <td className="muted">{fmtTime(d.deployedAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </div>
  );
}
