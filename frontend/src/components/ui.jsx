import React from 'react';

export function StatCard({ label, value, sub, color = '', icon }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{icon && <span style={{ marginRight: 6 }}>{icon}</span>}{label}</div>
      <div className={`stat-value ${color}`}>{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export function Panel({ title, sub, children, className = '', style }) {
  return (
    <div className={`panel ${className}`} style={style}>
      <div className="panel-title"><span>{title}</span>{sub && <span className="sub">{sub}</span>}</div>
      {children}
    </div>
  );
}

export function Badge({ type, children }) {
  return <span className={`badge ${type || 'info'}`}>{children}</span>;
}

export function Bar({ pct, color = 'var(--accent)' }) {
  return (
    <div className="bar"><div className="bar-fill" style={{ width: `${Math.min(Math.max(pct, 0), 100)}%`, background: color }} /></div>
  );
}

export function Meter({ label, value, pct, color }) {
  return (
    <div className="meter-row">
      <span className="meter-label">{label}</span>
      <div style={{ flex: 1 }}><Bar pct={pct} color={color} /></div>
      <span className="meter-val">{value}</span>
    </div>
  );
}

export function Sparkline({ data, color = 'var(--accent)', height = 40 }) {
  if (!data || data.length < 2) return <div className="spark" style={{ height }} />;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  return (
    <div className="spark" style={{ height }}>
      {data.map((v, i) => (
        <div key={i} className="spark-bar" style={{ height: `${((v - min) / range) * 100}%`, background: color }} />
      ))}
    </div>
  );
}

export function Loading() {
  return <div className="empty">Loading data...</div>;
}

export function ErrorMsg({ msg }) {
  return <div className="empty" style={{ color: 'var(--red)' }}>Error: {msg}</div>;
}

export function Empty({ text = 'No data available' }) {
  return <div className="empty">{text}</div>;
}

export function KeyValue({ rows }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <React.Fragment key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}
