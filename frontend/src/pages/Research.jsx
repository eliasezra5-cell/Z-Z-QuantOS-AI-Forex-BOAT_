import { useState } from 'react';
import { useFetch, post } from '../api.js';
import { Panel, Badge, Loading, StatCard } from '../components/ui.jsx';
import { Fragment } from 'react';
import { useSymbol } from '../symbols.jsx';

export default function Research() {
  const { symbol } = useSymbol();
  const { data: experiments, refresh: refreshExp } = useFetch('/research/experiments');
  const { data: features } = useFetch('/features');
  const { data: pipelines, refresh: refreshPipe } = useFetch('/pipelines');
  const { data: pipelineStats } = useFetch('/pipelines/stats');
  const { data: featureData } = useFetch(`/features/compute/${symbol}`, [symbol]);
  const [nb, setNb] = useState(null);

  const createExp = async () => {
    await post('/research/experiments', { name: `Experiment ${experiments?.length + 1}`, description: 'Strategy parameter exploration', status: 'running' });
    refreshExp();
  };

  const runPipe = async (id) => {
    await post(`/pipelines/${id}/run`, {});
    refreshPipe();
  };

  const runNb = async () => {
    const res = await post('/research/notebooks/run', {
      id: `nb-${Date.now()}`,
      cells: [
        { id: 'c1', language: 'javascript', code: `// Analyze ${symbol} H1 momentum` },
        { id: 'c2', language: 'strategy', code: 'trend-follow' },
        { id: 'c3', language: 'javascript', code: '// Evaluate risk per trade' }
      ]
    });
    setNb(res);
  };

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Research Laboratory & Data Pipelines</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn" onClick={createExp}>New Experiment</button>
          <button className="btn btn-primary" onClick={runNb}>Run Notebook</button>
        </div>
      </div>

      <div className="grid grid-4">
        <StatCard label="Feature Store" value={features?.length} sub="Registered features" />
        <StatCard label="Pipelines" value={pipelineStats?.total} sub={`${pipelineStats?.completed} completed`} />
        <StatCard label="Experiments" value={experiments?.length} sub="Research runs" />
        <StatCard label="Notebook Cells" value={nb ? nb.cells.length : 0} sub={nb ? 'Executed' : 'Sandbox ready'} />
      </div>

      <div style={{ height: 16 }} />
      <div className="grid grid-2">
        <Panel title="Feature Store" sub="Versioned, reusable AI features">
          <table>
            <thead><tr><th>Feature</th><th>Category</th><th>Type</th><th>Version</th><th>Online</th></tr></thead>
            <tbody>
              {(features || []).map((f) => (
                <tr key={f.name}>
                  <td style={{ fontWeight: 600 }}>{f.name}</td>
                  <td><Badge type="info">{f.category}</Badge></td>
                  <td className="muted">{f.type}</td>
                  <td>v{f.version}</td>
                  <td>{f.online ? '✓' : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Panel title="Data Pipelines" sub="ETL · Streaming · Batch">
            {(pipelines || []).map((p) => (
              <div key={p.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 12 }}>{p.name}</div>
                  <div className="muted" style={{ fontSize: 10 }}>{p.type} · {p.source} → {p.target}</div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <Badge type={p.status === 'completed' ? 'buy' : p.status === 'running' ? 'high' : 'neutral'}>{p.status}</Badge>
                  <button className="btn btn-sm" onClick={() => runPipe(p.id)} disabled={!p.enabled}>Run</button>
                </div>
              </div>
            ))}
          </Panel>
          <Panel title="Feature Computation" sub={`Live features for ${symbol}`}>
            <div className="kv">
              {Object.entries(featureData?.features || {}).map(([k, v]) => (
                <Fragment key={k}>
                  <dt>{k}</dt><dd>{typeof v === 'number' ? v.toFixed(3) : v}</dd>
                </Fragment>
              ))}
            </div>
          </Panel>
        </div>
      </div>

      <div style={{ height: 16 }} />
      <div className="grid grid-2">
        <Panel title="Experiments" sub="Research runs">
          {(experiments || []).map((e) => (
            <div key={e.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontWeight: 600 }}>{e.name}</div>
                <div className="muted" style={{ fontSize: 10.5 }}>{e.description} · {new Date(e.createdAt).toLocaleString()}</div>
              </div>
              <Badge type={e.status === 'running' ? 'high' : 'info'}>{e.status}</Badge>
            </div>
          ))}
        </Panel>
        <Panel title="Notebook Output" sub="Sandbox execution results">
          {nb ? nb.cells.map((c) => (
            <div key={c.id} className="list-item">
              <div className="muted" style={{ fontSize: 10 }}>[{c.language}] {c.id}</div>
              <div style={{ fontSize: 11.5 }}>{c.output}</div>
            </div>
          )) : <div className="empty">Run a notebook to see sandbox output</div>}
        </Panel>
      </div>
    </div>
  );
}
