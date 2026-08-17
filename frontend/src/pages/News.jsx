import { useCallback, useEffect, useMemo, useState } from 'react';
import { useFetch, useLive, post } from '../api.js';
import { Panel, Badge, Loading, Meter } from '../components/ui.jsx';

const SOURCE_TYPES = [
  { value: 'rss', label: 'RSS Feed' },
  { value: 'telegram_channel', label: 'Telegram (Bot API / manual-forward)' },
  { value: 'telegram', label: 'Telegram (legacy)' },
  { value: 'x_twitter', label: 'X / Twitter' },
  { value: 'web', label: 'Website (single page)' },
  { value: 'web_blog', label: 'Website / Blog' },
  { value: 'financial_api', label: 'Financial API' },
  { value: 'reddit', label: 'Reddit' },
];

const ORIGIN_LABELS = {
  twitter: 'X/Twitter',
  x_twitter: 'X/Twitter',
  web: 'Website',
  web_blog: 'Website',
  website: 'Website',
  telegram_channel: 'Telegram (Channel)',
  telegram_manual: 'Telegram (Bot manual-forward)',
  telegram: 'Telegram',
  whatsapp_manual: 'WhatsApp (Manual forward)',
  rss: 'RSS',
  financial_api: 'Financial API',
  official: 'Official',
  social: 'Social',
  api: 'API',
  calendar: 'Calendar',
  x: 'X',
  reddit: 'Reddit',
};

const isTwitterType = (t) => t === 'x_twitter' || t === 'twitter';
const isRedditType = (t) => t === 'reddit';

const toHandle = (raw) => {
  const s = String(raw || '').trim().replace(/^@/, '');
  if (!s) return '';
  return s.split('/').pop().split('?')[0].trim();
};

const parseHandles = (raw) => String(raw || '').split(',').map(toHandle).filter(Boolean);

