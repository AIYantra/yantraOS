import { useState, useEffect, useRef, useCallback } from 'react';

const MAX_LOGS = 300;

/**
 * useKriyaStream
 *
 * Connects to the FastAPI SSE endpoint at /stream and keeps a reactive
 * snapshot of the Kriya Loop runtime state.
 *
 * Returns:
 *   logs      – string[]  up to MAX_LOGS most-recent log lines
 *   telemetry – { cpu_pct, vram_pct, inference_tps }
 *   phase     – 'SENSE' | 'REASON' | 'ACT' | 'IDLE'
 *   connected – boolean   true while the EventSource is open
 *   clearLogs – () => void
 */
export default function useKriyaStream() {
  const [logs, setLogs] = useState([]);
  const [telemetry, setTelemetry] = useState({
    cpu_pct:       0,
    vram_pct:      0,
    inference_tps: 0,
  });
  const [phase, setPhase]       = useState('IDLE');
  const [connected, setConnected] = useState(false);

  const esRef    = useRef(null);
  const retryRef = useRef(null);

  const connect = useCallback(() => {
    // Clean up any existing connection
    if (esRef.current) {
      esRef.current.close();
    }

    const es = new EventSource('/stream');
    esRef.current = es;

    es.onopen = () => {
      setConnected(true);
      if (retryRef.current) {
        clearTimeout(retryRef.current);
        retryRef.current = null;
      }
    };

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === 'log') {
          setLogs((prev) => {
            const next = [...prev, data.message];
            // Trim to MAX_LOGS — drop oldest from the front
            return next.length > MAX_LOGS ? next.slice(next.length - MAX_LOGS) : next;
          });
        }

        if (data.type === 'telemetry') {
          setTelemetry({
            cpu_pct:       data.cpu_pct       ?? 0,
            vram_pct:      data.vram_pct      ?? 0,
            inference_tps: data.inference_tps ?? 0,
          });
          if (data.phase) setPhase(data.phase);
        }
      } catch {
        // Non-JSON keepalive comment lines are silently ignored
      }
    };

    es.onerror = () => {
      setConnected(false);
      es.close();
      esRef.current = null;
      // Exponential back-off: reconnect after 4 s
      retryRef.current = setTimeout(connect, 4000);
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (esRef.current) esRef.current.close();
      if (retryRef.current) clearTimeout(retryRef.current);
    };
  }, [connect]);

  const clearLogs = useCallback(() => setLogs([]), []);

  return { logs, telemetry, phase, connected, clearLogs };
}
