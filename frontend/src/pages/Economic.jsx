import { useState } from 'react';
import { useFetch } from '../api.js';
import { Panel, Badge, Loading } from '../components/ui.jsx';

export default function Economic() {
  const [impact, setImpact] = useState('all');
  const { data: events, loading } = useFetch('/economic/calendar?limit=100');
  const filtered = events?.filter((e) => impact === 'all' || e.impact === parseInt(impact, 10));

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Economic Calendar Intelligence</div>
        <div style={{ display: 'flex', gap: 8 }}>
          {[['all', 'All Impact'], [3, 'High'], [2, 'Medium'], [1, 'Low']].map(([v, label]) => (
            <button key={v} className={`btn btn-sm ${impact === String(v) ? 'btn-primary' : ''}`} onClick={() => setImpact(String(v))}>{label}</button>
          ))}
        </div>
      </div>

      <Panel title="Upcoming Events" sub="AI impact analysis per event">
        {loading ? <Loading /> : (
          <table>
            <thead>
              <tr><th>Time</th><th>Event</th><th>Currency</th><th>Impact</th><th>Forecast</th><th>Previous</th><th>Status</th><th>AI Direction</th></tr>
            </thead>
            <tbody>
              {(filtered || []).map((e) => (
                <tr key={e.id}>
                  <td className="muted">{new Date(e.time).toLocaleString()}</td>
                  <td style={{ fontWeight: 500 }}>{e.name}</td>
                  <td><Badge type="info">{e.currency}</Badge></td>
                  <td><Badge type={e.impact === 3 ? 'high' : e.impact === 2 ? 'warning' : 'info'}>{'●'.repeat(e.impact)}{'○'.repeat(3 - e.impact)}</Badge></td>
                  <td>{e.forecast ?? '—'}</td>
                  <td className="muted">{e.previous ?? '—'}</td>
                  <td>
                    <Badge type={e.status === 'released' ? 'buy' : e.status === 'upcoming-today' ? 'high' : 'neutral'}>{e.status}</Badge>
                    {e.status === 'released' && <span className="muted" style={{ marginLeft: 6 }}>{e.actual}</span>}
                  </td>
                  <td className={e.ai?.direction?.includes('bearish') ? 'red' : e.ai?.direction?.includes('bullish') ? 'green' : 'muted'}>
                    {e.ai?.direction || 'pending'}
                    {e.ai && <div style={{ fontSize: 10, opacity: 0.7 }}>vol {e.ai.volatilityExpectation}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <div style={{ height: 16 }} />
      <Panel title="High Impact Events Tracker" sub="Next 72 hours">
        {loading ? <Loading /> : (events || []).filter((e) => e.impact === 3).slice(0, 8).map((e) => (
          <div key={e.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontWeight: 600 }}>{e.name}</div>
              <div className="muted" style={{ fontSize: 10.5 }}>{new Date(e.time).toLocaleString()}</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <Badge type={e.status === 'released' ? 'buy' : 'high'}>{e.status === 'released' ? 'Released' : 'Upcoming'}</Badge>
              {e.ai && <div className="muted" style={{ fontSize: 10, marginTop: 3 }}>{e.ai.reasoning}</div>}
            </div>
          </div>
        ))}
      </Panel>
    </div>
  );
}
