/**
 * Overview tab: 4 status cards + 2-pane layout (Cognitive Stream + Telemetry HUD).
 * Freeze-buffer activates on REASON phase — scroll stops, last entry pulses.
 */

import { subscribe, unsubscribe } from "./sse-client.js";
import { renderChat } from "./chat.js";

let _handler = null;
let _isReasoning = false;
let _activeReasonEl = null;
let _lastPhase = "";
const MAX_ENTRIES = 500;

export function render(container) {
  container.innerHTML = `
    <div id="ov-cards">
      <div class="ov-card">
        <div class="ov-card-label">DAEMON STATUS</div>
        <div class="ov-card-value" id="ov-daemon-status">—</div>
      </div>
      <div class="ov-card">
        <div class="ov-card-label">ACTIVE MODEL</div>
        <div class="ov-card-value" id="ov-active-model">—</div>
      </div>
      <div class="ov-card">
        <div class="ov-card-label">INFERENCE ROUTE</div>
        <div class="ov-card-value" id="ov-route">—</div>
      </div>
      <div class="ov-card">
        <div class="ov-card-label">ITERATION</div>
        <div class="ov-card-value" id="ov-iteration">—</div>
      </div>
    </div>

    <div id="ov-panes">
      <section id="ov-log-pane" aria-label="Cognitive stream">
        <div class="pane-header">
          <span class="pane-header-icon">▶</span> COGNITIVE STREAM
          <span id="ov-freeze-badge" class="freeze-badge hidden">FROZEN</span>
        </div>
        <div id="ov-log-feed" role="log" aria-live="polite" aria-atomic="false"></div>
        <div id="ov-chat-container"></div>
      </section>

      <aside id="ov-hud-pane" aria-label="Telemetry">
        <div id="ov-phase-indicator" class="phase-indicator state-sense">SENSE</div>

        <section class="hud-section">
          <div class="hud-section-title">CPU UTILISATION</div>
          <div class="metric-row">
            <div class="metric-label">
              <span>LOAD</span><span id="ov-cpu-val" class="val">0%</span>
            </div>
            <div class="bar-track" role="progressbar" aria-valuemin="0" aria-valuemax="100">
              <div id="ov-cpu-bar" class="bar-fill"></div>
            </div>
          </div>
        </section>

        <section class="hud-section">
          <div class="hud-section-title">VRAM ALLOCATION</div>
          <div class="metric-row">
            <div class="metric-label">
              <span>ALLOCATED</span><span id="ov-vram-val" class="val">0 MB</span>
            </div>
            <div class="bar-track" role="progressbar" aria-valuemin="0" aria-valuemax="24576">
              <div id="ov-vram-bar" class="bar-fill"></div>
            </div>
          </div>
        </section>

        <section class="hud-section">
          <div class="hud-section-title">INFERENCE THROUGHPUT</div>
          <div class="tps-display">
            <div id="ov-tps-val" class="tps-num">0.0</div>
            <div class="tps-unit">TOKENS / SEC</div>
          </div>
        </section>
      </aside>
    </div>
  `;

  _isReasoning = false;
  _activeReasonEl = null;
  _lastPhase = "";

  _loadCards();
  _handler = _onEvent;
  subscribe(_handler);

  const chatContainer = document.getElementById("ov-chat-container");
  if (chatContainer) {
    renderChat(chatContainer);
  }
}

export function destroy() {
  if (_handler) unsubscribe(_handler);
  _handler = null;
}

async function _loadCards() {
  try {
    const res = await fetch("/api/config");
    if (!res.ok) return;
    const d = await res.json();
    _set("ov-daemon-status", d.daemon?.status || "—");
    _set("ov-active-model",  d.inference?.active_model || "—");
    _set("ov-route",         d.inference?.routing || "—");
    _set("ov-iteration",     String(d.daemon?.iteration ?? "—"));
  } catch { /* standalone */ }
}

