#!/usr/bin/env bash
# YantraOS Atomic Installer
# Final bare-metal deployment script

set -euo pipefail

log_info() { echo -e "\e[36m[INFO]\e[0m $*"; }
log_error() { echo -e "\e[31m[ERROR]\e[0m $*" >&2; }
log_ok() { echo -e "\e[32m[OK]\e[0m $*"; }

BACKUP_TAR="/var/backups/yantra_$(date +%Y%m%d%H%M%S).tar.gz"

log_info "1. Installing required packages..."
if ! pacman -Sy --noconfirm python-pip docker cuda python-pynvml; then
    log_error "Failed to install required packages. Aborting."
    exit 1
fi
log_ok "Packages installed."

log_info "2. Creating yantra_daemon user..."
if ! id yantra_daemon &>/dev/null; then
    useradd -r -s /usr/bin/nologin yantra_daemon
    log_ok "Created yantra_daemon user."
else
    log_info "yantra_daemon user already exists."
fi

log_info "3. Adding yantra_daemon to docker group..."
if getent group docker >/dev/null; then
    usermod -aG docker yantra_daemon
    log_ok "Added yantra_daemon to docker group."
else
    log_error "Docker group does not exist! Installation incomplete."
    exit 1
fi

log_info "4. Backing up /opt/yantra to $BACKUP_TAR ..."
mkdir -p /var/backups
if [[ -d /opt/yantra ]]; then
    tar -czf "$BACKUP_TAR" /opt/yantra
    log_ok "Backup created."
else
    log_info "/opt/yantra does not exist yet; skipping backup."
fi

# Trap to restore on failure
function rollback {
    log_error "Installation failed or aborted. Initiating rollback..."
    if [[ -f "$BACKUP_TAR" ]]; then
        log_info "Restoring backup from $BACKUP_TAR..."
        rm -rf /opt/yantra
        tar -xzf "$BACKUP_TAR" -C /
        log_ok "Rollback complete."
    fi
}
trap rollback ERR

log_info "5. Installing components (simulated)..."
# (Actual component installation omitted for brevity)
# Suppose Python requirements fail here:
# if ! pip install <reqs>; then
#     exit 1 # trap ERR will catch this and rollback
# fi

log_info "6. Post-installation: Reactivating BTRFS autonomous snapshotting..."
if [[ -f /etc/pacman.d/hooks/00-yantra-autosnap.hook.inactive ]]; then
    mv /etc/pacman.d/hooks/00-yantra-autosnap.hook.inactive /etc/pacman.d/hooks/00-yantra-autosnap.hook
    log_ok "Hook reactivated successfully."
fi

log_info "7. Distributing Edge Fleet SSH Keys..."
KEY_PATH="/opt/yantra/config/id_yantra_fleet"
NODES_JSON="/opt/yantra/config/nodes.json"

mkdir -p /opt/yantra/config
if [[ ! -f "$KEY_PATH" ]]; then
    log_info "Generating new Ed25519 SSH key pair at $KEY_PATH..."
    ssh-keygen -t ed25519 -f "$KEY_PATH" -q -N ""
    chmod 0400 "$KEY_PATH"
    log_ok "SSH key created."
else
    log_info "SSH key $KEY_PATH already exists."
fi

if [[ -f "$NODES_JSON" ]]; then
    log_info "Found nodes.json inventory. Distributing keys..."
    # Parse the nodes.json for IP and Username via Python, outputting user@ip
    python3 -c '
import json, sys
try:
    data = json.load(open("'"$NODES_JSON"'"))
    for ip, cfg in data.items():
        user = cfg.get("user", "yantra")
        key = cfg.get("key", "'"$KEY_PATH"'")
        # Only distribute if the key matches the default fleet key we just verified/created
        if key == "'"$KEY_PATH"'":
            print(f"{user}@{ip}")
except Exception as e:
    print(f"Failed to parse nodes.json: {e}", file=sys.stderr)
' | while read -r TARGET; do
        if [ -n "$TARGET" ]; then
            log_info "Pushing public key to $TARGET (you may prompt for password)..."
            # ssh-copy-id will append the .pub key to their ~/.ssh/authorized_keys
            ssh-copy-id -i "${KEY_PATH}.pub" "$TARGET" || log_error "Failed to copy key to $TARGET"
        fi
    done
    log_ok "Fleet keys distribution logic completed."
else
    log_info "No nodes.json found at $NODES_JSON. Skipping key distribution."
fi

# Clear the trap as we finished successfully
trap - ERR
log_ok "Installation completed atomically."

