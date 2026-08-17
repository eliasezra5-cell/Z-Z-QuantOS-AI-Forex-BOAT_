import { useState } from 'react';
import { useFetch } from '../api.js';
import { Panel, Badge, Loading, StatCard, Empty } from '../components/ui.jsx';
import { SYMBOL_LIST, useSymbol } from '../symbols.jsx';

const COT_ASSETS = ['gold', 'silver', 'crude', 'natgas', 'eurusd', 'gbpusd'];

function fmtBig(n) {
  if (n == null) return '—';
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return Number(n).toFixed(0);
}

function SourceNote({ note }) {
  if (!note) return null;
  return <div className="muted" style={{ fontSize: 10.5, marginBottom: 8 }}>{note}</div>;
}

function ShortInterest({ data }) {
  if (!data) return <Empty text="No short-interest data." />;
  const rows = data.shortInterest || [];
  if (!rows.length) return <Empty text="No short-interest data." />;
  const latest = rows[0];
  return (
    <div>
      <SourceNote note={data.note} />
      <div className="grid grid-3">
        <StatCard label="Short Interest" value={fmtBig(latest.shortInterest)} />
        <StatCard label="Days to Cover" value={latest.daysToCover} />
        <StatCard label="Avg Daily Volume" value={fmtBig(latest.avgDailyVolume)} />
      </div>
      <div style={{ overflowX: 'auto', marginTop: 10 }}>
        <table className="table">
          <thead>
            <tr><th>Settlement</th><th>Short Interest</th><th>ADV</th><th>Days to Cover</th></tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>{r.settlementDate}</td>
                <td>{fmtBig(r.shortInterest)}</td>
                <td>{fmtBig(r.avgDailyVolume)}</td>
                <td>{r.daysToCover}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ShortVolume({ data }) {
  if (!data) return <Empty text="No short-volume data." />;
  const rows = data.shortVolume || [];
  if (!rows.length) return <Empty text="No short-volume data." />;
  const latest = rows[0];
  const ratioPct = latest.shortVolumeRatio != null ? (latest.shortVolumeRatio * 100).toFixed(1) : '—';
  return (
    <div>
      <SourceNote note={data.note} />
      <div className="grid grid-3">
        <StatCard label="Short Volume" value={fmtBig(latest.shortVolume)} />
        <StatCard label="Total Volume" value={fmtBig(latest.totalVolume)} />
        <StatCard label="Short Volume Ratio" value={`${ratioPct}%`} />
      </div>
      <div style={{ overflowX: 'auto', marginTop: 10 }}>
        <table className="table">
          <thead>
            <tr><th>Date</th><th>Short Vol</th><th>Total Vol</th><th>Ratio</th></tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>{r.date}</td>
                <td>{fmtBig(r.shortVolume)}</td>
                <td>{fmtBig(r.totalVolume)}</td>
                <td>{r.shortVolumeRatio != null ? `${(r.shortVolumeRatio * 100).toFixed(1)}%` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DarkPool({ data }) {
  if (!data) return <Empty text="No dark-pool data." />;
  const rows = data.darkpool || [];
  if (!rows.length) return <Empty text="No dark-pool data." />;
  const latest = rows[0];
  const ratioPct = latest.darkPoolRatio != null ? (latest.darkPoolRatio * 100).toFixed(1) : '—';
  return (
    <div>
      <SourceNote note={data.note} />
      <div className="grid grid-3">
        <StatCard label="OTC Volume" value={fmtBig(latest.otcVolume)} />
        <StatCard label="Exchange Volume" value={fmtBig(latest.exchangeVolume)} />
        <StatCard label="Dark-Pool Ratio" value={`${ratioPct}%`} />
      </div>
      <div style={{ overflowX: 'auto', marginTop: 10 }}>
        <table className="table">
          <thead>
            <tr><th>Date</th><th>OTC Vol</th><th>Exchange Vol</th><th>Dark Ratio</th></tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>{r.date}</td>
                <td>{fmtBig(r.otcVolume)}</td>
                <td>{fmtBig(r.exchangeVolume)}</td>
                <td>{r.darkPoolRatio != null ? `${(r.darkPoolRatio * 100).toFixed(1)}%` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Cot({ data }) {
  if (!data) return <Empty text="No COT data." />;
  const r = data.report;
  if (!r) return <Empty text="No COT report." />;
  const bias = (r.bias || '').toLowerCase();
  const color = bias === 'bullish' ? 'green' : bias === 'bearish' ? 'red' : 'amber';
  return (
    <div>
      <SourceNote note={data.note} />
      <div className="grid grid-4">
        <StatCard label="Market" value={r.market} sub={r.reportDate} />
        <StatCard label="Non-Commercial Net" value={fmtBig(r.netNonCommercial)} color={color} sub={bias.toUpperCase() || '—'} />
        <StatCard label="Comm Long" value={fmtBig(r.commercialLong)} />
        <StatCard label="Comm Short" value={fmtBig(r.commercialShort)} />
      </div>
    </div>
  );
}

function CongressTrades({ data }) {
  if (!data) return <Empty text="No congressional disclosures." />;
  const trades = data.trades || [];
  if (!trades.length) return <Empty text="No congressional disclosures." />;
  return (
    <div>
      <SourceNote note={data.note} />
      <div style={{ overflowX: 'auto' }}>
        <table className="table">
          <thead>
            <tr><th>Member</th><th>Ticker</th><th>Type</th><th>Amount</th><th>Date</th></tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <tr key={i}>
                <td>{t.member}</td>
                <td><b>{t.ticker}</b></td>
                <td><Badge type={t.type === 'BUY' ? 'ok' : 'warn'}>{t.type}</Badge></td>
                <td className="muted">{t.amount}</td>
                <td className="muted">{t.date}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SecFilings({ data }) {
  if (!data) return <Empty text="No SEC filings." />;
  const filings = data.filings || [];
  if (!filings.length) return <Empty text="No SEC filings." />;
  return (
    <div>
      <SourceNote note={data.note} />
      <div style={{ overflowX: 'auto' }}>
        <table className="table">
          <thead>
            <tr><th>Form</th><th>Date</th><th>Description</th></tr>
          </thead>
          <tbody>
            {filings.map((f, i) => (
              <tr key={i}>
                <td><Badge type="info">{f.form}</Badge></td>
                <td className="muted">{f.date}</td>
                <td className="muted">{f.description || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function SmartMoneyIntel() {
  const { symbol, setSymbol } = useSymbol();
  const [asset, setAsset] = useState('gold');
  const { data, loading } = useFetch(`/pro/institutional/overview?symbol=${symbol}&asset=${asset}`, [symbol, asset]);

  const d = data?.data || {};
  const failed = data?.sources_failed || [];

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Smart Money Intel</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {SYMBOL_LIST.map(([s]) => <option key={s}>{s}</option>)}
          </select>
          <select value={asset} onChange={(e) => setAsset(e.target.value)}>
            {COT_ASSETS.map((a) => <option key={a}>{a}</option>)}
          </select>
        </div>
      </div>

      {loading ? <Loading /> : (
        <>
          {failed.length > 0 && (
            <div className="panel" style={{ borderLeft: '3px solid var(--amber)', marginBottom: 12 }}>
              <div className="muted" style={{ fontSize: 11 }}>
                Partial data — {failed.length} source(s) unavailable: {failed.join(', ')}
              </div>
            </div>
          )}

          <div className="grid grid-2">
            <Panel title="Short Interest" sub="FINRA + fails-to-deliver">
              <ShortInterest data={d.shortInterest} />
            </Panel>
            <Panel title="Short Volume" sub="Daily short-sale volume">
              <ShortVolume data={d.shortVolume} />
            </Panel>
          </div>

          <div style={{ height: 12 }} />

          <div className="grid grid-2">
            <Panel title="Dark Pool / OTC" sub="Off-exchange flow">
              <DarkPool data={d.darkpool} />
            </Panel>
            <Panel title="CFTC COT" sub="Futures positioning">
              <Cot data={d.cot} />
            </Panel>
          </div>

          <div style={{ height: 12 }} />

          <div className="grid grid-2">
            <Panel title="Congress Trades" sub="Political insider disclosures">
              <CongressTrades data={d.congressTrades} />
            </Panel>
            <Panel title="SEC Filings" sub="Recent EDGAR filings">
              <SecFilings data={d.secFilings} />
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