const parseSubs = (raw) => String(raw || '')
  .split(',')
  .map((s) => s.trim().replace(/^\/?r\//, '').replace(/^\/$/, ''))
  .filter(Boolean);

export default function News() {
  const [filter, setFilter] = useState('all');
  const [originFilter, setOriginFilter] = useState('all');
  const newsPath = originFilter === 'all' ? '/news?limit=60' : `/news?limit=60&sourceType=${originFilter}`;
  const { data: news, loading, refresh } = useFetch(newsPath);
  const { data: sources, refresh: refreshSources } = useFetch('/news/sources');
  const { data: originSummary } = useFetch('/news/sources/summary');
  const [liveItems, setLiveItems] = useState([]);
  const [form, setForm] = useState({ name: '', type: 'rss', priority: 2, url: '', handles: '', subs: '' });
  const [sourceError, setSourceError] = useState('');
  const [polling, setPolling] = useState(false);
  const [pollError, setPollError] = useState('');
  const [lang, setLang] = useState('en');
  const [translations, setTranslations] = useState({});

  const fetchTranslation = useCallback(async (item) => {
    if (!item?.id || lang === 'en') return;
    const key = `${lang}:${item.id}`;
    setTranslations((prev) => {
      const existing = prev[key];
      if (existing && (existing.loading || existing.title)) return prev;
      return { ...prev, [key]: { ...(existing || {}), loading: true } };
    });
    try {
      const res = await post(`/news/${item.id}/translate?lang=${lang}`);
      if (res?.status === 'ok') {
        setTranslations((prev) => ({
          ...prev,
          [key]: { title: res.translatedTitle, summary: res.translatedSummary, loading: false, error: false },
        }));
      } else {
        setTranslations((prev) => ({ ...prev, [key]: { loading: false, error: true } }));
      }
    } catch (err) {
      setTranslations((prev) => ({ ...prev, [key]: { loading: false, error: true } }));
    }
  }, [lang]);

  const pollSources = async () => {
    setPolling(true);
    setPollError('');
    try {
      await post('/news/collectors/run', { limit: 10 });
      refresh();
      refreshSources();
    } catch (err) {
      setPollError(err.message || 'Failed to poll sources');
    } finally {
      setPolling(false);
    }
  };

  useLive('news', useCallback((data) => {
    const item = data?.item;
    if (!item?.id) return;
    setLiveItems((prev) => [item, ...prev.filter((i) => i.id !== item.id)].slice(0, 60));
  }, []));

  const items = useMemo(() => {
    const seen = new Set();
    const merged = [];
    for (const n of [...liveItems, ...(news || [])]) {
      if (!n || !n.id || seen.has(n.id)) continue;
      seen.add(n.id);
      merged.push(n);
    }
    return merged.slice(0, 60);
  }, [liveItems, news]);

  const filtered = items.filter((n) =>
    (filter === 'all' || n.category === filter) &&
    (originFilter === 'all' || n.sourceType === originFilter)
  );

  const visibleKey = useMemo(() => filtered.slice(0, 15).map((n) => n.id).join(','), [filtered]);

  useEffect(() => {
    if (lang === 'en') {
      setTranslations({});
      return;
    }
    filtered.slice(0, 15).forEach((n) => fetchTranslation(n));
  }, [lang, visibleKey, fetchTranslation]);

  const addSource = async () => {
    if (!form.name) return;
    setSourceError('');
    const isTwitter = isTwitterType(form.type);
    const isReddit = isRedditType(form.type);
    const handles = isTwitter ? parseHandles(form.handles) : [];
    const subs = isReddit ? parseSubs(form.subs) : [];
    const payload = {
      name: form.name,
      type: form.type,
      priority: parseInt(form.priority, 10),
    };
    if (isReddit) {
      payload.config = subs.length ? { subreddits: subs } : {};
    } else if (isTwitter) {
      payload.config = handles.length ? { handles } : {};
    } else {
      payload.url = form.url.trim() || null;
    }
    try {
      await post('/news/sources', payload);
      setForm({ name: '', type: 'rss', priority: 2, url: '', handles: '', subs: '' });
      refreshSources();
    } catch (err) {
      setSourceError(err.message || 'Failed to add source');
    }
  };

  return (
    <div>
      <div className="page-head">
        <div className="section-title">News Intelligence Terminal</div>
        <div style={{ display: 'flex', gap: 8 }}>
          {['all', 'macro', 'crypto', 'central-banks', 'energy', 'precious-metals', 'equities', 'bonds'].map((c) => (
            <button key={c} className={`btn btn-sm ${filter === c ? 'btn-primary' : ''}`} onClick={() => setFilter(c)}>{c}</button>
          ))}
          <select className="btn btn-sm" value={originFilter} onChange={(e) => setOriginFilter(e.target.value)} title="Filter news items by origin">
            <option value="all">All origins</option>
            {['twitter', 'web', 'telegram_channel', 'telegram_manual', 'rss', 'financial_api', 'official', 'reddit'].map((o) => (
              <option key={o} value={o}>{ORIGIN_LABELS[o] || o}</option>
            ))}
          </select>
          <button className="btn btn-sm" onClick={refresh} title="Manual refresh (live updates also arrive via WebSocket)">↻ Refresh</button>
          <select className="btn btn-sm" value={lang} onChange={(e) => setLang(e.target.value)} title="Translate news headlines (best-effort)">
            <option value="en">English</option>
            <option value="ur">اردو</option>
            <option value="ur-roman">Roman Urdu</option>
          </select>
          <button className="btn btn-sm" onClick={pollSources} disabled={polling} title="Force an immediate poll of all news sources (RSS/web/X/Twitter/Telegram manual-forward)">{polling ? 'Polling…' : '🔄 Poll sources now'}</button>
          {pollError && <span className="muted" style={{ fontSize: 11, color: 'var(--red)' }}>{pollError}</span>}
        </div>
      </div>

      <div className="grid grid-3">
        <Panel title="AI News Feed" sub="FinBERT + FinLLM · RAG indexed" style={{ gridColumn: 'span 2' }}>
          {loading && items.length === 0 ? <Loading /> : (filtered || []).slice(0, 15).map((n) => (
            <div key={n.id} className="list-item">
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                <span style={{ fontWeight: 500 }}>
                  {translations[`${lang}:${n.id}`]?.loading
                    ? n.title
                    : (translations[`${lang}:${n.id}`]?.title || n.title)}
                  {translations[`${lang}:${n.id}`]?.loading && <span className="muted" style={{ fontSize: 10 }}> …</span>}
                </span>
                <Badge type={n.sentiment > 0.1 ? 'buy' : n.sentiment < -0.1 ? 'sell' : 'neutral'}>{(n.sentiment ?? 0).toFixed(2)}</Badge>
              </div>
              <div className="muted" style={{ fontSize: 10.5, marginTop: 3, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <span>{n.source}</span>
                {n.sourceType && n.sourceType !== 'unknown' && (
                  <span className="badge info">{ORIGIN_LABELS[n.sourceType] || n.sourceType}</span>
                )}
                <span>{new Date(n.time).toLocaleString()}</span>
                <span>Impact <b>{n.marketImpact}</b></span>
                <span>Trust <b>{n.trustScore}</b></span>
                <span>Confidence <b>{n.confidence}</b></span>
                <span>{n.crossVerified ? '✔ Verified' : 'Unverified'}</span>
              </div>
              <div style={{ display: 'flex', gap: 4, marginTop: 4, flexWrap: 'wrap' }}>
                {n.entities?.map((e) => <span key={e} className="badge info">{e}</span>)}
                {(n.keywords || []).slice(0, 4).map((k) => <span key={k} className="badge neutral" style={{ opacity: 0.6 }}>{k}</span>)}
              </div>
            </div>
          ))}
        </Panel>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Panel title="Origin Breakdown">
            {Object.entries(originSummary?.sourcesByType || {}).map(([type, count]) => (
              <div key={type} className="list-item" style={{ padding: '4px 0', display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 11.5 }}>{ORIGIN_LABELS[type] || type}</span>
                <span className="muted">{count}</span>
              </div>
            ))}
          </Panel>
          <Panel title="Source Reliability">
            {(sources || []).slice(0, 8).map((s) => (
              <div key={s.id} className="list-item" style={{ padding: '6px 0' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 11.5 }}>{s.name}</span>
                  <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                    {(s.config?.lastError || s.lastError) ? (
                      <span className="badge error" title={(s.config?.lastError || s.lastError)}>Error</span>
                    ) : null}
                    <Badge type={s.reliability > 0.9 ? 'buy' : s.reliability > 0.7 ? 'info' : 'warning'}>{s.reliability}</Badge>
                  </div>
                </div>
                <div className="muted" style={{ fontSize: 10 }}>{s.type} · Priority {s.priority} · {s.enabled ? 'Enabled' : 'Disabled'}</div>
              </div>
            ))}
          </Panel>
          <Panel title="Manual Source Manager" sub="Add websites, RSS, Telegram, APIs">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <input placeholder="Source name (e.g. My RSS Feed)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              {isRedditType(form.type) ? (
                <input placeholder="Subreddit(s) — comma-separated, e.g. Forex, wallstreetbets, economy" value={form.subs} onChange={(e) => setForm({ ...form, subs: e.target.value })} />
              ) : isTwitterType(form.type) ? (
                <input placeholder="Twitter handle(s) — comma-separated, e.g. ForexPeaceArmy_, elonmusk" value={form.handles} onChange={(e) => setForm({ ...form, handles: e.target.value })} />
              ) : (
                <input placeholder="Feed URL (required for RSS/news fetch)" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
              )}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} style={{ flex: 1 }}>
                  {SOURCE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
                <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                  {[1, 2, 3, 4].map((p) => <option key={p} value={p}>P{p}</option>)}
                </select>
              </div>
              <button className="btn btn-primary" onClick={addSource}>Add Source</button>
              {sourceError && <div className="muted" style={{ fontSize: 11, color: 'var(--red)' }}>{sourceError}</div>}
            </div>
          </Panel>
          <Panel title="Sentiment Distribution">
            {(() => {
              const cats = {};
              items.forEach((n) => { cats[n.sentiment > 0.1 ? 'Bullish' : n.sentiment < -0.1 ? 'Bearish' : 'Neutral'] = (cats[n.sentiment > 0.1 ? 'Bullish' : n.sentiment < -0.1 ? 'Bearish' : 'Neutral'] || 0) + 1; });
              const total = items.length || 1;
              return Object.entries(cats).map(([k, v]) => (
                <Meter key={k} label={k} value={v} pct={(v / total) * 100} color={k === 'Bullish' ? 'var(--green)' : k === 'Bearish' ? 'var(--red)' : 'var(--amber)'} />
              ));
            })()}
          </Panel>
        </div>
      </div>
    </div>
  );
}
