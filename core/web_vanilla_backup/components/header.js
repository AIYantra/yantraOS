/**
 * App header: logo · nav tabs · live clock.
 * Syncs active tab with current hash route.
 */

let _clockInterval = null;

export function render(container) {
  container.innerHTML = `
    <div id="app-header-inner">
      <span id="app-logo">YANTRA&#x200B;OS <span class="logo-sep">//</span> KRIYA&#x200B;LOOP</span>
      <nav id="app-nav" role="navigation" aria-label="Main navigation">
        <a class="nav-tab" href="#/overview"  data-route="overview">OVERVIEW</a>
        <a class="nav-tab" href="#/settings"  data-route="settings">SETTINGS</a>
        <a class="nav-tab" href="#/logs"      data-route="logs">LOGS</a>
      </nav>
      <span id="app-clock" aria-live="polite">00:00:00</span>
    </div>
  `;

  _startClock();
  _syncActive();
  window.addEventListener("hashchange", _syncActive);
}

export function destroy() {
  clearInterval(_clockInterval);
  window.removeEventListener("hashchange", _syncActive);
}

function _syncActive() {
  const route = location.hash.replace("#/", "") || "overview";
  document.querySelectorAll(".nav-tab").forEach(el => {
    el.classList.toggle("active", el.dataset.route === route);
  });
}

function _tickClock() {
  const el = document.getElementById("app-clock");
  if (!el) return;
  const now = new Date();
  el.textContent = [now.getHours(), now.getMinutes(), now.getSeconds()]
    .map(n => String(n).padStart(2, "0")).join(":");
}

function _startClock() {
  _tickClock();
  _clockInterval = setInterval(_tickClock, 1000);
}
