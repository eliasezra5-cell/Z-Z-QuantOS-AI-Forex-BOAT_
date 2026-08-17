import { useState, useMemo } from 'react';
import { useFetch } from '../api.js';
import { Panel, Badge, Loading, Meter, StatCard } from '../components/ui.jsx';
import CandleChart from '../components/CandleChart.jsx';
import ProposedExecutionZone from '../components/ProposedExecutionZone.jsx';
import ProIndicatorsSection from '../components/ProIndicatorsSection.jsx';
import { SYMBOL_LIST, useSymbol } from '../symbols.jsx';

const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1'];

export default function Technical() {
  const { symbol, setSymbol } = useSymbol();
  const [tf, setTf] = useState('H1');
  const { data: mtf } = useFetch(`/technical/multitimeframe/${symbol}`, [symbol]);
  const { data: confluence } = useFetch(`/technical/confluence/${symbol}`, [symbol]);
  const { data: indicators, loading: iLoad } = useFetch(`/technical/indicators/${symbol}?timeframe=${tf}`, [symbol, tf]);
  const { data: candles } = useFetch(`/market/candles/${symbol}?timeframe=${tf}&count=150`, [symbol, tf]);
  const layer = mtf?.layers?.[tf];
  const emaLayers = useMemo(() => {
    if (!candles) return {};
    const closes = candles.map((c) => c.close);
    return {
      ema20: ema(closes, 20),
      ema50: ema(closes, 50)
    };
  }, [candles]);

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Enterprise Technical Analysis Engine</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {SYMBOL_LIST.map(([s]) => <option key={s}>{s}</option>)}
          </select>
          <select value={tf} onChange={(e) => setTf(e.target.value)}>
            {TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}
          </select>
        </div>
      </div>

      <div className="grid grid-4">
        <StatCard label="Price" value={layer?.price?.toFixed(5) ?? '…'} />
        <StatCard label="Trend" value={layer?.priceAction?.trend ?? '…'} color={layer?.priceAction?.trend === 'bullish' ? 'green' : layer?.priceAction?.trend === 'bearish' ? 'red' : 'amber'} sub={`Structure ${layer?.priceAction?.latestStructure || '—'}`} />
        <StatCard label="RSI (14)" value={indicators?.rsi14?.toFixed(1) ?? '…'} color={indicators?.rsi14 > 70 ? 'red' : indicators?.rsi14 < 30 ? 'green' : 'amber'} sub={indicators?.rsi14 > 70 ? 'Overbought' : indicators?.rsi14 < 30 ? 'Oversold' : 'Neutral'} />
        <StatCard label="ATR (14)" value={indicators?.atr14?.toFixed(5) ?? '…'} sub="Volatility" />
      </div>

      <div style={{ height: 16 }} />

      <div className="grid grid-3">
        <Panel title={`${symbol} ${tf} · Price Action + Indicators`} sub="EMA 20/50 overlay" style={{ gridColumn: 'span 2' }}>
          {candles ? <CandleChart candles={candles} height={300} indicators={emaLayers} /> : <Loading />}
        </Panel>
        <Panel title="Signal Layers" sub="Multi-factor confluence">
          {layer?.signal ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="muted">Overall</span>
                <Badge type={layer.signal.direction}>{layer.signal.direction.toUpperCase()}</Badge>
                <span style={{ marginLeft: 'auto', fontWeight: 700 }}>{Math.round(layer.signal.strength * 100)}%</span>
              </div>
              {layer.signal.reasons.map((r) => <div key={r} className="muted" style={{ fontSize: 11 }}>• {r}</div>)}
            </div>
          ) : <div className="empty">Not enough data</div>}
        </Panel>
      </div>

      <div style={{ height: 16 }} />

      <div className="grid grid-3">
        <Panel title="Momentum Indicators">
          <Meter label="RSI 14" value={fmt(indicators?.rsi14)} pct={indicators?.rsi14} color={indicators?.rsi14 > 70 ? 'var(--red)' : indicators?.rsi14 < 30 ? 'var(--green)' : 'var(--accent)'} />
          <Meter label="MFI 14" value={fmt(indicators?.mfi14)} pct={indicators?.mfi14} color="var(--purple)" />
          <Meter label="Stochastic %K" value={fmt(indicators?.stochastic?.k?.slice(-1)[0])} pct={indicators?.stochastic?.k?.slice(-1)[0]} color="var(--blue)" />
          <Meter label="CCI 20" value={fmt(indicators?.cci20)} pct={50 + (indicators?.cci20 || 0)} color="var(--amber)" />
          <Meter label="ROC 12" value={fmt(indicators?.roc12)} pct={50 + (indicators?.roc12 || 0)} color="var(--accent)" />
        </Panel>
        <Panel title="Trend & Volatility">
          <Meter label="ADX 14" value={fmt(indicators?.adx)} pct={indicators?.adx} color="var(--accent)" />
          <Meter label="CMF 20" value={fmt(indicators?.cmf20)} pct={50 + (indicators?.cmf20 || 0) * 50} color="var(--green)" />
          <Meter label="VWAP Position" value="—" pct={50} color="var(--blue)" />
          <div className="kv" style={{ marginTop: 8 }}>
            <dt>EMA 20 / 50 / 200</dt><dd>{fmt(indicators?.ema20)} / {fmt(indicators?.ema50)} / {fmt(indicators?.ema200)}</dd>
            <dt>SMA 20 / 50</dt><dd>{fmt(indicators?.sma20)} / {fmt(indicators?.sma50)}</dd>
            <dt>BB Upper / Mid / Lower</dt><dd>{fmt(indicators?.bollinger?.upper)} / {fmt(indicators?.bollinger?.middle)} / {fmt(indicators?.bollinger?.lower)}</dd>
            <dt>SuperTrend</dt><dd>{indicators?.superTrend ? `${indicators.superTrend.trend > 0 ? 'Bull' : 'Bear'} ${fmt(indicators.superTrend.value)}` : '—'}</dd>
          </div>
        </Panel>
        <Panel title="Candlestick Patterns" sub="60+ pattern library">
          {layer?.candlesticks?.length ? layer.candlesticks.map((p) => (
            <div key={p.id} className="list-item" style={{ padding: '6px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <span style={{ fontWeight: 600 }}>{p.name}</span>
                <div className="muted" style={{ fontSize: 10 }}>Reliability {p.reliability}</div>
              </div>
              <Badge type={p.type}>{p.type}</Badge>
            </div>
          )) : <div className="empty">No patterns on current bar</div>}
        </Panel>
      </div>

      <div style={{ height: 16 }} />

      <Panel title="Multi-Timeframe Alignment" sub="M1 → W1 institutional hierarchy">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1'].map((t) => {
            const l = mtf?.layers?.[t];
            return (
              <div key={t} className={`stat-card ${l?.signal?.direction === 'buy' ? 'green' : l?.signal?.direction === 'sell' ? 'red' : ''}`} style={{ flex: 1, minWidth: 90, textAlign: 'center', borderColor: l?.signal?.direction === 'buy' ? 'var(--green)' : l?.signal?.direction === 'sell' ? 'var(--red)' : 'var(--border)' }}>
                <div style={{ fontWeight: 800, fontSize: 15 }}>{t}</div>
                <div style={{ fontSize: 10.5, textTransform: 'uppercase', opacity: 0.8 }}>{l?.signal?.direction || '—'}</div>
              </div>
            );
          })}
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 16, alignItems: 'center' }}>
          <span>Overall Bias: <Badge type={mtf?.bias}>{mtf?.bias}</Badge></span>
          <span className="muted">Bullish TFs: {mtf?.alignment?.bullCount} · Bearish TFs: {mtf?.alignment?.bearCount}</span>
          <span className="muted">Alignment: {mtf?.summary?.alignmentRatio ? Math.round(mtf.summary.alignmentRatio * 100) + '%' : '—'}</span>
        </div>
      </Panel>

      <div style={{ height: 16 }} />

      <div className="grid grid-3">
        <Panel title="Confluence Matrix" sub="Per-timeframe factor convergence (0-100)" style={{ gridColumn: 'span 2' }}>
          {confluence ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {confluence.timeframes.length ? confluence.timeframes.map((t) => (
                <div key={t.timeframe} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ width: 38, fontWeight: 700, fontSize: 12 }}>{t.timeframe}</span>
                  <Badge type={t.direction}>{t.direction.toUpperCase()}</Badge>
                  <Meter label="" value={`${t.confluence}`} pct={t.confluence}
                    color={t.confluence >= 70 ? 'var(--green)' : t.confluence >= 40 ? 'var(--amber)' : 'var(--red)'} />
                  <span className="muted" style={{ fontSize: 10.5, width: 70, textAlign: 'right' }}>
                    agree {Math.round(t.agreement * 100)}%
                  </span>
                </div>
              )) : <div className="empty">Not enough data</div>}
            </div>
          ) : <Loading />}
        </Panel>
        <Panel title="Composite Confluence" sub="All timeframes">
          {confluence ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
              <div style={{ fontWeight: 800, fontSize: 40, color: confluence.composite >= 70 ? 'var(--green)' : confluence.composite >= 40 ? 'var(--amber)' : 'var(--red)' }}>
                {confluence.composite}
              </div>
              <Badge type={confluence.bias}>{confluence.bias}</Badge>
              <div className="muted" style={{ fontSize: 11 }}>
                Bullish TFs {confluence.bullCount} · Bearish TFs {confluence.bearCount} · {confluence.timeframesAnalyzed} analyzed
              </div>
              <Meter label="" value="" pct={confluence.composite}
                color={confluence.composite >= 70 ? 'var(--green)' : confluence.composite >= 40 ? 'var(--amber)' : 'var(--red)'} />
            </div>
          ) : <Loading />}
        </Panel>
      </div>

      <div style={{ height: 16 }} />

      <ProposedExecutionZone />

      <div style={{ height: 16 }} />

      <ProIndicatorsSection symbol={symbol} timeframe={tf} />
    </div>
  );
}

function fmt(v) { return v == null ? '—' : Number(v).toFixed(1); }

function ema(values, period) {
  const out = [];
  const k = 2 / (period + 1);
  let prev = null;
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) { out.push(null); continue; }
    if (prev === null) {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) sum += values[j];
      prev = sum / period;
    } else {
      prev = values[i] * k + prev * (1 - k);
    }
    out.push(prev);
  }
  return out;
}
