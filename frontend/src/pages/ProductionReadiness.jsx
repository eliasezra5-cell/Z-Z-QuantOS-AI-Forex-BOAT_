import { useState } from 'react';
import { useFetch, post } from '../api.js';
import { Panel, Badge, Loading, StatCard, Meter } from '../components/ui.jsx';
import { fmtTime } from '../api.js';

export default function ProductionReadiness() {
  const [tab, setTab] = useState('readiness');
  const { data: overview, loading, refresh } = useFetch('/production/overview');
  const { data: tests, refresh: refreshTests } = useFetch('/production/tests');
  const { data: scans, refresh: refreshScans } = useFetch('/production/security-scans');
  const { data: perf, refresh: refreshPerf } = useFetch('/production/performance');
  const { data: audits, refresh: refreshAudits } = useFetch('/production/audits');

  const act = async (fn) => { await fn(); refresh(); refreshTests(); refreshScans(); refreshPerf(); refreshAudits(); };

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Production Readiness</div>
        <div className="tabs">
          {[['readiness', 'Go-Live'], ['performance', 'Performance'], ['security', 'Security'], ['ha', 'HA & DR'], ['audit', 'Audits']].map(([id, label]) => (
            <div key={id} className={`tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>{label}</div>
          ))}
        </div>
      </div>

      {loading && <Loading />}

      {tab === 'readiness' && overview && (
        <div>
          <div className="grid grid-4">
            <StatCard label="Checklist" value={`${overview.goLiveStatus.checklistPct}%`} sub={`${overview.checklist.summary.completed}/${overview.checklist.summary.total} done`} icon="✓" color="green" />
            <StatCard label="Last Audit" value={overview.lastAudit ? `${overview.lastAudit.overallScore}%` : 'None'} sub={overview.lastAudit ? overview.lastAudit.status : 'not run'} icon="▦" />
            <StatCard label="Go-Live" value={overview.goLiveStatus.ready ? 'READY' : 'PENDING'} sub="checklist + audit required" icon="▲" color={overview.goLiveStatus.ready ? 'green' : 'red'} />
            <StatCard label="HA Overall" value={overview.highAvailability.summary.overall} sub="multi-region" icon="⇄" />
          </div>
          <Panel title="Go-Live Checklist" sub="16 enterprise readiness items">
            {(overview.checklist.items || []).map((item) => (
              <div key={item.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0' }}>
                <div style={{ flex: 1 }}>
                  <span style={{ fontWeight: 600, fontSize: 12 }}>{item.item}</span>
                  <div className="muted" style={{ fontSize: 10.5 }}>
                    {item.category}{item.notes ? ` · ${item.notes}` : ''}{item.required ? ' · required' : ''}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <Badge type={item.completed ? 'buy' : 'neutral'}>{item.completed ? 'Done' : 'Pending'}</Badge>
                  <button className="btn btn-sm" onClick={() => act(() => post(`/production/checklist/${item.id}`, { completed: !item.completed }))}>Toggle</button>
                </div>
              </div>
            ))}
          </Panel>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn btn-sm" onClick={() => act(() => post('/production/stress-test', { concurrency: 20, durationSec: 3 }))}>Run Stress Test</button>
            <button className="btn btn-sm" onClick={() => act(() => post('/production/load-test', { targetRps: 100, durationSec: 3 }))}>Run Load Test</button>
            <button className="btn btn-sm" onClick={() => act(() => post('/production/security-scan', {}))}>Run Security Scan</button>
            <button className="btn btn-sm btn-danger" onClick={() => act(() => post('/production/failover', { target: 'backend' }))}>Trigger Failover</button>
            <button className="btn btn-sm" onClick={() => act(() => post('/production/dr-drill', {}))}>Run DR Drill</button>
            <button className="btn btn-sm" onClick={() => act(() => post('/production/audit', {}))}>Run Audit</button>
          </div>
        </div>
      )}

      {tab === 'performance' && (
        <div>
          <Panel title="Stress & Load Test Results" sub="Latency percentiles across recent runs">
            <table>
              <thead><tr><th>Type</th><th>Requests</th><th>RPS</th><th>p50</th><th>p95</th><th>p99</th><th>Errors</th><th>Result</th></tr></thead>
              <tbody>
                {[...(tests?.stress || []), ...(tests?.load || [])].slice(0, 10).map((t) => (
                  <tr key={t.id}>
                    <td><Badge type="info">{t.type}</Badge></td>
                    <td>{t.requests}</td>
                    <td>{t.rps || t.achievedRps || '—'}</td>
                    <td>{t.latency?.p50 ?? '—'}</td>
                    <td>{t.latency?.p95 ?? t.p95 ?? '—'}</td>
                    <td>{t.latency?.p99 ?? '—'}</td>
                    <td className="red">{t.errors}</td>
                    <td><Badge type={t.passed ? 'buy' : 'sell'}>{t.passed ? 'PASS' : 'FAIL'}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
          <Panel title="Performance Recommendations" sub="Optimization backlog">
            {(perf || []).map((o) => (
              <div key={o.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0' }}>
                <div style={{ flex: 1 }}>
                  <span style={{ fontWeight: 600, fontSize: 12 }}>{o.area}</span>
                  <div className="muted" style={{ fontSize: 11 }}>{o.recommendation}</div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <Badge type={o.impact === 'high' ? 'high' : 'info'}>{o.impact}</Badge>
                  <Badge type={o.applied ? 'buy' : 'neutral'}>{o.applied ? 'Applied' : 'Pending'}</Badge>
                  {!o.applied && <button className="btn btn-sm" onClick={() => act(() => post(`/production/performance/${o.id}/apply`, {}))}>Apply</button>}
                </div>
              </div>
            ))}
          </Panel>
        </div>
      )}

      {tab === 'security' && (
        <Panel title="Security Hardening Scans" sub="10-point enterprise security posture">
          {(scans || []).map((s) => (
            <div key={s.id} className="list-item" style={{ padding: '8px 0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>Scan · {fmtTime(s.startedAt)}</span>
                <div>
                  <Badge type={s.status === 'completed' ? 'buy' : 'info'}>{s.status}</Badge>
                  <Badge type="high" style={{ marginLeft: 6 }}>{s.summary?.score}%</Badge>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                {(s.checks || []).map((c) => (
                  <Badge key={c.id} type={c.passed ? 'buy' : 'sell'}>{c.check}</Badge>
                ))}
              </div>
            </div>
          ))}
        </Panel>
      )}

      {tab === 'ha' && overview && (
        <div className="grid grid-2">
          <Panel title="High Availability Topology" sub="Active-passive + replicated DB">
            <KeyValue rows={[
              ['Backend', `${overview.highAvailability.backend.replicas} replicas · ${overview.highAvailability.backend.zoneSpread} zones`],
              ['Frontend', `${overview.highAvailability.frontend.replicas} replicas · active-active`],
              ['Database', `${overview.highAvailability.database.mode} · ${overview.highAvailability.database.replicas} replicas`],
              ['MT5', `${overview.highAvailability.mt5.mode} · broker failover ${overview.highAvailability.mt5.brokerFailover ? 'on' : 'off'}`],
              ['Failover RTO', `${overview.highAvailability.backend.failover.rtoSec}s`],
              ['Failover RPO', `${overview.highAvailability.backend.failover.rpoSec}s`]
            ]} />
            <div className="muted" style={{ fontSize: 11, marginTop: 8 }}>Last failover: {overview.highAvailability.summary.lastFailover ? fmtTime(overview.highAvailability.summary.lastFailover.at) : 'none'}</div>
          </Panel>
          <Panel title="Disaster Recovery Plan" sub={`RTO ${overview.disasterRecovery.rto}s · RPO ${overview.disasterRecovery.rpo}s`}>
            <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>{overview.disasterRecovery.strategy}</div>
            {(overview.disasterRecovery.backups || []).map((b) => (
              <div key={b.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0' }}>
                <span style={{ fontSize: 12, fontWeight: 600 }}>{b.resource}</span>
                <span className="muted" style={{ fontSize: 11 }}>{b.frequency} · {b.retention} · {b.region}</span>
              </div>
            ))}
            <div style={{ marginTop: 8 }}>
              <div className="section-title" style={{ fontSize: 13 }}>Runbook</div>
              {(overview.disasterRecovery.runbook || []).map((s, i) => <div key={i} className="muted" style={{ fontSize: 11 }}>{s}</div>)}
            </div>
          </Panel>
        </div>
      )}

      {tab === 'audit' && (
        <Panel title="Production Audits" sub="Category scoring per audit run">
          {(audits || []).map((a) => (
            <div key={a.id} className="list-item" style={{ padding: '8px 0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>Audit · {fmtTime(a.generatedAt)}</span>
                <Badge type={a.status === 'pass' ? 'buy' : 'sell'}>{a.status} · {a.overallScore}%</Badge>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {(a.categories || []).map((c) => (
                  <Badge key={c.category} type={c.score >= 90 ? 'buy' : c.score >= 80 ? 'info' : 'sell'}>{c.category}: {c.score}</Badge>
                ))}
              </div>
              {(a.recommendedActions || []).map((r, i) => (
                <div key={i} className="muted" style={{ fontSize: 11, marginTop: 4 }}>• {r}</div>
              ))}
            </div>
          ))}
        </Panel>
      )}
    </div>
  );
}
