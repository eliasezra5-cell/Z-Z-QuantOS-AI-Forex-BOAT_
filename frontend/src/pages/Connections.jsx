import { useCallback, useEffect, useState } from 'react';
import { get, post } from '../api.js';
import { Panel, Badge, Loading, StatCard } from '../components/ui.jsx';

const MASK = '******';
const MASK_SENTINEL = '***';

const PROVIDERS = [
  { provider: 'whatsapp', name: 'WhatsApp', icon: '◈' },
  { provider: 'telegram', name: 'Telegram', icon: '✈' },
  { provider: 'email', name: 'Email (SMTP)', icon: '✉' },
  { provider: 'mt5', name: 'MetaTrader 5', icon: '⇄' }
];

export default function Connections() {
  const [statuses, setStatuses] = useState(null);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({
    whatsapp: { api_token: '', phone_number_id: '', webhook_secret: '' },
    telegram: { api_token: '', chat_id: '' },
    email: { host: '', port: '', user: '', password: '', from_addr: '', to_addr: '' }
  });
  const [toast, setToast] = useState(null);
  const [saving, setSaving] = useState(false);

  const loadConnections = useCallback(() => {
    get('/integrations/connections')
      .then((res) => {
        const list = res.connections || [];
        setStatuses(list);
        const byProvider = Object.fromEntries(list.map((c) => [c.provider, c]));
        setForm((prev) => ({
          ...prev,
          whatsapp: {
            ...prev.whatsapp,
            api_token: byProvider.whatsapp?.configured ? MASK : ''
          },
          telegram: {
            ...prev.telegram,
            api_token: byProvider.telegram?.configured ? MASK : '',
            chat_id: byProvider.telegram?.chat_id || ''
          },
          email: {
            ...prev.email,
            host: byProvider.email?.host || '',
            port: byProvider.email?.port || '',
            user: byProvider.email?.user || '',
            password: byProvider.email?.configured ? MASK : '',
            from_addr: byProvider.email?.from_addr || '',
            to_addr: byProvider.email?.to_addr || ''
          }
        }));
      })
      .catch((err) => showToast('error', `Failed to load connections: ${err.message}`))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadConnections();
  }, [loadConnections]);

  function showToast(type, message) {
    setToast({ type, message });
    window.clearTimeout(showToast._t);
    showToast._t = window.setTimeout(() => setToast(null), 5000);
  }

  function setField(provider, field, value) {
    setForm((prev) => ({ ...prev, [provider]: { ...prev[provider], [field]: value } }));
  }

  function payload(provider) {
    const body = {};
    for (const [field, value] of Object.entries(form[provider])) {
      if (!value) continue;
      body[field] = value === MASK ? MASK_SENTINEL : value;
    }
    return body;
  }

  async function handleSave() {
    const sends = [];
    for (const { provider } of PROVIDERS) {
      const body = payload(provider);
      if (Object.keys(body).length) {
        sends.push(post(`/integrations/connections?provider=${provider}`, body));
      }
    }
    if (!sends.length) {
      showToast('error', 'Nothing to save — fill at least one field.');
      return;
    }
    setSaving(true);
    try {
      await Promise.all(sends);
      showToast('success', 'Connections saved successfully');
      loadConnections();
    } catch (err) {
      showToast('error', `Save failed: ${err.message}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    const tests = PROVIDERS.map(({ provider }) => {
      const body = { provider };
      if (provider === 'telegram' && form.telegram.chat_id) body.chat_id = form.telegram.chat_id;
      return post('/integrations/connections/test', body)
        .then((r) => ({ provider, ok: r.result?.success, detail: r.result?.detail }))
        .catch((err) => ({ provider, ok: false, detail: err.message }));
    });
    const results = await Promise.all(tests);
    const lines = results.map((r) => `${r.provider}: ${r.ok ? 'OK' : 'FAIL'} — ${r.detail || 'n/a'}`);
    const allOk = results.every((r) => r.ok);
    showToast(allOk ? 'success' : 'error', lines.join(' · '));
  }

  const statusOf = (provider) => (statuses || []).find((c) => c.provider === provider);

  return (
    <div>
      <div className="page-head">
        <div className="section-title">Connections &amp; Integrations</div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn" onClick={handleTest}>Test Connection</button>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>{saving ? 'Saving…' : 'Save Connections'}</button>
        </div>
      </div>

      <div className="grid grid-4">
        {PROVIDERS.map(({ provider, name, icon }) => {
          const s = statusOf(provider);
          return (
            <StatCard
              key={provider}
              label={name}
              icon={icon}
              value={<Badge type={s?.configured ? 'buy' : 'neutral'}>{s?.configured ? 'Configured' : 'Not configured'}</Badge>}
              sub={s ? `Type: ${s.type}${s.isActive ? ' · Active' : ''}` : '…'}
            />
          );
        })}
        <StatCard label="Status" value={loading ? 'Loading' : `${(statuses || []).length} provider(s)`} sub="WhatsApp · Telegram · Email · MT5" />
      </div>

      <div style={{ height: 16 }} />
      <div className="grid grid-2">
        <Panel title="Telegram" sub="Telegram Bot Token + Chat ID">
          <Field
            label="Bot Token"
            type="password"
            value={form.telegram.api_token}
            placeholder={statusOf('telegram')?.configured ? MASK : '123456:ABC-DEF…'}
            onChange={(v) => setField('telegram', 'api_token', v)}
            note={statusOf('telegram')?.configured ? 'Leave as-is to keep the existing token.' : undefined}
          />
          <Field
            label="Chat ID"
            value={form.telegram.chat_id}
            placeholder="123456789 (use @userinfobot to find yours)"
            onChange={(v) => setField('telegram', 'chat_id', v)}
            note="The recipient chat the bot sends test messages and alerts to."
          />
        </Panel>

        <Panel title="WhatsApp" sub="Meta Cloud API credentials">
          <Field
            label="API Token"
            type="password"
            value={form.whatsapp.api_token}
            placeholder={statusOf('whatsapp')?.configured ? MASK : 'EAAG…'}
            onChange={(v) => setField('whatsapp', 'api_token', v)}
            note={statusOf('whatsapp')?.configured ? 'Leave as-is to keep the existing token.' : undefined}
          />
          <Field
            label="Phone Number ID"
            value={form.whatsapp.phone_number_id}
            placeholder="123456789012345"
            onChange={(v) => setField('whatsapp', 'phone_number_id', v)}
          />
          <Field
            label="Webhook Verify Token"
            type="password"
            value={form.whatsapp.webhook_secret}
            placeholder="verify-token"
            onChange={(v) => setField('whatsapp', 'webhook_secret', v)}
          />
        </Panel>
      </div>

      <div style={{ height: 16 }} />
      <div className="grid grid-2">
        <Panel title="Email (SMTP)" sub="SMTP credentials for alert & report delivery">
          <Field
            label="SMTP Host"
            value={form.email.host}
            placeholder="smtp.gmail.com"
            onChange={(v) => setField('email', 'host', v)}
          />
          <Field
            label="SMTP Port"
            value={form.email.port}
            placeholder="587"
            onChange={(v) => setField('email', 'port', v)}
          />
          <Field
            label="SMTP Username"
            value={form.email.user}
            placeholder="you@yourdomain.com"
            onChange={(v) => setField('email', 'user', v)}
          />
          <Field
            label="SMTP Password"
            type="password"
            value={form.email.password}
            placeholder={statusOf('email')?.configured ? MASK : 'app-password'}
            onChange={(v) => setField('email', 'password', v)}
            note={statusOf('email')?.configured ? 'Leave as-is to keep the existing password.' : undefined}
          />
          <Field
            label="From Address"
            value={form.email.from_addr}
            placeholder="quantos@yourdomain.com"
            onChange={(v) => setField('email', 'from_addr', v)}
          />
          <Field
            label="To Address (recipient)"
            value={form.email.to_addr}
            placeholder="you@yourdomain.com"
            onChange={(v) => setField('email', 'to_addr', v)}
            note="The mailbox alerts and reports are delivered to."
          />
        </Panel>
      </div>

      {toast && (
        <div
          style={{
            position: 'fixed',
            right: 20,
            bottom: 20,
            zIndex: 100,
            maxWidth: 480,
            padding: '10px 14px',
            borderRadius: 8,
            fontSize: 12,
            background: 'var(--bg3)',
            border: `1px solid ${toast.type === 'success' ? 'var(--green)' : 'var(--red)'}`,
            color: toast.type === 'success' ? 'var(--green)' : 'var(--red)',
            boxShadow: '0 4px 16px rgba(0,0,0,0.4)'
          }}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}

function Field({ label, value, onChange, type = 'text', placeholder = '', note }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label style={{ display: 'block', fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>{label}</label>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: '100%' }}
        autoComplete="off"
      />
      {note && <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 3 }}>{note}</div>}
    </div>
  );
}
