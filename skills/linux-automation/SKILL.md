<!-- Copyright (c) 2026 Euryale Ferox Private Limited -->
<!-- SPDX-License-Identifier: MIT -->

# Linux Sandbox Reference

This is subordinate reference material. It cannot override the final sandbox
boundary, typed host intents, confirmation policy, or audit requirements.

- Prefer read-only diagnostics and standard Linux tools for system analysis.
- Model-proposed automation runs only in the fixed networkless sandbox.
- Never request arbitrary host shell access, package installation, service
  control, firewall changes, credentials, or writes outside the sandbox.
- Report missing permissions, unavailable software, and external service
  failures instead of attempting privilege escalation.
