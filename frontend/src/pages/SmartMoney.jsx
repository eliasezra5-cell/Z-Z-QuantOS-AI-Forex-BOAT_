import { useState } from 'react';
import { useFetch } from '../api.js';
import { Panel, Badge, Loading, StatCard, Meter } from '../components/ui.jsx';
import { SYMBOL_LIST, useSymbol } from '../symbols.jsx';

export default function SmartMoney() {
  const { symbol, setSymbol } = useSymbol();
  const { data: smc, loading } = useFetch(`/technical/smc/${symbol}?timeframe=H1`, [symbol]);

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Smart Money Concepts</div>
        <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          {SYMBOL_LIST.map(([s]) => <option key={s}>{s}</option>)}
        </select>
      </div>
      {loading ? <Loading /> : (
        <>
          <div className="grid grid-4">
            <StatCard label="Institutional Bias" value={smc?.summary?.trend} color={smc?.summary?.trend === 'bullish' ? 'green' : smc?.summary?.trend === 'bearish' ? 'red' : 'amber'} />
            <StatCard label="Zone Position" value={smc?.premiumDiscount?.position} color={smc?.premiumDiscount?.position === 'premium' ? 'red' : smc?.premiumDiscount?.position === 'discount' ? 'green' : 'amber'} sub={`Ratio ${smc?.premiumDiscount?.ratio}`} />
            <StatCard label="Session" value={smc?.session} sub={`Kill Zone: ${smc?.killZone ? 'YES' : 'no'}`} />
            <StatCard label="Price" value={smc?.summary?.price?.toFixed(5)} />
          </div>

          <div style={{ height: 16 }} />
          <div className="grid grid-3">
            <Panel title="Liquidity Pools" sub="Buy-side & sell-side liquidity">
              {(smc?.liquidity || []).map((l, i) => (
                <div key={i} className="list-item" style={{ padding: '6px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <span className={l.type === 'buy-side' ? 'green' : 'red'} style={{ fontWeight: 600, fontSize: 12 }}>
                      {l.type === 'buy-side' ? '▲' : '▼'} {l.type}
                    </span>
                    <div className="muted" style={{ fontSize: 10 }}>{l.price?.toFixed(4)} · {l.distance?.toFixed(2)}% away</div>
                  </div>
                  <Meter label="" value={l.strength} pct={l.strength * 10} color={l.type === 'buy-side' ? 'var(--green)' : 'var(--red)'} />
                </div>
              ))}
            </Panel>

            <Panel title="Order Blocks" sub="Institutional order flow">
              {(smc?.orderBlocks || []).map((ob, i) => (
                <div key={i} className="list-item">
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span className={ob.type === 'bullish' ? 'green' : 'red'} style={{ fontWeight: 600, fontSize: 12 }}>{ob.type === 'bullish' ? 'Bullish OB' : 'Bearish OB'}</span>
                    <Badge type={ob.type === 'bullish' ? 'buy' : 'sell'}>{ob.type}</Badge>
                  </div>
                  <div className="muted" style={{ fontSize: 10.5 }}>Zone: {ob.zone?.[0]?.toFixed(4)} – {ob.zone?.[1]?.toFixed(4)}</div>
                </div>
              ))}
            </Panel>

            <Panel title="Fair Value Gaps (FVG)" sub="Imbalances">
              {(smc?.fvgs || []).map((f, i) => (
                <div key={i} className="list-item">
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span className={f.type === 'bullish' ? 'green' : 'red'} style={{ fontWeight: 600, fontSize: 12 }}>{f.type === 'bullish' ? 'Bullish FVG' : 'Bearish FVG'}</span>
                    <span className="muted" style={{ fontSize: 11 }}>{f.size?.toFixed(5)} size</span>
                  </div>
                  <div className="muted" style={{ fontSize: 10.5 }}>Zone: {f.zone?.[0]?.toFixed(4)} – {f.zone?.[1]?.toFixed(4)}</div>
                </div>
              ))}
            </Panel>
          </div>

          <div style={{ height: 16 }} />
          <div className="grid grid-2">
            <Panel title="Market Structure" sub="BOS · CHoCH · HH HL LH LL">
              {(smc?.structure || []).map((s, i) => (
                <div key={i} className="list-item" style={{ padding: '4px 0', display: 'flex', justifyContent: 'space-between', fontSize: 11.5 }}>
                  <span>{s.type === 'swingHigh' ? 'Swing High' : 'Swing Low'}</span>
                  <span className="muted">{s.price?.toFixed(4)}</span>
                </div>
              ))}
              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                {smc?.bos && <Badge type="info">BOS: {smc.bos.direction}</Badge>}
                {smc?.choch && <Badge type="warning">CHoCH: {smc.choch.direction}</Badge>}
              </div>
            </Panel>
            <Panel title="Mitigation & Kill Zones" sub="Price reaching key zones">
              <div className="kv">
                <dt>BOS</dt><dd>{smc?.bos ? `${smc.bos.type} ${smc.bos.direction} @ ${smc.bos.price?.toFixed(4)}` : '—'}</dd>
                <dt>CHoCH</dt><dd>{smc?.choch ? `${smc.choch.type} ${smc.choch.direction} @ ${smc.choch.price?.toFixed(4)}` : '—'}</dd>
                <dt>Kill Zone Active</dt><dd className={smc?.killZone ? 'green' : 'muted'}>{smc?.killZone ? 'Yes' : 'No'}</dd>
                <dt>Mitigated Zones</dt><dd>{(smc?.mitigation || []).length}</dd>
              </div>
              <div style={{ marginTop: 10 }}>
                <Meter label="Institutional Volume" value={smc?.killZone ? 'HIGH' : 'LOW'} pct={smc?.killZone ? 80 : 30} color="var(--purple)" />
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
