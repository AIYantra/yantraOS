import { useState, useEffect, useCallback } from 'react';
import { Save, RotateCcw, CheckCircle, XCircle, Eye, EyeOff } from 'lucide-react';

// ── Toast ─────────────────────────────────────────────────────────────────────

function Toast({ toast }) {
  if (!toast) return null;
  const isOk = toast.ok;
  return (
    <div className={`
      fixed bottom-6 right-6 z-50 flex items-center gap-3
      border px-4 py-3 font-mono text-xs
      transition-all duration-300
      ${isOk
        ? 'bg-emerald-950 border-emerald-700 text-emerald-300'
        : 'bg-red-950   border-red-700   text-red-300'
      }
    `}>
      {isOk
        ? <CheckCircle size={14} className="text-emerald-400" />
        : <XCircle    size={14} className="text-red-400" />
      }
      <span className="tracking-wide">{toast.message}</span>
    </div>
  );
}

// ── API Key field ─────────────────────────────────────────────────────────────

function ApiKeyField({ id, label, value, onChange }) {
  const [show, setShow] = useState(false);

  return (
    <div>
      <label htmlFor={id} className="block font-mono text-[10px] uppercase tracking-widest text-zinc-500 mb-1.5">
        {label}
      </label>
      <div className="flex">
        <input
          id={id}
          type={show ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete="off"
          placeholder="sk-…"
          className="
            flex-1 bg-zinc-900 border border-zinc-700 border-r-0
            px-3 py-2 font-mono text-xs text-zinc-200
            placeholder:text-zinc-700
            focus:outline-none focus:border-cyan-600
            transition-colors
          "
        />
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          aria-label={show ? 'Hide key' : 'Reveal key'}
          className="
            border border-zinc-700 bg-zinc-900 px-3
            text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800
            transition-colors
          "
        >
          {show ? <EyeOff size={13} /> : <Eye size={13} />}
        </button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const ROUTING_OPTIONS = [
  { value: 'LOCAL', label: 'LOCAL',  desc: 'On-device inference via Ollama / llama.cpp' },
  { value: 'CLOUD', label: 'CLOUD',  desc: 'Route inference to configured cloud API'     },
];

const INITIAL_FORM = {
  gemini_key:  '',
  openai_key:  '',
  routing:     'LOCAL',
  active_model: '',
};

export default function Settings() {
  const [form,    setForm]    = useState(INITIAL_FORM);
  const [loading, setLoading] = useState(true);
  const [saving,  setSaving]  = useState(false);
  const [toast,   setToast]   = useState(null);

  // ── Load initial config ──────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    async function fetchConfig() {
      try {
        const res  = await fetch('/api/config');
        const data = await res.json();
        if (cancelled) return;
        setForm({
          gemini_key:   data.api_keys?.GEMINI_API_KEY   ?? '',
          openai_key:   data.api_keys?.OPENAI_API_KEY   ?? '',
          routing:      data.inference?.routing          ?? 'LOCAL',
          active_model: data.inference?.active_model     ?? '',
        });
      } catch {
        if (!cancelled) showToast(false, 'Failed to load config from server');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchConfig();
    return () => { cancelled = true; };
  }, []);

  // ── Toast helpers ────────────────────────────────────────────────────────
  const showToast = useCallback((ok, message) => {
    setToast({ ok, message });
    setTimeout(() => setToast(null), 3500);
  }, []);

  // ── Submit ───────────────────────────────────────────────────────────────
  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    try {
      const body = {
        api_keys: {
          GEMINI_API_KEY: form.gemini_key,
          OPENAI_API_KEY: form.openai_key,
        },
        inference: {
          routing:      form.routing,
          active_model: form.active_model,
        },
      };
      const res = await fetch('/api/config', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error ?? `HTTP ${res.status}`);
      }
      const result = await res.json();
      showToast(true, `Saved: ${result.updated?.join(', ') || 'no changes'}`);
    } catch (err) {
      showToast(false, `Save failed — ${err.message}`);
    } finally {
      setSaving(false);
    }
  }

  // ── Reset ────────────────────────────────────────────────────────────────
  function handleReset() {
    setForm(INITIAL_FORM);
  }

  // ── Field helpers ────────────────────────────────────────────────────────
  function field(key) {
    return (val) => setForm((f) => ({ ...f, [key]: val }));
  }

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-zinc-950">
      {/* Header */}
      <header className="px-6 py-4 border-b border-zinc-800 bg-zinc-950">
        <h1 className="font-sans text-sm font-semibold text-zinc-100 tracking-wide uppercase">
          Settings
        </h1>
        <p className="font-mono text-[10px] text-zinc-600 tracking-widest mt-0.5">
          API credentials · Inference routing · Model selection
        </p>
      </header>

      <div className="max-w-2xl p-6">
        {loading ? (
          <div className="font-mono text-xs text-zinc-600 animate-pulse">Loading config…</div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-6">

            {/* ── API Keys ── */}
            <section className="border border-zinc-800 bg-zinc-900">
              <div className="px-4 py-3 border-b border-zinc-800">
                <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-400 font-semibold">
                  API Keys
                </p>
              </div>
              <div className="px-4 py-4 space-y-4">
                <ApiKeyField
                  id="gemini-key"
                  label="Gemini API Key"
                  value={form.gemini_key}
                  onChange={field('gemini_key')}
                />
                <ApiKeyField
                  id="openai-key"
                  label="OpenAI API Key"
                  value={form.openai_key}
                  onChange={field('openai_key')}
                />
              </div>
            </section>

            {/* ── Inference Routing ── */}
            <section className="border border-zinc-800 bg-zinc-900">
              <div className="px-4 py-3 border-b border-zinc-800">
                <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-400 font-semibold">
                  Inference Routing
                </p>
              </div>
              <div className="px-4 py-4 space-y-2">
                {ROUTING_OPTIONS.map(({ value, label, desc }) => {
                  const checked = form.routing === value;
                  return (
                    <label
                      key={value}
                      htmlFor={`route-${value}`}
                      className={`
                        flex items-start gap-3 p-3 border cursor-pointer
                        transition-colors
                        ${checked
                          ? 'border-cyan-600 bg-cyan-500/5'
                          : 'border-zinc-800 hover:border-zinc-600 hover:bg-zinc-800/40'
                        }
                      `}
                    >
                      <input
                        id={`route-${value}`}
                        type="radio"
                        name="routing"
                        value={value}
                        checked={checked}
                        onChange={() => setForm((f) => ({ ...f, routing: value }))}
                        className="mt-0.5 accent-cyan-500"
                      />
                      <div>
                        <p className={`font-mono text-xs font-bold tracking-widest uppercase ${checked ? 'text-cyan-400' : 'text-zinc-300'}`}>
                          {label}
                        </p>
                        <p className="font-mono text-[10px] text-zinc-600 mt-0.5">{desc}</p>
                      </div>
                    </label>
                  );
                })}
              </div>
            </section>

            {/* ── Active Model ── */}
            <section className="border border-zinc-800 bg-zinc-900">
              <div className="px-4 py-3 border-b border-zinc-800">
                <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-400 font-semibold">
                  Active Model
                </p>
              </div>
              <div className="px-4 py-4">
                <input
                  id="active-model"
                  type="text"
                  value={form.active_model}
                  onChange={(e) => setForm((f) => ({ ...f, active_model: e.target.value }))}
                  placeholder="e.g. gemini/gemini-2.5-flash"
                  className="
                    w-full bg-zinc-950 border border-zinc-700
                    px-3 py-2 font-mono text-xs text-zinc-200
                    placeholder:text-zinc-700
                    focus:outline-none focus:border-cyan-600
                    transition-colors
                  "
                />
              </div>
            </section>

            {/* ── Actions ── */}
            <div className="flex items-center gap-3 pt-2">
              <button
                type="submit"
                disabled={saving}
                className="
                  flex items-center gap-2
                  bg-cyan-500 hover:bg-cyan-400 text-zinc-950
                  font-mono text-xs font-bold uppercase tracking-widest
                  px-5 py-2.5
                  transition-colors disabled:opacity-50 disabled:cursor-not-allowed
                "
              >
                <Save size={13} />
                {saving ? 'Saving…' : 'Save Config'}
              </button>

              <button
                type="button"
                onClick={handleReset}
                className="
                  flex items-center gap-2
                  border border-zinc-700 hover:border-zinc-500
                  bg-transparent hover:bg-zinc-900
                  text-zinc-400 hover:text-zinc-200
                  font-mono text-xs uppercase tracking-widest
                  px-4 py-2.5
                  transition-colors
                "
              >
                <RotateCcw size={13} />
                Reset
              </button>
            </div>

          </form>
        )}
      </div>

      <Toast toast={toast} />
    </div>
  );
}
