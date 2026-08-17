import { useState } from 'react';
import { useFetch, post } from '../api.js';
import { Panel, Badge, StatCard, Bar } from '../components/ui.jsx';

const CORE_AGENTS = [
  { name: 'News Analysis Agent', weight: 0.40, desc: 'News-driven directional vote · 40%' },
  { name: 'Historical Pattern Agent', weight: 0.20, desc: 'Historical pattern match vote · 20%' },
  { name: 'Macro Analysis Agent', weight: 0.20, desc: 'Macro regime directional vote · 20%' },
  { name: 'Technical Execution Agent', weight: 0.20, desc: 'Entry / execution quality · 20%' },
  { name: 'Risk Manager Agent', weight: 0.0, desc: 'Veto power · no directional weight' }
];

const BUILTIN_CUSTOM_AGENTS = [
  { name: 'Social Sentiment Agent', id: 'custom-sentiment', weight: 0.10, desc: 'Real-time social sentiment vote · custom pool (≤20% combined)' },
  { name: 'Fundamentals Analysis Agent', id: 'custom-fundamentals', weight: 0.10, desc: 'Economic-calendar fundamentals vote · custom pool (≤20% combined)' }
];

const PROVIDERS = [
  { value: 'free_local', label: 'Free local (no key needed)' },
  { value: 'paid_openai', label: 'OpenAI (GPT)' },
  { value: 'paid_anthropic', label: 'Anthropic (Claude)' },
  { value: 'paid_gemini', label: 'Google (Gemini)' },
  { value: 'paid_deepseek', label: 'DeepSeek' },
  { value: 'xai', label: 'xAI (Grok)' },
  { value: 'dashscope', label: 'Qwen via DashScope (International)' },
  { value: 'dashscope-cn', label: 'Qwen via DashScope (China)' },
  { value: 'zhipu', label: 'z.ai / GLM (International)' },
  { value: 'minimax', label: 'MiniMax (Global)' },
  { value: 'minimax-cn', label: 'MiniMax (China)' },
  { value: 'nvidia', label: 'NVIDIA (NIM) — free tier' },
  { value: 'custom_http', label: 'Custom HTTP (OpenAI-compatible)' }
];
const PROVIDER_LABEL = (v) => PROVIDERS.find((p) => p.value === v)?.label || v || 'free_local';
const EMPTY_FORM = { name: '', provider_type: 'free_local', model_name: '', system_prompt: '', voting_weight: 10, api_key: '', base_url: '' };

