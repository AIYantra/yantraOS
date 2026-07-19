# The Amnesia Protocol

YantraOS serves as a framework distributed globally as a pre-compiled Arch Linux ISO. To ensure complete operational security and privacy for end users, preventing the "State Leakage" problem is critical during the build process.

State leakage occurs when the developer's local development environment—such as LLM memory fragments, Python compiled bytecode, or API keys—accidentally bleeds into the public 'Gold Master' (`.iso`) image.

YantraOS mitigates this using the **Amnesia Protocol**.

## Pre-flight Sanitization (`archlive/forge_sovereign_iso.sh`)

Before the forge maps source into `airootfs`, it excludes credentials, databases, caches, and host ownership, then applies a final sanitation pass.

### 1. PyCache Annihilation
Compiled Python files (`.pyc`) within `__pycache__` directories retain fragments of code structure and potentially sensitive variables. All such directories are deleted recursively:

```bash
find /opt/yantra -type d -name "__pycache__" -exec rm -rf {} +
find /opt/yantra -name "*.pyc" -delete
```

### 2. State Tracker Cleansing
The Kriya Loop maintains continuous operational state (current cycle, error logs, and metrics) in `JSON` tracker files. The Amnesia script clears these entirely:

```bash
rm -f /opt/yantra/core/state.json
rm -f /opt/yantra/logs/engine.log
```

### 3. Vector Database Purging (ChromaDB)
The local ChromaDB instance stores execution memories inside a local SQLite database and WAL (Write-Ahead Log) files. To prevent the distribution of the Developer's system workflow logs to the public, the local Chroma database is explicitly wiped:

```bash
rm -rf /var/lib/yantra/chroma/
rm -rf /opt/yantra/core/chromadb/
```

### 4. Credential Exclusion
Operational credentials are never copied into the image. ISO nodes use a boot-media provisioning file; Azure nodes use managed identity and Key Vault. The provisioner validates an allowlist and writes separate root-owned `0600` daemon and Telegram environment files.

## Zero State Leakage Guarantee

When an operator flashes YantraOS to a USB and executes a live boot, the OS wakes up in a state of absolute amnesia. The Kriya loop will auto-generate new state trackers, ChromaDB will spin up a fresh empty vector store, and the daemon will calibrate specifically to the hardware of the new host.
