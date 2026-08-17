import { useRef, useEffect } from 'react';

export default function CandleChart({ candles, height = 280, indicators = {} }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !candles?.length) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    const data = candles.slice(-120);
    const pad = 8;
    const min = Math.min(...data.map((c) => c.low)) * 0.999;
    const max = Math.max(...data.map((c) => c.high)) * 1.001;
    const range = max - min || 1;
    const step = (w - pad * 2) / data.length;
    const y = (p) => pad + (max - p) / range * (h - pad * 2);

    const emaVals = [];
    if (indicators.ema20 && indicators.ema20.length === data.length) emaVals.push({ arr: indicators.ema20, color: '#22d3ee' });
    if (indicators.ema50 && indicators.ema50.length === data.length) emaVals.push({ arr: indicators.ema50, color: '#fbbf24' });

    for (const { arr, color } of emaVals) {
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      let started = false;
      arr.forEach((v, i) => {
        if (v == null) return;
        const x = pad + i * step + step / 2;
        const yy = y(v);
        if (!started) { ctx.moveTo(x, yy); started = true; }
        else ctx.lineTo(x, yy);
      });
      ctx.stroke();
    }

    data.forEach((c, i) => {
      const x = pad + i * step + step / 2;
      const wick = Math.max(1, step * 0.15);
      ctx.strokeStyle = c.close >= c.open ? '#34d399' : '#f87171';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, y(c.high));
      ctx.lineTo(x, y(c.low));
      ctx.stroke();
      ctx.fillStyle = c.close >= c.open ? 'rgba(52,211,153,0.75)' : 'rgba(248,113,113,0.75)';
      const top = y(Math.max(c.open, c.close));
      const bh = Math.max(1, Math.abs(y(c.open) - y(c.close)));
      ctx.fillRect(x - wick, top, wick * 2, bh);
    });

    ctx.strokeStyle = 'rgba(138,151,179,0.25)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const yy = pad + i * (h - pad * 2) / 4;
      ctx.beginPath();
      ctx.moveTo(0, yy);
      ctx.lineTo(w, yy);
      ctx.stroke();
      const val = max - range * i / 4;
      ctx.fillStyle = 'rgba(138,151,179,0.7)';
      ctx.font = '10px monospace';
      ctx.fillText(val.toFixed(val < 10 ? 4 : 2), 2, yy - 3);
    }
  }, [candles, indicators, height]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: '100%', height }}
      className="candle-chart"
    />
  );
}

export function Donut({ pct, label, color = 'var(--accent)', size = 90 }) {
  const r = size / 2 - 8;
  const circ = 2 * Math.PI * r;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--bg3)" strokeWidth="10" fill="none" />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          stroke={color} strokeWidth="10" fill="none"
          strokeDasharray={`${(pct / 100) * circ} ${circ}`}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" fill="var(--text)" fontSize="16" fontWeight="700">
          {Math.round(pct)}%
        </text>
      </svg>
      <div style={{ fontSize: 11, color: 'var(--muted)' }}>{label}</div>
    </div>
  );
}
