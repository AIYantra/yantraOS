<!-- Copyright (c) 2026 Euryale Ferox Private Limited -->
<!-- SPDX-License-Identifier: MIT -->

# Action Skills

Each installed runtime skill is a directory containing one data-only
`skill.json`. The manifest uses `yantraos/runtime-skill/v1`, declares a unique
skill ID and version, and maps typed action names to fixed sandbox scripts.

The host validates exact action fields and primitive parameter types, requires
human confirmation, and sends the fixed script plus base64-encoded input only
to the root sandbox broker. Skill packages are never imported or executed by
the daemon. Browser, desktop, file, and privileged host operations cannot be
declared by a skill. Root-signed revocation metadata is checked before confirmation
and immediately before dispatch. Third-party installation remains disabled until
the publisher flow is implemented.
