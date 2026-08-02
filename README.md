# yantraOS Core

yantraOS Core is an experimental Python runtime for safer, human-supervised AI actions on a local computer. It routes actions through explicit confirmation, audit logging, deterministic handling where available, and a constrained Docker sandbox for generated scripts.

## Included

- Action routing for bounded file and desktop tasks.
- Human confirmation and immutable audit hooks for external actions.
- A root-owned Unix-socket sandbox broker with a fixed Docker policy.
- A local HTTP/JSON control plane and typed runtime-skill validation.

## Security Model

yantraOS Core is designed to fail closed at privilege boundaries. The daemon is unprivileged; the sandbox broker authorizes it using Unix peer credentials. Sandbox containers have no network or host mounts, a read-only filesystem, no Linux capabilities, and bounded resources.

Desktop automation runs in the logged-in user session, not in the sandbox. Review every proposed action and use a disposable environment while evaluating the project.

## Development

The repository is an early research release. Read the source and run focused tests before enabling any action path on a system you care about.

```bash
python3 -m py_compile *.py
```

Runtime dependencies and platform integration are intentionally left to the integrator. Do not run the root sandbox broker or enable privileged paths until you have reviewed their configuration and security assumptions.

## Contributing

Keep changes focused and preserve the existing trust boundaries: no raw privileged shell strings, no credential commits, and no bypass around confirmation or audit.

## License

Copyright (c) 2026 Euryale Ferox Private Limited. Licensed under the [MIT License](LICENSE).