function _onEvent(ev) {
  if (ev.type === "telemetry") {
    _updateBars(ev);
    if (ev.phase && ev.phase !== _lastPhase) _applyPhase(ev.phase, null);
  }
  if (ev.type === "log") {
    const phase = _lastPhase || "SENSE";
    const entry = _appendEntry(phase, ev.message || "");
    if (phase === "REASON") {
      if (_activeReasonEl) _activeReasonEl.classList.remove("active-reason");
      entry.classList.add("active-reason");
      _activeReasonEl = entry;
    } else if (!_isReasoning) {
      _scrollBottom();
    }
  }
  if (ev.type === "kriya_phase") {
    const entry = _appendEntry(ev.phase || "SENSE", ev.message || `[Kriya] Phase → ${ev.phase}`);
    _applyPhase(ev.phase || "SENSE", entry);
    _updateBars(ev);
  }
}

function _applyPhase(phase, entryEl) {
  const p = phase.toUpperCase();
  if (_activeReasonEl) { _activeReasonEl.classList.remove("active-reason"); _activeReasonEl = null; }

  if (p === "REASON") {
    _isReasoning = true;
    if (entryEl) { entryEl.classList.add("active-reason"); _activeReasonEl = entryEl; }
    _setFreezeBadge(true);
  } else {
    _isReasoning = false;
    _setFreezeBadge(false);
    _scrollBottom();
  }
  _lastPhase = p;
  _setPhaseUI(p);
}

function _setPhaseUI(p) {
  const ind = document.getElementById("ov-phase-indicator");
  if (ind) {
    ind.textContent = p;
    ind.className = "phase-indicator";
    if (p === "REASON") ind.classList.add("state-reason");
    else if (p === "ACT") ind.classList.add("state-act");
    else ind.classList.add("state-sense");
  }
}

function _setFreezeBadge(frozen) {
  const badge = document.getElementById("ov-freeze-badge");
  if (badge) badge.classList.toggle("hidden", !frozen);
}

function _appendEntry(phase, message) {
  const feed = document.getElementById("ov-log-feed");
  if (!feed) return document.createElement("div");
  const entry = document.createElement("div");
  entry.className = `log-entry phase-${phase.toLowerCase()}`;
  const ts = document.createElement("span");
  ts.className = "ts";
  ts.textContent = _fmtTs();
  const msg = document.createElement("span");
  msg.className = "msg";
  msg.textContent = message || "(no message)";
  entry.append(ts, msg);
  feed.appendChild(entry);
  while (feed.children.length > MAX_ENTRIES) feed.removeChild(feed.firstChild);
  return entry;
}

function _scrollBottom() {
  const feed = document.getElementById("ov-log-feed");
  if (feed) feed.scrollTop = feed.scrollHeight;
}

function _updateBars(data) {
  if (data.cpu_pct != null) {
    _setBar("ov-cpu-bar", "ov-cpu-val", data.cpu_pct, 100, "%");
  }
  if (data.vram_allocation_mb != null) {
    _setBar("ov-vram-bar", "ov-vram-val", data.vram_allocation_mb, 24576, " MB");
  }
  if (data.inference_tps != null) {
    _set("ov-tps-val", Number(data.inference_tps).toFixed(1));
  }
  if (data.iteration != null) {
    _set("ov-iteration", String(data.iteration));
  }
}

function _setBar(barId, valId, raw, max, unit) {
  const bar = document.getElementById(barId);
  const val = document.getElementById(valId);
  if (!bar) return;
  const pct = Math.min(100, Math.max(0, (raw / max) * 100));
  bar.style.width = `${pct.toFixed(1)}%`;
  bar.classList.remove("warn", "crit");
  if (pct >= 90) bar.classList.add("crit");
  else if (pct >= 75) bar.classList.add("warn");
  if (val) val.textContent = `${raw}${unit}`;
}

function _set(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function _fmtTs() {
  const n = new Date();
  return [n.getHours(), n.getMinutes(), n.getSeconds()]
    .map(v => String(v).padStart(2, "0")).join(":") +
    "." + String(n.getMilliseconds()).padStart(3, "0");
}
