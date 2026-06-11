/**
 * Singleton SSE client for /stream.
 * Call subscribe(fn) to receive parsed event objects.
 * Call unsubscribe(fn) to remove a listener.
 */

const _listeners = new Set();
let _es = null;
let _connState = "dead"; // "live" | "dead" | "reconnecting"

function _notify(event) {
  for (const fn of _listeners) {
    try { fn(event); } catch (e) { console.error("[sse-client]", e); }
  }
}

function _connect() {
  if (_es) {
    _es.close();
    _es = null;
  }
  _connState = "reconnecting";
  _notify({ type: "conn", state: "reconnecting" });

  _es = new EventSource("/stream");

  _es.addEventListener("open", () => {
    _connState = "live";
    _notify({ type: "conn", state: "live" });
  });

  _es.addEventListener("message", (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }
    _notify(data);
  });

  _es.addEventListener("kriya_phase", (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }
    _notify({ ...data, type: "kriya_phase" });
  });

  _es.addEventListener("error", () => {
    _connState = "dead";
    _notify({ type: "conn", state: "dead" });
    // EventSource auto-reconnects; we track state only
  });
}

export function subscribe(fn) {
  _listeners.add(fn);
  if (!_es) _connect();
}

export function unsubscribe(fn) {
  _listeners.delete(fn);
}

export function connState() {
  return _connState;
}
