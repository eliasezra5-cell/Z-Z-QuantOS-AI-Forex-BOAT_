import { useEffect, useRef } from 'react';

const TV_SYMBOLS = {
  EURUSD: 'FX:EURUSD',
  GBPUSD: 'FX:GBPUSD',
  USDJPY: 'FX:USDJPY',
  XAUUSD: 'OANDA:XAUUSD',
  BTCUSD: 'COINBASE:BTCUSD',
  ETHUSD: 'COINBASE:ETHUSD',
  US500: 'FOREXCOM:SPX500',
  NAS100: 'FOREXCOM:US100',
  US30: 'FOREXCOM:DJ30',
  WTI: 'NYMEX:CL1!',
  AAPL: 'NASDAQ:AAPL',
  TSLA: 'NASDAQ:TSLA'
};

const TV_INTERVALS = {
  M1: '1', M5: '5', M15: '15', M30: '30', H1: '60', H4: '240', D1: 'D', W1: 'W'
};

function tvSymbol(symbol) {
  return TV_SYMBOLS[symbol] || `FX:${symbol}`;
}

function tvInterval(timeframe) {
  return TV_INTERVALS[timeframe] || TV_INTERVALS.H1;
}

export default function TradingViewChart({ symbol = 'XAUUSD', timeframe = 'H1', height = 480, onSymbolChange }) {
  const containerRef = useRef(null);
  const idRef = useRef(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    container.innerHTML = '';
    if (!idRef.current) idRef.current = `tv_${Math.random().toString(36).slice(2, 10)}`;
    const widgetDiv = document.createElement('div');
    widgetDiv.id = idRef.current;
    widgetDiv.style.width = '100%';
    widgetDiv.style.height = '100%';
    container.appendChild(widgetDiv);

    const buildWidget = () => {
      if (!window.TradingView || !window.TradingView.widget) return;
      const widget = new window.TradingView.widget({
        autosize: true,
        symbol: tvSymbol(symbol),
        interval: tvInterval(timeframe),
        timezone: 'Etc/UTC',
        theme: 'dark',
        style: '1',
        locale: 'en',
        hide_top_toolbar: false,
        allow_symbol_change: true,
        calendar: false,
        withdateranges: true,
        support_host: 'https://www.tradingview.com',
        container_id: idRef.current,
        onChartReady: () => {
          try {
            const chart = widget.chart && widget.chart();
            if (chart && typeof chart.onSymbolChange === 'function') {
              chart.onSymbolChange().subscribe((s) => {
                const raw = String(s.symbol || '').split(':').pop().toUpperCase();
                const mapped = Object.keys(TV_SYMBOLS).find((k) => TV_SYMBOLS[k].toLowerCase() === String(s.symbol || '').toLowerCase());
                if (onSymbolChange) onSymbolChange(mapped || raw);
              });
            }
          } catch (e) { /* widget symbol event unavailable - dropdown still syncs globally */ }
        }
      });
    };

    if (window.TradingView && window.TradingView.widget) {
      buildWidget();
    } else {
      const script = document.createElement('script');
      script.type = 'text/javascript';
      script.async = true;
      script.src = 'https://s3.tradingview.com/tv.js';
      script.onload = buildWidget;
      document.head.appendChild(script);
    }

    return () => {
      container.innerHTML = '';
    };
  }, [symbol, timeframe, onSymbolChange]);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height }}
      className="tradingview-widget-container"
    />
  );
}
