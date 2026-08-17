import { useFetch, get } from '../api.js';
import { Panel, Badge, StatCard } from '../components/ui.jsx';
import { SYMBOL_LIST, useSymbol } from '../symbols.jsx';

const ratingColor = (r = 'Hold') => {
  const map = { Buy: 'green', Overweight: 'green', Hold: 'amber', Underweight: 'red', Sell: 'red' };
  return map[r] || 'amber';
};

const stateBadge = (state) => {
  const map = {
    TRADE: { label: 'TRADE', type: 'buy' },
    PROVIDER_DEGRADED: { label: 'PROVIDER DEGRADED', type: 'warning' },
    DATA_INSUFFICIENT: { label: 'DATA INSUFFICIENT', type: 'neutral' },
    MISSING: { label: 'NO CASE PRODUCED', type: 'error' },
  };
  return map[state] || { label: state || 'UNKNOWN', type: 'neutral' };
};

export default function Debate() {
  const { symbol, setSymbol } = useSymbol();
  const { data: latest, refresh } = useFetch(`/ai/debate/${symbol}/latest`);
  const { data: history } = useFetch(`/ai/debate/${symbol}/history?limit=10`);
  const debate = latest && latest.status !== 'none' && (latest.available || latest.rating) ? latest : null;
  const unavailable = latest && !debate;

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Bull vs Bear Debate</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {SYMBOL_LIST.map(([s]) => <option key={s}>{s}</option>)}
          </select>
          <button className="btn btn-primary" onClick={refresh}>Refresh</button>
        </div>
      </div>

      {unavailable && (
        <Panel title="Debate Unavailable" sub={latest?.reason || 'No debate has been run for this symbol yet'}>
          <div className="empty">
            {latest?.status === 'unavailable'
              ? `The research debate could not run — neither the bull nor the bear agent produced an analyst case (${latest.bull?.state || 'MISSING'} / ${latest.bear?.state || 'MISSING'}). Configure and reach an LLM provider, then hit Refresh.`
              : 'No bull vs bear debate stored for this symbol yet. Run Multi-Agent Analysis to trigger the research debate.'}
          </div>
        </Panel>
      )}

      {debate && (
        <>
          <div className="grid grid-4">
            <StatCard label="Resolved Rating" value={debate.rating ?? '—'} color={ratingColor(debate.rating)} />
            <StatCard label="Direction Signal" value={(debate.direction || 'neutral').toUpperCase()} color={debate.direction === 'buy' ? 'green' : debate.direction === 'sell' ? 'red' : 'amber'} />
            <StatCard label="Net Stance" value={debate.net != null ? `${debate.net >= 0 ? '+' : ''}${debate.net}` : '—'} sub="+1 bull wins · -1 bear wins" />
            <StatCard label="Signal Strength" value={debate.strength != null ? debate.strength : '—'} sub="used as capped consensus voice" />
          </div>

          {debate.status === 'partial' && (
            <div style={{ height: 16 }} />
          )}
          {debate.status === 'partial' && (
            <Panel title="Partial Debate" sub="One side could not produce a case">
              <div className="empty">
                {(debate.bear?.state && debate.bear.state !== 'TRADE' ? 'Bear' : 'Bull')} case unavailable (
                {debate.bear?.state !== 'TRADE' ? debate.bear?.state : debate.bull?.state}). The debate was resolved from the available side only.
              </div>
            </Panel>
          )}

          <div style={{ height: 16 }} />
          <div className="grid grid-2">
            <Panel title="Bull Case" sub={`Confidence ${debate.bull?.confidence ?? '—'}`}>
              <Badge type={stateBadge(debate.bull?.state).type}>{stateBadge(debate.bull?.state).label}</Badge>
              <div style={{ marginTop: 10, fontSize: 12.5, lineHeight: 1.6 }}>{debate.bull?.argument || <span className="muted">No bull case produced.</span>}</div>
              {debate.bull?.counters?.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <div className="muted" style={{ fontWeight: 600, fontSize: 10.5, textTransform: 'uppercase', letterSpacing: 0.5 }}>Rebuttals (vs bear)</div>
                  {(debate.bull.counters).map((c, i) => (
                    <div key={i} style={{ fontSize: 11, padding: '4px 0', borderLeft: '2px solid var(--green)', paddingLeft: 8, marginTop: 2 }}>
                      <span className="muted" style={{ fontSize: 10 }}>{i + 1}.</span> {c}
                    </div>
                  ))}
                </div>
              )}
            </Panel>

            <Panel title="Bear Case" sub={`Confidence ${debate.bear?.confidence ?? '—'}`}>
              <Badge type={stateBadge(debate.bear?.state).type}>{stateBadge(debate.bear?.state).label}</Badge>
              <div style={{ marginTop: 10, fontSize: 12.5, lineHeight: 1.6 }}>{debate.bear?.argument || <span className="muted">No bear case produced.</span>}</div>
              {debate.bear?.counters?.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <div className="muted" style={{ fontWeight: 600, fontSize: 10.5, textTransform: 'uppercase', letterSpacing: 0.5 }}>Rebuttals (vs bull)</div>
                  {(debate.bear.counters).map((c, i) => (
                    <div key={i} style={{ fontSize: 11, padding: '4px 0', borderLeft: '2px solid var(--red)', paddingLeft: 8, marginTop: 2 }}>
                      <span className="muted" style={{ fontSize: 10 }}>{i + 1}.</span> {c}
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </div>

          <div style={{ height: 16 }} />
          <Panel title="Research Manager Resolution" sub="Debate transcript · transparency">
            <div className="kv">
              <dt>Rating</dt><dd className="purple" style={{ fontWeight: 700 }}>{debate.rating}</dd>
              <dt>Rationale</dt><dd style={{ textAlign: 'left', fontWeight: 400 }}>{debate.rationale}</dd>
            </div>
            <div style={{ marginTop: 12 }}>
              {(debate.transcript || []).map((t, i) => (
                <div key={i} style={{ fontSize: 11, padding: '6px 0', borderLeft: '2px solid var(--border2)', paddingLeft: 10, marginBottom: 4 }}>
                  <span className="muted" style={{ fontSize: 10 }}>{i + 1}.</span>{' '}
                  <span style={{ fontWeight: 600 }}>{t.speaker.replace('_', ' ')}</span>
                  {t.argument && <span className="muted"> · {t.argument}</span>}
                  <span className="muted" style={{ fontSize: 10 }}> ({t.stance})</span>
                </div>
              ))}
            </div>
          </Panel>
        </>
      )}

      <div style={{ height: 16 }} />
      <Panel title="Debate History" sub={`Latest ${(history || []).length} debates for ${symbol}`}>
        {(history || []).map((d, i) => (
          <div key={i} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontWeight: 700 }}>{d.rating ?? '—'}</span>
              <span className="muted"> · {d.direction}</span>
              <div className="muted" style={{ fontSize: 10.5 }}>{new Date(d.timestamp).toLocaleString()}</div>
            </div>
            <Badge type={ratingColor(d.rating)}>{d.rating ?? 'unavailable'}</Badge>
          </div>
        ))}
        {(history || []).length === 0 && <div className="empty">No debate history yet.</div>}
      </Panel>
    </div>
  );
}
