import { useEffect, useState } from 'react';
import { get } from '../api.js';
import { Panel, Badge, Loading } from './ui.jsx';

const SOURCE_OPTIONS = [
  ['fred', 'FRED', 'DGS10'],
  ['ecb', 'ECB', 'EXR.D.USD.EUR.SP00.A'],
  ['oecd', 'OECD', 'G20_MAIN.O_CPI.M'],
  ['eia', 'EIA', 'PET.RBRTE.D'],
  ['bls', 'BLS', 'LNS14000000'],
];

export default function OfficialSources() {
  const [source, setSource] = useState('fred');
  const [seriesId, setSeriesId] = useState('DGS10');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      setLoading(true);
      try {
        const res = await get(`/pro/macro/${source}/${encodeURIComponent(seriesId)}`);
        if (alive) setData(res.data || res);
      } catch (e) {
        if (alive) setData({ available: false, reason: 'internal-error' });
      } finally {
        if (alive) setLoading(false);
      }
    };
    load();
    return () => { alive = false; };
  }, [source, seriesId]);

  const rows = data?.rows || [];

  return (
    <Panel title="Official Sources" sub="FRED · ECB · OECD · EIA · BLS (optional keys)">
      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <select className="select" value={source} onChange={(e) => {
          const next = SOURCE_OPTIONS.find(([id]) => id === e.target.value);
          setSource(e.target.value);
          setSeriesId(next ? next[2] : '');
        }} style={{ fontSize: 11 }}>
          {SOURCE_OPTIONS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
        <input
          className="input"
          value={seriesId}
          onChange={(e) => setSeriesId(e.target.value)}
          placeholder="Series ID"
          style={{ fontSize: 11, flex: 1, padding: '4px 8px' }}
        />
      </div>

      {loading ? <Loading /> : !data ? null : (
        <>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
            <Badge type={data.available ? 'ok' : 'warn'}>{data.available ? 'LIVE' : 'DEGRADED'}</Badge>
            <span className="muted" style={{ fontSize: 10.5 }}>
              {data.source || source} · {data.series || seriesId}
            </span>
            {data.note && <span className="muted" style={{ fontSize: 10 }}>· {data.note}</span>}
          </div>

          {rows && rows.length > 0 ? (
            <div style={{ overflowX: 'auto', maxHeight: 260, overflowY: 'auto' }}>
              <table className="table" style={{ minWidth: 280 }}>
                <thead>
                  <tr><th>Label / Date</th><th>Value</th></tr>
                </thead>
                <tbody>
                  {rows.slice(-15).reverse().map((r, i) => (
                    <tr key={i}>
                      <td>{r.date || r.name || r.label || '—'}</td>
                      <td style={{ fontWeight: 700 }}>{r.value != null ? (typeof r.value === 'number' ? r.value.toFixed(3) : r.value) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="muted" style={{ fontSize: 11 }}>
              {data.reason || 'No data for this series. Add the matching API key to .env for live data.'}
            </div>
          )}
        </>
      )}
    </Panel>
  );
}
