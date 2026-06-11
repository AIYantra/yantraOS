/**
 * YantraOS Dashboard — SPA Router
 * Hash-based routing: #/overview | #/settings | #/logs
 * Each route module exports render(container) and optional destroy().
 */

import * as Header   from "./components/header.js";
import * as Sidebar  from "./components/sidebar.js";
import * as Footer   from "./components/footer.js";
import * as Overview from "./components/overview.js";
import * as Settings from "./components/settings.js";
import * as Logs     from "./components/logs.js";

const ROUTES = {
  overview: Overview,
  settings: Settings,
  logs:     Logs,
};

let _currentView = null;
let _currentRoute = null;

function _getRoute() {
  const hash = location.hash.replace("#/", "").split("?")[0];
  return ROUTES[hash] ? hash : "overview";
}

function _navigate() {
  const route   = _getRoute();
  if (route === _currentRoute) return;

  // Tear down previous view
  if (_currentView && typeof _currentView.destroy === "function") {
    _currentView.destroy();
  }

  // Swap content with fade
  const content = document.getElementById("app-content");
  if (!content) return;
  content.classList.add("view-fade");

  requestAnimationFrame(() => {
    content.innerHTML = "";
    ROUTES[route].render(content);
    content.classList.remove("view-fade");
    _currentView  = ROUTES[route];
    _currentRoute = route;
  });
}

function boot() {
  // Mount structural components (persistent across routes)
  Header.render(document.getElementById("app-header"));
  Sidebar.render(document.getElementById("app-sidebar"));
  Footer.render(document.getElementById("app-footer"));

  // Initial route
  _navigate();
  window.addEventListener("hashchange", _navigate);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
