import { useFetch } from '../api.js';
import { Panel, Badge, Loading, Meter, Sparkline, StatCard } from '../components/ui.jsx';
import OfficialSources from '../components/OfficialSources.jsx';

export default function Macro() {
  const { data: macro, loading } = useFetch('/macro/overview');
  const { data: corr } = useFetch('/macro/correlations');

  return (
    <div>
      <div className="page-head"><div className="section-title">Macro Intelligence</div></div>
      {loading ? <Loading /> : (
        <>
          <div className="grid grid-4">
            <StatCard label="Dollar Index (DXY)" value={macro?.dollarIndex?.slice(-1)[0]} color="blue" sub={<Sparkline data={macro?.dollarIndex} color="var(--blue)" />} />
            <StatCard label="US 10Y Yield" value={`${macro?.bondYields?.us10y}%`} color="amber" sub="Treasury benchmark" />
            <StatCard label="VIX" value={macro?.indicators?.vix?.toFixed(1)} color={macro?.indicators?.vix > 20 ? 'red' : 'green'} sub="Volatility index" />
            <StatCard label="Risk Regime" value={macro?.riskOn ? 'Risk-On' : 'Risk-Off'} color={macro?.riskOn ? 'green' : 'red'} sub="Global risk appetite" />
          </div>

          <div style={{ height: 16 }} />
          <div className="grid grid-3">
            <Panel title="Bond Yields" sub="Global yield curve">
              {Object.entries(macro?.bondYields || {}).map(([k, v]) => (
                <Meter key={k} label={k.toUpperCase()} value={`${v}%`} pct={(v / 5) * 100} color="var(--amber)" />
              ))}
            </Panel>

            <Panel title="Cross-Asset Correlations" sub="Hedge fund correlation matrix">
              {Object.entries(corr || {}).slice(0, 8).map(([a, map]) => {
                const target = Object.entries(map).find(([b]) => b !== a);
                return (
                  <div key={a} className="list-item" style={{ padding: '6px 0', display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ fontWeight: 600 }}>{a}</span>
                    <span>→ {target?.[0]}</span>
                    <span className={target?.[1] > 0 ? 'green' : 'red'}>{target?.[1]}</span>
                  </div>
                );
              })}
            </Panel>

            <Panel title="Global Economy" sub="Central bank policy matrix">
              <div className="kv">
                <dt>Fed Funds</dt><dd>{macro?.global?.fedFunds}%</dd>
                <dt>ECB Rate</dt><dd>{macro?.global?.ecbRate}%</dd>
                <dt>BOJ Rate</dt><dd>{macro?.global?.bojRate}%</dd>
                <dt>BOE Rate</dt><dd>{macro?.global?.boeRate}%</dd>
                <dt>Growth 2026</dt><dd>{macro?.global?.growthForecast2026}%</dd>
                <dt>Inflation Forecast</dt><dd>{macro?.global?.inflationForecast}%</dd>
              </div>
            </Panel>
          </div>

          <div style={{ height: 16 }} />
          <div className="grid grid-2">
            <Panel title="Market Indicators">
              <Meter label="Market Breadth" value={`${macro?.indicators?.marketBreadth?.toFixed(0)}%`} pct={macro?.indicators?.marketBreadth} color="var(--accent)" />
              <Meter label="Recession Probability" value={`${macro?.indicators?.recessionProbability?.toFixed(0)}%`} pct={macro?.indicators?.recessionProbability} color="var(--red)" />
              <Meter label="Global M2 Growth" value={`${macro?.indicators?.globalM2Growth?.toFixed(1)}%`} pct={macro?.indicators?.globalM2Growth * 10} color="var(--purple)" />
            </Panel>
            <Panel title="Macro Signals Summary">
              <div className="kv">
                <dt>DXY Trend</dt><dd>{macro?.dollarIndex?.slice(-1)[0] > macro?.dollarIndex?.slice(-5, -1).reduce((a, b) => a + b, 0) / 4 ? 'Strengthening' : 'Weakening'}</dd>
                <dt>Gold Correlation</dt><dd className="red">{corr?.['XAUUSD']?.['EURUSD'] ?? -0.82}</dd>
                <dt>Crypto Correlation</dt><dd className="green">{corr?.['BTCUSD']?.['US500'] ?? 0.65}</dd>
                <dt>Regime</dt><dd className={macro?.riskOn ? 'green' : 'red'}>{macro?.riskOn ? 'Growth / Risk-On' : 'Defensive / Risk-Off'}</dd>
              </div>
            </Panel>
          </div>

          <div style={{ height: 16 }} />
          <OfficialSources />
        </>
      )}
    </div>
  );
}
