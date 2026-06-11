/**
 * Left sidebar: icon+label nav + system status card.
 * Loads system info from GET /api/system on mount.
 */

export function render(container) {
  container.innerHTML = `
    <nav id="sidebar-nav" aria-label="Sidebar navigation">
      <a class="sidebar-link" href="#/overview" data-route="overview">
        <span class="sidebar-icon">◈</span><span class="sidebar-label">OVERVIEW</span>
      </a>
      <a class="sidebar-link" href="#/settings" data-route="settings">
        <span class="sidebar-icon">⚙</span><span class="sidebar-label">SETTINGS</span>
      </a>
      <a class="sidebar-link" href="#/logs" data-route="logs">
        <span class="sidebar-icon">≡</span><span class="sidebar-label">LOGS</span>
      </a>
    </nav>
    <div id="sidebar-sys-card">
      <div class="sidebar-card-title">SYSTEM</div>
      <div class="sidebar-kv"><span class="sk">HOST</span><span class="sv" id="sb-host">—</span></div>
      <div class="sidebar-kv"><span class="sk">OS</span><span class="sv" id="sb-os">—</span></div>
      <div class="sidebar-kv"><span class="sk">IP</span><span class="sv" id="sb-ip">—</span></div>
      <div class="sidebar-kv"><span class="sk">UP</span><span class="sv" id="sb-uptime">—</span></div>
    </div>
  `;

  _syncActive();
  window.addEventListener("hashchange", _syncActive);
  _loadSystem();
}

export function destroy() {
  window.removeEventListener("hashchange", _syncActive);
}

function _syncActive() {
  const route = location.hash.replace("#/", "") || "overview";
  document.querySelectorAll(".sidebar-link").forEach(el => {
    el.classList.toggle("active", el.dataset.route === route);
  });
}

async function _loadSystem() {
  try {
    const res = await fetch("/api/system");
    if (!res.ok) return;
    const d = await res.json();
    _set("sb-host", d.hostname || "—");
    _set("sb-os", d.os || "—");
    _set("sb-ip", d.ip || "—");
    _set("sb-uptime", _fmtUptime(d.uptime_seconds || 0));
  } catch { /* standalone mode — no daemon */ }
}

function _set(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function _fmtUptime(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${m}m`;
}
