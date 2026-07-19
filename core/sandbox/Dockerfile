# ═══════════════════════════════════════════════════════════════════
# YantraOS — Hardened Sandbox Container Image
# Target: yantra-sandbox:3.20.3
# ═══════════════════════════════════════════════════════════════════
#
# Minimal Alpine image with bash + coreutils for script execution.
# A non-root user (sandbox_user) is created and set as the default
# to enforce least-privilege even before the Docker SDK applies
# additional runtime constraints (cap_drop, read_only, etc.).
#
# This image is built by the ISO/VHD forge and loaded locally before the broker
# starts. It is not pulled or built by the runtime broker.
# ═══════════════════════════════════════════════════════════════════

FROM alpine:3.20.3@sha256:029a752048e32e843bd6defe3841186fb8d19a28dae8ec287f433bb9d6d1ad85

# ── Install runtime dependencies ──────────────────────────────────
# bash:      Required shell for script execution (POSIX sh is too limited)
# coreutils: GNU echo, date, cat, head, tail, etc.
RUN apk add --no-cache bash=5.2.26-r0 coreutils=9.5-r2

# ── Create unprivileged sandbox user ──────────────────────────────
# UID 1000 / GID 1000 — standard unprivileged user.
# No home directory, no login shell needed (scripts run via bash -c).
RUN addgroup -g 1000 sandbox_group && \
    adduser -D -u 1000 -G sandbox_group -s /bin/bash sandbox_user

# ── Drop to non-root ─────────────────────────────────────────────
USER sandbox_user

# No ENTRYPOINT — the Python Docker SDK passes [bash, -c, <script>]
# as the command argument to containers.run().
