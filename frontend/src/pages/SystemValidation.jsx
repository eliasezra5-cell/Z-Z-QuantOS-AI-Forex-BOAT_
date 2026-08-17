import { useState } from 'react';
import { useFetch, post } from '../api.js';
import { Panel, Badge, Loading, StatCard } from '../components/ui.jsx';
import { fmtTime } from '../api.js';

export default function SystemValidation() {
  const [running, setRunning] = useState(null);
  const { data: suites } = useFetch('/validation/suites');
  const { data: certification, refresh: refreshCert } = useFetch('/validation/certification');
  const { data: runs, refresh: refreshRuns } = useFetch('/validation/runs');

  const runSuite = async (id) => {
    setRunning(id);
    try {
      await post(`/validation/run/${id}`, {});
      refreshRuns();
      refreshCert();
    } finally {
      setRunning(null);
    }
  };

  const runAll = async () => {
    setRunning('all');
    try {
      await post('/validation/run-all', {});
      refreshRuns();
      refreshCert();
    } finally {
      setRunning(null);
    }
  };

  const statusFor = (id) => (runs || []).find((r) => r.suiteId === id);

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Enterprise System Validation</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-sm" disabled={running} onClick={runAll}>
            {running === 'all' ? 'Running all suites...' : 'Run All 9 Suites'}
          </button>
        </div>
      </div>

      {certification && (
        <div className="grid grid-4">
          <StatCard label="Certification" value={certification.status === 'certified' ? 'CERTIFIED' : 'PENDING'} sub={certification.certifiedAt ? fmtTime(certification.certifiedAt) : 'not yet certified'} icon="◆" color={certification.status === 'certified' ? 'green' : 'red'} />
          <StatCard label="Overall Score" value={`${certification.score}%`} sub="latest run per suite" icon="◔" color="green" />
          <StatCard label="Suites Passing" value={`${certification.suitesPassed}/${certification.suitesTotal}`} sub={`requires ${certification.required}`} icon="✓" />
          <StatCard label="Required Score" value="90%" sub="for production certification" icon="▲" />
        </div>
      )}

      <Panel title="Validation Suites" sub="9 enterprise-grade test suites">
        <div className="grid grid-2">
          {(suites || []).map((s) => {
            const run = statusFor(s.id);
            return (
              <div key={s.id} className="list-item" style={{ padding: '10px 0' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <span style={{ fontWeight: 700, fontSize: 13 }}>{s.name}</span>
                    <div className="muted" style={{ fontSize: 11 }}>{s.description}</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {run && (
                      <span>
                        <Badge type={run.passed ? 'buy' : 'sell'}>{run.passed ? 'PASS' : 'FAIL'}</Badge>
                        <span className="muted" style={{ fontSize: 11, marginLeft: 4 }}>{run.score}%</span>
                      </span>
                    )}
                    <button className="btn btn-sm" disabled={running === s.id} onClick={() => runSuite(s.id)}>
                      {running === s.id ? 'Running...' : 'Run'}
                    </button>
                  </div>
                </div>
                {run && run.checks && (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                    {run.checks.slice(0, 8).map((c, i) => (
                      <Badge key={i} type={c.passed ? 'buy' : 'sell'}>{c.check}</Badge>
                    ))}
                    {run.checks.length > 8 && <span className="muted" style={{ fontSize: 11 }}>+{run.checks.length - 8} more</span>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Panel>

      <Panel title="Recent Validation Runs" sub="Full run history">
        <table>
          <thead><tr><th>Suite</th><th>Status</th><th>Score</th><th>Duration</th><th>Completed</th></tr></thead>
          <tbody>
            {(runs || []).slice(0, 25).map((r) => (
              <tr key={r.id}>
                <td style={{ fontWeight: 600 }}>{r.suiteName}</td>
                <td><Badge type={r.passed ? 'buy' : 'sell'}>{r.status}</Badge></td>
                <td>{r.score}%</td>
                <td className="muted">{r.durationMs}ms</td>
                <td className="muted">{fmtTime(r.completedAt || r.startedAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
