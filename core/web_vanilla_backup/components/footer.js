/**
 * Footer telemetry strip: conn-dot · phase · CPU · VRAM · TPS · version.
 * Subscribes to SSE client for live updates.
 */

import { subscribe, unsubscribe } from "./sse-client.js";

let _handler = null;

export function render(container) {
  container.innerHTML = `
    <div class="footer-kv">
      <span id="ft-conn-dot" title="Disconnected" aria-label="Connection status"></span>
      <span class="fk">STREAM</span>
    </div>
    <div class="footer-kv">
      <span class="fk">PHASE</span>
      <span id="ft-phase" class="fv" aria-live="polite">SENSE</span>
    </div>
    <div class="footer-kv">
      <span class="fk">CPU</span>
      <span id="ft-cpu" class="fv">0%</span>
    </div>
    <div class="footer-kv">
      <span class="fk">VRAM</span>
      <span id="ft-vram" class="fv">0 MB</span>
    </div>
    <div class="footer-kv">
      <span class="fk">TPS</span>
      <span id="ft-tps" class="fv">0.0 t/s</span>
    </div>
    <div class="footer-kv footer-right">
      <span class="fk">YANTRAOS</span>
      <span class="fv">v3.0 // DASHBOARD</span>
    </div>
  `;

  _handler = _onEvent;
  subscribe(_handler);
}

export function destroy() {
  if (_handler) unsubscribe(_handler);
  _handler = null;
}

function _onEvent(ev) {
  if (ev.type === "conn") {
    const dot = document.getElementById("ft-conn-dot");
    if (!dot) return;
    dot.className = ev.state === "live" ? "live" : ev.state === "reconnecting" ? "reconnecting" : "dead";
    dot.title = ev.state;
    return;
  }
  if (ev.type === "telemetry") {
    _set("ft-phase", ev.phase || "—");
    _set("ft-cpu",   ev.cpu_pct != null ? `${ev.cpu_pct}%` : null);
    _set("ft-vram",  ev.vram_allocation_mb != null ? `${ev.vram_allocation_mb} MB` : null);
    _set("ft-tps",   ev.inference_tps != null ? `${Number(ev.inference_tps).toFixed(1)} t/s` : null);
  }
}

function _set(id, text) {
  if (text == null) return;
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}
