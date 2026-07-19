# YantraOS Quickstart Guide

Welcome to YantraOS. This guide will walk you through flashing the OS, configuring your network on initial boot, and syncing your local node to the telemetry HUD.

## 1. Flashing the ISO

To install YantraOS, flash the generated ISO (`yantraos-master.iso`) to a target bare-metal drive or bootable USB medium.

Using `dd` on a Unix system:

```bash
sudo dd if=yantraos-master.iso of=/dev/sdX bs=4M status=progress
```

*(Ensure `/dev/sdX` represents your actual target device before executing.)*

## 2. Initial Boot And Credential Provisioning

The ISO has no password login, SSH, or autologin. Before boot, place a `yantra-secrets.env` file on the boot medium containing the allowlisted values shown in `.env.example`. The first-boot provisioner writes private per-service files and only then permits `yantra.service` to start.

Azure images obtain the same environment bundle from Key Vault through managed identity. Credentials are never embedded in ISO or VHD artifacts.

## 3. Connecting to the Telemetry HUD

Once connected to the internet, you can verify your agent node connection at the centralized HUD.

1. Navigate to [yantraos.com](https://yantraos.com) from an external workstation or mobile device.
2. Authenticate the node via your generated telemetry tokens.
3. Verify that your machine's diagnostic telemetry, IPC streams, and execution matrices are streaming efficiently over the network infrastructure.

Your local node's IPC interface is now synchronized with the broader telemetry network, running autonomously on top of your hardware via the Kriya Loop. Welcome to the collective.

## 4. Security Model

The Telegram gateway accepts commands only from the configured private operator chat and cannot transport secrets or privileged host directives. The control API is loopback-only, requires a strong bearer token, and validates Host, Origin, body size, and queue bounds. AI-generated scripts can execute only through the root broker's fixed, networkless Docker policy.
