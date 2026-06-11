import { useRef, useEffect, useState } from 'react';
import { Trash2, Download, PauseCircle, PlayCircle } from 'lucide-react';

export default function Logs({ stream }) {
  const { logs, phase, clearLogs } = stream;
  const [frozen, setFrozen]   = useState(false);
  const [filter, setFilter]   = useState('');
  const bottomRef = useRef(null);

  // Auto-scroll unless manually frozen
  useEffect(() => {
    if (frozen) return;
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs, frozen]);

  // Export logs as .txt
  function handleExport() {
    const blob = new Blob([logs.join('\n')], { type: 'text/plain' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `yantra-logs-${Date.now()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const filtered = filter.trim()
    ? logs.filter((l) => l.toLowerCase().includes(filter.toLowerCase()))
    : logs;

  return (
    <div className="h-screen flex flex-col bg-zinc-950">
      {/* Header */}
      <header className="px-6 py-4 border-b border-zinc-800 bg-zinc-950 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-sans text-sm font-semibold text-zinc-100 tracking-wide uppercase">
              Logs
            </h1>
            <p className="font-mono text-[10px] text-zinc-600 tracking-widest mt-0.5">
              Live cognitive event buffer · {logs.length} / 300 lines
            </p>
          </div>

          {/* Toolbar */}
          <div className="flex items-center gap-2">
            {/* Search */}
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter…"
              className="
                bg-zinc-900 border border-zinc-700
                px-3 py-1.5 font-mono text-[11px] text-zinc-300
                placeholder:text-zinc-700 w-44
                focus:outline-none focus:border-cyan-600
                transition-colors
              "
            />

            {/* Freeze toggle */}
            <button
              id="btn-freeze-logs"
              onClick={() => setFrozen((f) => !f)}
              title={frozen ? 'Resume auto-scroll' : 'Freeze scroll'}
              className={`
                flex items-center gap-1.5 px-3 py-1.5 border
                font-mono text-[10px] uppercase tracking-widest
                transition-colors
                ${frozen
                  ? 'border-amber-600 bg-amber-950/40 text-amber-400'
                  : 'border-zinc-700 bg-zinc-900 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500'
                }
              `}
            >
              {frozen ? <PlayCircle size={12} /> : <PauseCircle size={12} />}
              {frozen ? 'Resume' : 'Freeze'}
            </button>

            {/* Export */}
            <button
              id="btn-export-logs"
              onClick={handleExport}
              disabled={logs.length === 0}
              title="Export logs as .txt"
              className="
                flex items-center gap-1.5 px-3 py-1.5 border border-zinc-700
                bg-zinc-900 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500
                font-mono text-[10px] uppercase tracking-widest
                transition-colors disabled:opacity-30 disabled:cursor-not-allowed
              "
            >
              <Download size={12} />
              Export
            </button>

            {/* Clear */}
            <button
              id="btn-clear-logs"
              onClick={clearLogs}
              disabled={logs.length === 0}
              title="Clear log buffer"
              className="
                flex items-center gap-1.5 px-3 py-1.5 border border-zinc-700
                bg-zinc-900 text-zinc-400 hover:text-red-400 hover:border-red-800
                font-mono text-[10px] uppercase tracking-widest
                transition-colors disabled:opacity-30 disabled:cursor-not-allowed
              "
            >
              <Trash2 size={12} />
              Clear
            </button>
          </div>
        </div>
      </header>

      {/* Phase stripe */}
      {phase === 'REASON' && (
        <div className="bg-amber-950/30 border-b border-amber-900 px-6 py-1.5 flex items-center gap-2 flex-shrink-0">
          <span className="font-mono text-[9px] uppercase tracking-widest text-amber-500 animate-pulse">
            ⬡ REASON phase active — log buffer may lag behind execution
          </span>
        </div>
      )}

      {/* Log viewport */}
      <div className="flex-1 overflow-y-auto p-0">
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="font-mono text-xs text-zinc-700">
              {filter ? 'No lines match filter.' : '— Waiting for events —'}
            </p>
          </div>
        ) : (
          <table className="w-full border-collapse text-left">
            <tbody>
              {filtered.map((line, i) => {
                // Basic log-level colouring
                const lower = line.toLowerCase();
                const rowCls =
                  lower.includes('error') || lower.includes('err')
                    ? 'bg-red-950/20 text-red-400'
                    : lower.includes('warn')
                    ? 'bg-amber-950/20 text-amber-400'
                    : lower.includes('✓') || lower.includes('ok') || lower.includes('success')
                    ? 'text-emerald-400'
                    : 'text-zinc-400';

                return (
                  <tr
                    key={i}
                    className={`border-b border-zinc-900 hover:bg-zinc-900/50 transition-colors ${rowCls}`}
                  >
                    <td className="font-mono text-[10px] text-zinc-700 px-4 py-1 select-none w-14 text-right border-r border-zinc-900">
                      {i + 1}
                    </td>
                    <td className="font-mono text-[11px] px-4 py-1 whitespace-pre-wrap break-all">
                      {line}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Footer status bar */}
      <div className="border-t border-zinc-800 bg-zinc-950 px-6 py-1.5 flex items-center gap-4 flex-shrink-0">
        <span className="font-mono text-[9px] text-zinc-700 uppercase tracking-widest">
          Buffer: {logs.length}/300
        </span>
        {filter && (
          <span className="font-mono text-[9px] text-cyan-600 uppercase tracking-widest">
            Filtered: {filtered.length} matches
          </span>
        )}
        {frozen && (
          <span className="font-mono text-[9px] text-amber-600 uppercase tracking-widest animate-pulse">
            ⬡ Scroll frozen
          </span>
        )}
      </div>
    </div>
  );
}
