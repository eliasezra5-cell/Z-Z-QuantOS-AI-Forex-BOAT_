import { useState } from 'react';
import { useFetch, post } from '../api.js';
import { Panel, Badge, Loading, StatCard } from '../components/ui.jsx';

export default function Reports() {
  const [report, setReport] = useState(null);
  const [generating, setGenerating] = useState(false);
  const { data: reports, refresh } = useFetch('/reports?limit=20');

  const generate = async (type) => {
    setGenerating(true);
    try {
      const res = await post('/reports/generate', { type });
      setReport(res);
      refresh();
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Report Generation Studio</div>
        <div style={{ display: 'flex', gap: 8 }}>
          {['daily', 'weekly', 'monthly', 'portfolio', 'risk', 'trade', 'ai'].map((t) => (
            <button key={t} className="btn btn-sm" onClick={() => generate(t)} disabled={generating}>{t} report</button>
          ))}
        </div>
      </div>

      {report && (
        <>
          <div className="grid grid-4">
            <StatCard label="Report Type" value={report.type} color="purple" sub={new Date(report.generatedAt).toLocaleString()} />
            <StatCard label="Net P&L" value={`$${report.portfolio?.netProfit}`} color={report.portfolio?.netProfit >= 0 ? 'green' : 'red'} />
            <StatCard label="Win Rate" value={`${report.portfolio?.winRate}%`} />
            <StatCard label="Headline" value="" sub={report.summary?.headline} />
          </div>
          <div style={{ height: 16 }} />
          <div className="grid grid-2">
            <Panel title="Portfolio Summary">
              <div className="kv">
                <dt>Balance</dt><dd>${report.portfolio?.balance?.toLocaleString()}</dd>
                <dt>Equity</dt><dd>${report.portfolio?.equity?.toLocaleString()}</dd>
                <dt>Period P&L</dt><dd className={report.portfolio?.pnl >= 0 ? 'green' : 'red'}>${report.portfolio?.pnl}</dd>
                <dt>Trades</dt><dd>{report.portfolio?.trades}</dd>
                <dt>Win Rate</dt><dd>{report.portfolio?.winRate}%</dd>
                <dt>Profit Factor</dt><dd>{report.portfolio?.profitFactor}</dd>
              </div>
            </Panel>
            <Panel title="Market Context">
              <div className="kv">
                <dt>Market Sentiment</dt><dd className={report.market?.sentiment >= 0 ? 'green' : 'red'}>{report.market?.sentiment}</dd>
                <dt>VIX</dt><dd>{report.market?.macro?.vix?.toFixed(1)}</dd>
                <dt>Recession Prob</dt><dd>{report.market?.macro?.recessionProbability?.toFixed(0)}%</dd>
                <dt>AI Decisions</dt><dd>{report.ai?.decisions}</dd>
              </div>
            </Panel>
          </div>
        </>
      )}

      <div style={{ height: 16 }} />
      <Panel title="Generated Reports" sub="Click to view latest">
        <table>
          <thead><tr><th>Type</th><th>Generated</th><th>P&L</th><th>Trades</th><th>Win Rate</th></tr></thead>
          <tbody>
            {(reports || []).map((r) => (
              <tr key={r.id} onClick={() => setReport(r.report)} style={{ cursor: 'pointer' }}>
                <td><Badge type="info">{r.type}</Badge></td>
                <td className="muted">{new Date(r.generatedAt).toLocaleString()}</td>
                <td className={r.report?.portfolio?.netProfit >= 0 ? 'green' : 'red'} style={{ fontWeight: 700 }}>${r.report?.portfolio?.netProfit}</td>
                <td>{r.report?.portfolio?.trades}</td>
                <td>{r.report?.portfolio?.winRate}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
