/**
 * Settings tab: API keys, inference routing, model selector, daemon controls.
 * Loads from GET /api/config, saves via POST /api/config and POST /command.
 */

export function render(container) {
  container.innerHTML = `
    <div id="settings-root">
      <section class="settings-section">
        <div class="settings-section-title">API KEYS</div>
        <div class="settings-form" id="settings-keys-form">
          ${_keyField("GEMINI_API_KEY",    "Gemini API Key")}
          ${_keyField("OPENAI_API_KEY",    "OpenAI API Key")}
          ${_keyField("ANTHROPIC_API_KEY", "Anthropic API Key")}
        </div>
        <div class="settings-actions">
          <button class="btn-primary" id="btn-save-keys">SAVE KEYS</button>
        </div>
      </section>

      <section class="settings-section">
        <div class="settings-section-title">INFERENCE ROUTING</div>
        <div class="radio-group" id="routing-group" role="radiogroup" aria-label="Inference routing">
          ${["LOCAL","CLOUD","HYBRID"].map(r => `
            <label class="radio-label">
              <input type="radio" name="routing" value="${r}"> ${r}
            </label>
          `).join("")}
        </div>
      </section>

      <section class="settings-section">
        <div class="settings-section-title">ACTIVE MODEL</div>
        <select id="model-select" class="settings-select"></select>
        <div class="settings-actions">
          <button class="btn-primary" id="btn-save-inference">APPLY</button>
        </div>
      </section>

      <section class="settings-section">
        <div class="settings-section-title">DAEMON CONTROLS</div>
        <div class="daemon-controls">
          <button class="btn-ok"   id="btn-resume">RESUME</button>
          <button class="btn-warn" id="btn-pause">PAUSE</button>
          <button class="btn-err"  id="btn-shutdown">SHUTDOWN</button>
        </div>
      </section>

      <div id="settings-toast" class="toast hidden" role="alert" aria-live="assertive"></div>
    </div>
  `;

  _loadConfig();
  _bindEvents();
}

export function destroy() {}

function _keyField(name, label) {
  return `
    <div class="form-row">
      <label class="form-label" for="key-${name}">${label}</label>
      <div class="form-input-wrap">
        <input type="password" id="key-${name}" data-key="${name}"
               class="settings-input key-input" autocomplete="off"
               placeholder="Enter value…">
        <button class="btn-toggle-vis" data-target="key-${name}" title="Show/hide">◉</button>
      </div>
    </div>
  `;
}

async function _loadConfig() {
  try {
    const res = await fetch("/api/config");
    if (!res.ok) return;
    const d = await res.json();

    // Key placeholders (masked values from server — not editable as-is)
    for (const [k, v] of Object.entries(d.api_keys || {})) {
      const el = document.getElementById(`key-${k}`);
      if (el && v) el.placeholder = v;
    }

    // Routing
    const routing = d.inference?.routing || "LOCAL";
    const radio = document.querySelector(`input[name="routing"][value="${routing}"]`);
    if (radio) radio.checked = true;

    // Model list
    const sel = document.getElementById("model-select");
    if (sel) {
      const models = d.inference?.available_models || [];
      const active = d.inference?.active_model || "";
      sel.innerHTML = models.map(m =>
        `<option value="${m}" ${m === active ? "selected" : ""}>${m}</option>`
      ).join("");
    }
  } catch { /* standalone */ }
}

function _bindEvents() {
  document.getElementById("btn-save-keys")?.addEventListener("click", _saveKeys);
  document.getElementById("btn-save-inference")?.addEventListener("click", _saveInference);
  document.getElementById("btn-pause")?.addEventListener("click", () => _command("pause"));
  document.getElementById("btn-resume")?.addEventListener("click", () => _command("resume"));
  document.getElementById("btn-shutdown")?.addEventListener("click", async () => {
    if (!confirm("Send shutdown command to Kriya Loop daemon?")) return;
    _command("shutdown");
  });

  // Show/hide toggles
  document.querySelectorAll(".btn-toggle-vis").forEach(btn => {
    btn.addEventListener("click", () => {
      const inp = document.getElementById(btn.dataset.target);
      if (!inp) return;
      inp.type = inp.type === "password" ? "text" : "password";
    });
  });
}

async function _saveKeys() {
  const api_keys = {};
  document.querySelectorAll(".key-input").forEach(inp => {
    if (inp.value.trim()) api_keys[inp.dataset.key] = inp.value.trim();
  });
  if (!Object.keys(api_keys).length) { _toast("No keys to save.", "warn"); return; }

  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_keys }),
    });
    const d = await res.json();
    if (res.ok) {
      _toast(`Saved: ${d.updated?.join(", ")}`, "ok");
      document.querySelectorAll(".key-input").forEach(i => { i.value = ""; });
      _loadConfig();
    } else {
      _toast(d.error || "Save failed.", "err");
    }
  } catch (e) { _toast(String(e), "err"); }
}

async function _saveInference() {
  const routing = document.querySelector("input[name='routing']:checked")?.value;
  const active_model = document.getElementById("model-select")?.value;
  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ inference: { routing, active_model } }),
    });
    const d = await res.json();
    res.ok ? _toast(`Applied: ${d.updated?.join(", ")}`, "ok") : _toast(d.error || "Failed.", "err");
  } catch (e) { _toast(String(e), "err"); }
}

async function _command(action) {
  try {
    const res = await fetch("/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const d = await res.json();
    _toast(`${action}: ${d.status || JSON.stringify(d)}`, res.ok ? "ok" : "err");
  } catch (e) { _toast(String(e), "err"); }
}

function _toast(msg, level = "ok") {
  const el = document.getElementById("settings-toast");
  if (!el) return;
  el.textContent = msg;
  el.className = `toast toast-${level}`;
  clearTimeout(el._tid);
  el._tid = setTimeout(() => { el.className = "toast hidden"; }, 4000);
}
