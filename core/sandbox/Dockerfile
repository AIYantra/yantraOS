# ═══════════════════════════════════════════════════════════════════
# YantraOS — Hardened Sandbox Container Image
# Target: yantra-sandbox:latest
# ═══════════════════════════════════════════════════════════════════
#
# Minimal Alpine image with bash + coreutils for script execution.
# A non-root user (sandbox_user) is created and set as the default
# to enforce least-privilege even before the Docker SDK applies
# additional runtime constraints (cap_drop, read_only, etc.).
#
# This image is built programmatically by SandboxEngine._blocking_init()
# and is NOT intended to be pushed to any registry.
# ═══════════════════════════════════════════════════════════════════

FROM alpine:latest

# ── Install runtime dependencies ──────────────────────────────────
# bash:      Required shell for script execution (POSIX sh is too limited)
# coreutils: GNU echo, date, cat, head, tail, etc.
RUN apk add --no-cache bash coreutils

# ── Create unprivileged sandbox user ──────────────────────────────
# UID 1000 / GID 1000 — standard unprivileged user.
# No home directory, no login shell needed (scripts run via bash -c).
RUN addgroup -g 1000 sandbox_group && \
    adduser -D -u 1000 -G sandbox_group -s /bin/bash sandbox_user

# ── Drop to non-root ─────────────────────────────────────────────
USER sandbox_user

# No ENTRYPOINT — the Python Docker SDK passes [bash, -c, <script>]
# as the command argument to containers.run().
