import { useEffect, useState } from 'react';
import { get, fmtMoney } from '../api.js';
import { Panel, Badge, Loading, StatCard } from '../components/ui.jsx';

function ProbBar({ prob }) {
  if (prob == null) return <span className="muted">—</span>;
  const pct = Math.round(prob * 100);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 8, background: 'var(--border)', borderRadius: 4, overflow: 'hidden' }}>
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background: pct >= 50 ? 'var(--green)' : 'var(--red)',
            borderRadius: 4,
          }}
        />
      </div>
      <span style={{ fontWeight: 800, fontSize: 13, minWidth: 40, textAlign: 'right' }}>{pct}%</span>
    </div>
  );
}

function MarketCard({ m }) {
  return (
    <div style={{ padding: 12, border: '1px solid var(--border)', borderRadius: 10 }}>
      <div style={{ fontSize: 12.5, lineHeight: 1.4, marginBottom: 8 }}>{m.question || '—'}</div>
      <ProbBar prob={m.probability} />
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 10.5 }} className="muted">
        <span>Vol {m.volume != null ? fmtMoney(m.volume) : '—'}</span>
        <span>Ends {m.endDate ? new Date(m.endDate).toLocaleDateString() : '—'}</span>
      </div>
      {m.priceChange24hrPct != null && (
        <div className="muted" style={{ fontSize: 10.5, marginTop: 4 }}>
          24h:{' '}
          <span style={{ color: m.priceChange24hrPct >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>
            {m.priceChange24hrPct >= 0 ? '+' : ''}{m.priceChange24hrPct.toFixed(1)}%
          </span>
        </div>
      )}
    </div>
  );
}

function MarketGrid({ markets }) {
  if (!markets || !markets.length) return <div className="empty">No markets found.</div>;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
      {markets.map((m) => (
        <MarketCard key={m.id || m.slug || m.question} m={m} />
      ))}
    </div>
  );
}

export default function PredictionMarkets() {
  const [topic, setTopic] = useState('');
  const [overview, setOverview] = useState({});
  const [search, setSearch] = useState({});
  const [loadingOverview, setLoadingOverview] = useState(true);
  const [loadingSearch, setLoadingSearch] = useState(false);
  const [searchError, setSearchError] = useState('');

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await get('/pro/prediction-markets/macro-overview');
        if (alive) setOverview(r.data || {});
      } catch (e) {
        /* panels render empty state */
      } finally {
        if (alive) setLoadingOverview(false);
      }
    };
    load();
    return () => { alive = false; };
  }, []);

  const runSearch = async (t = topic) => {
    const query = (t || '').trim();
    if (!query) return;
    setLoadingSearch(true);
    setSearchError('');
    setSearch({});
    try {
      const r = await get(`/pro/prediction-markets/search?topic=${encodeURIComponent(query)}&limit=6`);
      setSearch(r.data || {});
    } catch (e) {
      setSearchError('Search failed');
      setSearch({});
    } finally {
      setLoadingSearch(false);
    }
  };

  const overviewGroups = overview.groups || [];
  const searchMarkets = search.markets || [];

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Prediction Markets</div>
        <span className="muted" style={{ fontSize: 11 }}>
          Market-implied probabilities · Polymarket{' '}
          <Badge type={overview.available === false ? 'warn' : 'ok'}>
            {overview.available === false ? 'degraded' : 'live'}
          </Badge>
        </span>
      </div>

      {overview.note && overview.available === false ? (
        <div className="muted" style={{ fontSize: 11, marginBottom: 12 }}>{overview.note}</div>
      ) : null}

      <div style={{ marginBottom: 16 }}>
        <Panel title="Search Markets" icon="▣" sub="Find an open market by topic keyword">
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              style={{ flex: 1 }}
              value={topic}
              placeholder="e.g. Fed rate, recession, inflation, election…"
              onChange={(e) => setTopic(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') runSearch(); }}
            />
            <button onClick={() => runSearch()} disabled={loadingSearch}>
              {loadingSearch ? 'Searching…' : 'Search'}
            </button>
          </div>
          {searchError && <div className="muted" style={{ color: 'var(--red)', fontSize: 11, marginTop: 6 }}>{searchError}</div>}
        </Panel>
      </div>

      {loadingSearch ? <Loading text="Searching markets…" /> : null}
      {!loadingSearch && searchMarkets.length ? (
        <div style={{ marginBottom: 16 }}>
          <div className="section-title" style={{ fontSize: 14 }}>
            Results for “{search.topic}”
          </div>
          <div style={{ marginTop: 10 }}>
            <MarketGrid markets={searchMarkets} />
          </div>
        </div>
      ) : null}
      {!loadingSearch && search.topic && !searchMarkets.length && !searchError ? (
        <div className="empty" style={{ marginBottom: 16 }}>No markets found.</div>
      ) : null}

      <div className="section-title" style={{ fontSize: 14 }}>Macro Overview</div>
      {loadingOverview ? <Loading text="Loading market data…" /> : null}
      {!loadingOverview && !overviewGroups.length ? (
        <div className="empty">{overview.note ? overview.note : 'No market data available.'}</div>
      ) : null}
      <div className="grid grid-4" style={{ marginBottom: 16, marginTop: 10 }}>
        <StatCard label="Topics" value={overviewGroups.length} icon="◈" />
        <StatCard label="Markets" value={overview.total != null ? overview.total : '—'} icon="▣" />
        <StatCard label="Source" value={overview.source === 'polymarket' ? 'Polymarket' : '—'} icon="⇄" />
        <StatCard label="Updated" value={overview.updatedAt ? new Date(overview.updatedAt).toLocaleTimeString() : '—'} icon="◉" />
      </div>
      <div className="grid grid-2">
        {overviewGroups.map((g) => (
          <Panel key={g.topic} title={g.topic} icon="◈" sub={`${g.count} markets`}>
            <MarketGrid markets={g.markets} />
          </Panel>
        ))}
      </div>
    </div>
  );
}

export { ProbBar, MarketCard, MarketGrid };
