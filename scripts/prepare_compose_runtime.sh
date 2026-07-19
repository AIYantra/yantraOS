#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
: "${YANTRA_UID:?Set YANTRA_UID to the host yantra_daemon UID}"
: "${YANTRA_GID:?Set YANTRA_GID to the host yantra group GID}"
[[ "${YANTRA_UID}" =~ ^[0-9]+$ && "${YANTRA_GID}" =~ ^[0-9]+$ ]] \
  || { echo "YANTRA_UID and YANTRA_GID must be numeric." >&2; exit 1; }

for socket_path in /run/yantra-sandbox/broker.sock; do
  [[ -S "${socket_path}" ]] || { echo "Missing broker socket: ${socket_path}" >&2; exit 1; }
done

for directory in yantra_logs yantra_state yantra_data; do
  install -d -m0700 -o "${YANTRA_UID}" -g "${YANTRA_GID}" "${directory}"
done

echo "Compose runtime directories prepared for ${YANTRA_UID}:${YANTRA_GID}."