export default function Agents() {
  const { data: list, refresh } = useFetch('/agents');
  const { data: modelStatus, loading: modelsLoading, refresh: refreshModels } = useFetch('/system/ai/models/status');
  const custom = list?.agents || [];
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);

  // Real pipeline output: the custom pool weight that was actually used in the
  // last consensus. Built-in sentiment + fundamentals are wired in the decision
  // pipeline, so they only show here — never in the user CRUD /agents list.
  const { data: analysis } = useFetch('/ai/analyze/XAUUSD');
  const customScores = (analysis?.agentScores || []).filter((a) => String(a.agent_id || '').startsWith('custom-'));
  const customUsedPct = customScores
    .filter((a) => String(a.abstention || 'TRADE').toUpperCase() === 'TRADE')
    .reduce((s, a) => s + (Number(a.weight) || 0), 0) * 100;
  const customState = (id) => {
    const a = customScores.find((x) => x.agent_id === id);
    return a ? String(a.abstention || 'TRADE').toUpperCase() : null;
  };

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const customWeightPct = custom.reduce((s, a) => s + (Number(a.voting_weight) || 0), 0) * 100;

  const create = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const res = await post('/agents', {
        name: form.name.trim(),
        provider_type: form.provider_type,
        model_name: form.model_name.trim(),
        system_prompt: form.system_prompt.trim(),
        voting_weight: (Number(form.voting_weight) || 0) / 100,
        api_key: form.api_key.trim(),
        base_url: form.base_url.trim()
      });
      setNotice(`Agent "${res.agent?.name || form.name.trim()}" created successfully`);
      setForm(EMPTY_FORM);
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const renderWeight = (weight, veto = false) => (
    <div className="meter-row" style={{ minWidth: 170 }}>
      <span className="meter-label">Weight</span>
      <div style={{ flex: 1 }}><Bar pct={veto ? 0 : weight * 100} color="var(--purple)" /></div>
      <span className="meter-val">{veto ? 'VETO' : `${(weight * 100).toFixed(0)}%`}</span>
    </div>
  );

  return (
    <div>
      <div className="page-head">
        <div className="section-title">AI Agents Management</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className="pill">Consensus: 80% news family · 20% execution + custom</span>
          <button className="btn btn-sm" onClick={refresh}>Refresh</button>
        </div>
      </div>

      <div className="grid grid-4">
        <StatCard label="Core Agents" value="5" color="blue" sub="News 40 · Hist 20 · Macro 20 · Tech 20 · Risk Veto" />
        <StatCard label="Signal Agents" value="2" color="purple" sub="Sentiment + Fundamentals (custom pool)" />
        <StatCard label="Custom Weight Used" value={`${customUsedPct.toFixed(0)}%`} color={customUsedPct > 20 ? 'red' : 'amber'} sub={`Pool cap 20% · ${customScores.length} built-in custom agents in last consensus`} />
        <StatCard label="Pipeline Status" value="Active" color="green" sub="Agents vote via asyncio.gather" />
      </div>

      <div style={{ height: 16 }} />

      <Panel title="Connected AI Models" sub="Which providers have API keys configured — brain (env) + dashboard custom agents">
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
          <button className="btn btn-sm" onClick={refreshModels}>Refresh</button>
          {modelsLoading && <span className="muted" style={{ fontSize: 11 }}>Loading…</span>}
        </div>
        {modelStatus ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 8 }}>
            {(modelStatus.providers || []).map((p) => (
              <div key={p.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1, overflow: 'hidden' }}>
                  <span style={{ fontWeight: 600, fontSize: 11.5 }}>{p.name}</span>
                  {p.model && <div className="muted" style={{ fontSize: 10 }}>{p.model}</div>}
                </div>
                <Badge type={p.connected ? 'buy' : 'neutral'}>{p.connected ? 'Connected' : 'No key'}</Badge>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty">No provider status available</div>
        )}
        {modelStatus && (modelStatus.customAgents || []).length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6 }}>Dashboard Custom Agents</div>
            {(modelStatus.customAgents || []).map((a) => (
              <div key={a.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1, overflow: 'hidden' }}>
                  <span style={{ fontWeight: 600, fontSize: 11.5 }}>{a.name}</span>
                  <div className="muted" style={{ fontSize: 10 }}>{PROVIDER_LABEL(a.providerType)} · {a.model}</div>
                </div>
                <Badge type={a.connected ? 'buy' : 'warning'}>{a.connected ? 'Key saved' : 'No key'}</Badge>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <div style={{ height: 16 }} />

      <div className="grid grid-2">
        <Panel title="Active Agents" sub={`${7 + custom.length} agents in the decision pipeline`}>
          {CORE_AGENTS.map((a) => (
            <div key={a.name} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
              <div style={{ flex: 1 }}>
                <span style={{ fontWeight: 600, fontSize: 12 }}>{a.name}</span>
                <span style={{ marginLeft: 6 }}><Badge type="purple">CORE</Badge></span>
                <div className="muted" style={{ fontSize: 10.5, marginTop: 2 }}>{a.desc}</div>
              </div>
              {renderWeight(a.weight, a.weight === 0)}
              <Badge type="buy">Active</Badge>
            </div>
          ))}
          {BUILTIN_CUSTOM_AGENTS.map((a) => {
            const state = customState(a.id);
            return (
              <div key={a.name} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <span style={{ fontWeight: 600, fontSize: 12 }}>{a.name}</span>
                  <span style={{ marginLeft: 6 }}><Badge type="info">SIGNAL</Badge></span>
                  <div className="muted" style={{ fontSize: 10.5, marginTop: 2 }}>{a.desc}</div>
                </div>
                {renderWeight(a.weight)}
                {state === 'TRADE'
                  ? <Badge type="buy">Active</Badge>
                  : <Badge type={state === 'PROVIDER_DEGRADED' ? 'warning' : 'neutral'}>{state || 'Pending'}</Badge>}
              </div>
            );
          })}
          {(custom || []).map((a) => (
            <div key={a.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
              <div style={{ flex: 1 }}>
                <span style={{ fontWeight: 600, fontSize: 12 }}>{a.name}</span>
                <span style={{ marginLeft: 6 }}><Badge type="info">CUSTOM</Badge></span>
                <div className="muted" style={{ fontSize: 10.5, marginTop: 2 }}>
                  {PROVIDER_LABEL(a.provider_type || a.providerType)} · {a.model_name || a.modelName || 'default'}
                  {a.base_url ? <span> · {a.base_url}</span> : null}
                </div>
              </div>
              {renderWeight(Number(a.voting_weight) || Number(a.votingWeight) || 0)}
              <Badge type={a.enabled ? 'buy' : 'neutral'}>{a.enabled ? 'Active' : 'Disabled'}</Badge>
            </div>
          ))}
          {custom.length === 0 && (
            <div className="empty">No custom agents yet — create one on the right.</div>
          )}
        </Panel>

        <Panel title="Add Custom Agent" sub="Weighted vote joins the 80% core consensus">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <label className="muted" style={{ fontSize: 11 }}>Name</label>
              <input type="text" placeholder="e.g. Gold Sentiment" value={form.name} onChange={set('name')} style={{ width: '100%' }} />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 11 }}>Provider Type</label>
              <select value={form.provider_type} onChange={set('provider_type')} style={{ width: '100%' }}>
                {PROVIDERS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
            </div>
            <div>
              <label className="muted" style={{ fontSize: 11 }}>Model Name</label>
              <input type="text" placeholder="e.g. gpt-4o" value={form.model_name} onChange={set('model_name')} style={{ width: '100%' }} />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 11 }}>System Prompt</label>
              <textarea rows={4} placeholder="System instructions for the agent..." value={form.system_prompt} onChange={set('system_prompt')} style={{ width: '100%', resize: 'vertical' }} />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 11 }}>Voting Weight: {form.voting_weight}% (0-20%)</label>
              <input type="range" min={0} max={20} step={1} value={form.voting_weight} onChange={set('voting_weight')} style={{ width: '100%' }} />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 11 }}>API Key {form.provider_type === 'free_local' ? '(optional — local fallback, no key)' : '(required by paid providers)'}</label>
              <input type="password" placeholder="sk-…" value={form.api_key} onChange={set('api_key')} style={{ width: '100%' }} />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 11 }}>Base URL (optional — koi bhi OpenAI-compatible endpoint)</label>
              <input type="text" placeholder="e.g. https://api.example.com/v1" value={form.base_url} onChange={set('base_url')} style={{ width: '100%' }} />
            </div>
            {error && <div className="empty" style={{ color: 'var(--red)', padding: 8 }}>Error: {error}</div>}
            {notice && <div className="empty" style={{ color: 'var(--green)', padding: 8 }}>{notice}</div>}
            <button className="btn btn-primary" onClick={create} disabled={saving || !form.name.trim()}>
              {saving ? 'Creating...' : 'Create Agent'}
            </button>
          </div>
        </Panel>
      </div>
    </div>
  );
}
