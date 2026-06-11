/**
 * YantraOS Web-OS Chat Component
 * Translates React/Tailwind Animated AI Chat into Brutalist Vanilla JS.
 */

export function renderChat(container) {
  container.innerHTML = `
    <div id="chat-wrapper">
      <div id="chat-header">
        <h2 class="chat-title">HOW CAN I HELP TODAY?</h2>
        <div class="chat-subtitle">TYPE A COMMAND OR ASK A QUESTION</div>
      </div>

      <div id="chat-box">
        <div id="command-palette" class="hidden">
          <div class="cmd-item" data-cmd="/inject">
            <span class="cmd-icon">[INJ]</span>
            <span class="cmd-label">INJECT DATA</span>
            <span class="cmd-desc">Force sense data into context</span>
          </div>
          <div class="cmd-item" data-cmd="/force">
            <span class="cmd-icon">[FRC]</span>
            <span class="cmd-label">FORCE ACT</span>
            <span class="cmd-desc">Bypass reasoning and execute</span>
          </div>
          <div class="cmd-item" data-cmd="/clear">
            <span class="cmd-icon">[CLR]</span>
            <span class="cmd-label">CLEAR STREAM</span>
            <span class="cmd-desc">Wipe cognitive log</span>
          </div>
          <div class="cmd-item" data-cmd="/status">
            <span class="cmd-icon">[STS]</span>
            <span class="cmd-label">DAEMON STATUS</span>
            <span class="cmd-desc">Print detailed telemetry</span>
          </div>
        </div>

        <textarea id="chat-input" placeholder="Initiate command..."></textarea>
        
        <div id="chat-attachments" class="hidden"></div>

        <div id="chat-footer">
          <div class="chat-tools">
            <button class="chat-tool-btn" id="btn-attach" title="Attach File (Mock)">[+] ATTACH</button>
            <button class="chat-tool-btn" id="btn-cmd" title="Command Palette">[/] CMD</button>
          </div>
          <button class="btn-primary" id="btn-send">
            <span class="send-text">SEND</span>
            <span class="send-loader hidden">...</span>
          </button>
        </div>
      </div>

      <div id="chat-typing-indicator" class="hidden">
        <span class="typing-label">DAEMON IS PROCESSING</span>
        <span class="typing-dots">. . .</span>
      </div>
    </div>
  `;

  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("btn-send");
  const attachBtn = document.getElementById("btn-attach");
  const cmdBtn = document.getElementById("btn-cmd");
  const palette = document.getElementById("command-palette");
  const attachmentsList = document.getElementById("chat-attachments");
  const typingIndicator = document.getElementById("chat-typing-indicator");

  let activeSuggestion = -1;
  let attachments = [];

  // Auto-resize logic
  function adjustHeight() {
    input.style.height = '60px';
    const newHeight = Math.max(60, Math.min(input.scrollHeight, 200));
    input.style.height = newHeight + 'px';
  }

  input.addEventListener("input", () => {
    adjustHeight();
    handleCommandPalette();
  });

  input.addEventListener("keydown", (e) => {
    const isPaletteOpen = !palette.classList.contains("hidden");
    const items = palette.querySelectorAll(".cmd-item");

    if (isPaletteOpen) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        activeSuggestion = activeSuggestion < items.length - 1 ? activeSuggestion + 1 : 0;
        updatePaletteSelection(items);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        activeSuggestion = activeSuggestion > 0 ? activeSuggestion - 1 : items.length - 1;
        updatePaletteSelection(items);
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (activeSuggestion >= 0) {
          selectCommand(items[activeSuggestion].dataset.cmd);
        }
      } else if (e.key === "Escape") {
        e.preventDefault();
        closePalette();
      }
    } else if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (input.value.trim()) sendMessage();
    }
  });

  // Command palette logic
  function handleCommandPalette() {
    const val = input.value;
    if (val.startsWith("/") && !val.includes(" ")) {
      palette.classList.remove("hidden");
      const items = Array.from(palette.querySelectorAll(".cmd-item"));
      let matchIdx = items.findIndex(el => el.dataset.cmd.startsWith(val));
      activeSuggestion = matchIdx >= 0 ? matchIdx : -1;
      updatePaletteSelection(items);
    } else {
      closePalette();
    }
  }

  function updatePaletteSelection(items) {
    items.forEach((item, idx) => {
      if (idx === activeSuggestion) {
        item.classList.add("active");
      } else {
        item.classList.remove("active");
      }
    });
  }

  function selectCommand(cmd) {
    input.value = cmd + " ";
    closePalette();
    input.focus();
    adjustHeight();
  }

  function closePalette() {
    palette.classList.add("hidden");
    activeSuggestion = -1;
    updatePaletteSelection(palette.querySelectorAll(".cmd-item"));
  }

  palette.addEventListener("click", (e) => {
    const item = e.target.closest(".cmd-item");
    if (item) {
      selectCommand(item.dataset.cmd);
    }
  });

  cmdBtn.addEventListener("click", () => {
    input.value = "/";
    input.focus();
    handleCommandPalette();
  });

  // Attachments mock
  attachBtn.addEventListener("click", () => {
    const name = `file-${Math.floor(Math.random()*1000)}.dump`;
    attachments.push(name);
    renderAttachments();
  });

  function renderAttachments() {
    if (attachments.length > 0) {
      attachmentsList.classList.remove("hidden");
      attachmentsList.innerHTML = attachments.map((f, i) => 
        \`<div class="attach-chip"><span>\${f}</span><button class="attach-rm" data-idx="\${i}">X</button></div>\`
      ).join('');
      
      attachmentsList.querySelectorAll('.attach-rm').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const idx = parseInt(e.target.dataset.idx);
          attachments.splice(idx, 1);
          renderAttachments();
        });
      });
    } else {
      attachmentsList.classList.add("hidden");
      attachmentsList.innerHTML = "";
    }
  }

  // Send message mock (can wire to backend later)
  async function sendMessage() {
    const text = input.value.trim();
    if (!text) return;

    // Simulate sending
    input.disabled = true;
    sendBtn.disabled = true;
    sendBtn.querySelector('.send-text').classList.add('hidden');
    sendBtn.querySelector('.send-loader').classList.remove('hidden');
    typingIndicator.classList.remove('hidden');

    try {
      // POST to backend (example mapping /inject to backend command)
      const res = await fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "inject", data: { text, attachments } })
      });
      // Ignore result for now, just simulate delay
      await new Promise(r => setTimeout(r, 1000));
    } catch (e) {
      console.error("Chat send failed", e);
    } finally {
      input.value = "";
      attachments = [];
      renderAttachments();
      adjustHeight();
      
      input.disabled = false;
      sendBtn.disabled = false;
      sendBtn.querySelector('.send-text').classList.remove('hidden');
      sendBtn.querySelector('.send-loader').classList.add('hidden');
      typingIndicator.classList.add('hidden');
      input.focus();
    }
  }

  sendBtn.addEventListener("click", sendMessage);

  // Close palette on outside click
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#chat-box")) {
      closePalette();
    }
  });

  // Init
  adjustHeight();
}
