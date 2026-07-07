# YantraOS Quickstart Guide

Welcome to YantraOS. This guide will walk you through flashing the OS, configuring your network on initial boot, and syncing your local node to the telemetry HUD.

## 1. Flashing the ISO

To install YantraOS, flash the generated ISO (`yantraos-master.iso`) to a target bare-metal drive or bootable USB medium.

Using `dd` on a Unix system:

```bash
sudo dd if=yantraos-master.iso of=/dev/sdX bs=4M status=progress
```

*(Ensure `/dev/sdX` represents your actual target device before executing.)*

## 2. Initial Boot & Wi-Fi Configuration

Upon first boot, the YantraOS daemon (`yantra.service`) will autonomously step through the ignition sequence and drop you into the core environment.

To configure Wi-Fi networking and establish an uplink, our automated first-boot script uses `nmtui`.

For a visual, curses-based network selection, simply run:

```bash
nmtui
```

Alternatively, for a direct command-line approach, use `nmcli`:

```bash
nmcli device wifi connect "YourSSID" password "YourPassword"
```

Once authenticated, NetworkManager (with the iwd backend) will automatically request a DHCP lease and stabilize the connection.

## 3. Connecting to the Telemetry HUD

Once connected to the internet, you can verify your agent node connection at the centralized HUD.

1. Navigate to [yantraos.com](https://yantraos.com) from an external workstation or mobile device.
2. Authenticate the node via your generated telemetry tokens.
3. Verify that your machine's diagnostic telemetry, IPC streams, and execution matrices are streaming efficiently over the network infrastructure.

Your local node's IPC interface is now synchronized with the broader telemetry network, running autonomously on top of your hardware via the Kriya Loop. Welcome to the collective.

## 4. Security Advisory — Telegram C2 Gateway

> ⚠️ **API Key Transmission Risk**

If you use the Telegram C2 gateway (`/api <provider> <key>` command), be aware that API keys are transmitted through Telegram's message infrastructure. While Telegram uses TLS in transit, message content may be logged by:
- The YantraOS gateway process itself (in `yantra.telegram` logger)
- Telegram's server-side infrastructure

**For production environments**, prefer injecting API keys directly via the ignition script (`./yantra_ignition.sh`) or by writing to `/etc/yantra/secrets.env` on the host. The Telegram `/api` command is intended for development and emergency key rotation only.

The State API (port 50000) is bound to `127.0.0.1` and is not accessible from the network. Privileged endpoints (`/api/v1/secrets/update`, `/api/v1/config/route`) additionally enforce localhost-only access regardless of the bind address.
