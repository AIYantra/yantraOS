import { useEffect, useRef } from 'react';
import { Cpu, MemoryStick, Gauge, Activity, Layers } from 'lucide-react';

// ── Helpers ───────────────────────────────────────────────────────────────────

function clamp(v, min = 0, max = 100) {
  return Math.min(max, Math.max(min, v));
}

// ── Sub-components ────────────────────────────────────────────────────────────

/**
 * MetricBar – a labelled progress bar.
 * value: 0–100 for bars that use %; raw number for TPS
 */
function MetricBar({ label, value, unit = '%', Icon, color = 'bg-cyan-500', max = 100 }) {
  const pct = unit === '%' ? clamp(value) : clamp((value / max) * 100, 0, 100);

  return (
    <div className="border border-zinc-800 bg-zinc-900 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {Icon && <Icon size={13} className="text-zinc-500" />}
          <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">
            {label}
          </span>
        </div>
        <span className="font-mono text-sm font-semibold text-zinc-100">
          {typeof value === 'number' ? value.toFixed(unit === '%' ? 1 : 2) : '—'}{unit}
        </span>
      </div>

      {/* Track */}
      <div className="h-1.5 w-full bg-zinc-800">
        <div
          className={`h-full transition-all duration-700 ease-out ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/**
 * PhaseIndicator – large phase display with REASON pulse.
 */
function PhaseIndicator({ phase }) {
  const cfg = {
    SENSE:  { label: 'Sensing',   ring: 'border-sky-500',     text: 'text-sky-400',     bg: 'bg-sky-500/5'     },
    REASON: { label: 'Reasoning', ring: 'border-amber-500',   text: 'text-amber-400',   bg: 'bg-amber-500/5'   },
    ACT:    { label: 'Acting',    ring: 'border-emerald-500', text: 'text-emerald-400', bg: 'bg-emerald-500/5' },
    IDLE:   { label: 'Idle',      ring: 'border-zinc-700',    text: 'text-zinc-500',    bg: 'bg-zinc-900'      },
  };
  const c = cfg[phase] ?? cfg.IDLE;

  return (
    <div className={`border ${c.ring} ${c.bg} p-4 flex items-center justify-between`}>
      <div>
        <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-600 mb-1">Kriya Loop Phase</p>
        <p className={`font-mono text-xl font-bold tracking-widest uppercase ${c.text} ${phase === 'REASON' ? 'animate-pulse' : ''}`}>
          {c.label}
        </p>
      </div>
      <Layers size={28} className={`${c.text} opacity-40`} />
    </div>
  );
}

/**
 * CognitiveStream – scrolling log pane with Freeze-Buffer on REASON phase.
 */
function CognitiveStream({ logs, phase }) {
  const bottomRef = useRef(null);
  const containerRef = useRef(null);
  const isReasoning = phase === 'REASON';

  useEffect(() => {
    // Freeze-Buffer: halt auto-scroll during REASON phase
    if (isReasoning) return;
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs, isReasoning]);

  return (
    <div className="flex flex-col h-full border border-zinc-800">
      {/* Header */}
      <div className={`
        flex items-center justify-between px-3 py-2
        border-b border-zinc-800
        ${isReasoning ? 'bg-amber-950/40' : 'bg-zinc-900'}
        transition-colors duration-500
      `}>
        <div className="flex items-center gap-2">
          <Activity size={12} className={isReasoning ? 'text-amber-400 animate-pulse' : 'text-zinc-600'} />
          <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">
            Cognitive Stream
          </span>
        </div>
        {isReasoning && (
          <span className="font-mono text-[9px] uppercase tracking-widest text-amber-400 animate-pulse border border-amber-700 px-1.5 py-0.5">
            ⬡ Buffer Frozen
          </span>
        )}
        <span className="font-mono text-[9px] text-zinc-700">
          {logs.length} lines
        </span>
      </div>

      {/* Log body */}
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto p-3 bg-zinc-950"
      >
        {logs.length === 0 ? (
          <p className="font-mono text-[11px] text-zinc-700 text-center mt-8">
            — Waiting for stream —
          </p>
        ) : (
          logs.map((line, i) => (
            <div
              key={i}
              className="font-mono text-[11px] leading-5 text-zinc-400 border-b border-zinc-900/60 py-0.5 last:border-b-0"
            >
              <span className="text-zinc-700 mr-2 select-none">
                {String(i + 1).padStart(4, '0')}
              </span>
              {line}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Overview({ stream }) {
  const { logs, telemetry, phase } = stream;
  const { cpu_pct, vram_pct, inference_tps } = telemetry;

  return (
    <div className="h-screen flex flex-col">
      {/* Page Header */}
      <header className="px-6 py-4 border-b border-zinc-800 bg-zinc-950 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-sans text-sm font-semibold text-zinc-100 tracking-wide uppercase">
              Overview
            </h1>
            <p className="font-mono text-[10px] text-zinc-600 tracking-widest mt-0.5">
              Real-time Kriya Loop telemetry + cognitive event stream
            </p>
          </div>
          <PhaseIndicator phase={phase} />
        </div>
      </header>

      {/* 2-Pane body */}
      <div className="flex flex-1 overflow-hidden">
        {/* LEFT — Cognitive stream */}
        <div className="flex-1 p-4 overflow-hidden flex flex-col min-w-0">
          <CognitiveStream logs={logs} phase={phase} />
        </div>

        {/* Divider */}
        <div className="w-px bg-zinc-800 flex-shrink-0" />

        {/* RIGHT — Telemetry */}
        <div className="w-[280px] flex-shrink-0 p-4 flex flex-col gap-3 overflow-y-auto">
          <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-600 mb-1">
            System Telemetry
          </p>

          <MetricBar
            label="CPU Load"
            value={cpu_pct}
            unit="%"
            Icon={Cpu}
            color={cpu_pct > 85 ? 'bg-red-500' : cpu_pct > 60 ? 'bg-amber-500' : 'bg-cyan-500'}
          />

          <MetricBar
            label="VRAM Allocation"
            value={vram_pct}
            unit="%"
            Icon={MemoryStick}
            color={vram_pct > 90 ? 'bg-red-500' : vram_pct > 70 ? 'bg-amber-500' : 'bg-cyan-500'}
          />

          <MetricBar
            label="Inference TPS"
            value={inference_tps}
            unit=" tok/s"
            max={200}
            Icon={Gauge}
            color="bg-violet-500"
          />

          {/* Raw values grid */}
          <div className="border border-zinc-800 bg-zinc-900 p-3 mt-2">
            <p className="font-mono text-[9px] uppercase tracking-widest text-zinc-600 mb-3">
              Raw Values
            </p>
            <div className="grid grid-cols-2 gap-2">
              {[
                { k: 'CPU',  v: `${cpu_pct.toFixed(1)}%`       },
                { k: 'VRAM', v: `${vram_pct.toFixed(1)}%`      },
                { k: 'TPS',  v: `${inference_tps.toFixed(2)}`  },
                { k: 'PHASE',v: phase                           },
              ].map(({ k, v }) => (
                <div key={k} className="border border-zinc-800 px-2 py-1.5">
                  <p className="font-mono text-[8px] text-zinc-600 uppercase">{k}</p>
                  <p className={`font-mono text-xs font-bold ${k === 'PHASE' ? 'text-cyan-400' : 'text-zinc-200'}`}>{v}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
