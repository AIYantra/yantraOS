/**
 * Logs tab: full-height scrollable log viewer with phase filter + regex search.
 * Max 500 entries in DOM. Auto-scroll toggle.
 */

import { subscribe, unsubscribe } from "./sse-client.js";

let _handler = null;
let _autoScroll = true;
let _filterPhase = "ALL";
let _filterRegex = null;
let _debounceTimer = null;
const MAX_ENTRIES = 500;

export function render(container) {
  container.innerHTML = `
    <div id="logs-root">
      <div id="logs-toolbar">
        <div class="filter-group" role="group" aria-label="Phase filter">
          ${["ALL","SENSE","REASON","ACT"].map(p =>
            `<button class="phase-btn${p === "ALL" ? " active" : ""}" data-phase="${p}">${p}</button>`
          ).join("")}
        </div>
        <input id="logs-search" class="logs-search-input" type="text"
               placeholder="Regex filter…" aria-label="Log search filter">
        <label class="autoscroll-label">
          <input type="checkbox" id="logs-autoscroll" checked>
          AUTO-SCROLL
        </label>
        <button class="btn-clear" id="logs-clear">CLEAR</button>
      </div>
      <div id="logs-feed" role="log" aria-live="polite" aria-atomic="false"></div>
    </div>
  `;

  _autoScroll = true;
  _filterPhase = "ALL";
  _filterRegex = null;

  _bindToolbar();
  _handler = _onEvent;
  subscribe(_handler);
}

export function destroy() {
  if (_handler) unsubscribe(_handler);
  _handler = null;
  clearTimeout(_debounceTimer);
}

function _onEvent(ev) {
  if (ev.type === "log" || ev.type === "kriya_phase") {
    const phase   = (ev.phase || "SENSE").toUpperCase();
    const message = ev.message || `[Kriya] Phase → ${phase}`;
    _appendEntry(phase, message);
  }
}

function _appendEntry(phase, message) {
  const feed = document.getElementById("logs-feed");
  if (!feed) return;

  // Phase filter
  if (_filterPhase !== "ALL" && phase !== _filterPhase) return;
  // Regex filter
  if (_filterRegex && !_filterRegex.test(message)) return;

  const entry = document.createElement("div");
  entry.className = `log-entry phase-${phase.toLowerCase()}`;
  entry.dataset.phase = phase;
  entry.dataset.msg   = message;

  const ts = document.createElement("span");
  ts.className = "ts";
  ts.textContent = _fmtTs();

  const phaseTag = document.createElement("span");
  phaseTag.className = "log-phase-tag";
  phaseTag.textContent = phase;

  const msg = document.createElement("span");
  msg.className = "msg";
  msg.textContent = message;

  entry.append(ts, phaseTag, msg);
  feed.appendChild(entry);

  while (feed.children.length > MAX_ENTRIES) feed.removeChild(feed.firstChild);
  if (_autoScroll) feed.scrollTop = feed.scrollHeight;
}

function _bindToolbar() {
  document.querySelectorAll(".phase-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".phase-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      _filterPhase = btn.dataset.phase;
    });
  });

  document.getElementById("logs-search")?.addEventListener("input", (e) => {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(() => {
      const val = e.target.value.trim();
      try {
        _filterRegex = val ? new RegExp(val, "i") : null;
      } catch {
        _filterRegex = null;
      }
    }, 200);
  });

  document.getElementById("logs-autoscroll")?.addEventListener("change", (e) => {
    _autoScroll = e.target.checked;
  });

  document.getElementById("logs-clear")?.addEventListener("click", () => {
    const feed = document.getElementById("logs-feed");
    if (feed) feed.innerHTML = "";
  });
}

function _fmtTs() {
  const n = new Date();
  return [n.getHours(), n.getMinutes(), n.getSeconds()]
    .map(v => String(v).padStart(2, "0")).join(":") +
    "." + String(n.getMilliseconds()).padStart(3, "0");
}
