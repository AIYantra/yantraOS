# Contributing to YantraOS

First off, thank you for considering contributing to YantraOS! It's people like you that make YantraOS a powerful and secure Autonomous Agent Operating System.

## How Can I Contribute?

### Reporting Bugs
If you find a bug, please create an issue using the **Bug Report** template. Provide as much detail as possible, including:
- Your OS environment details.
- Daemon logs (`/var/log/yantra/engine.log`).
- Steps to reproduce the issue.

### Suggesting Enhancements
If you have an idea for a new feature or integration, create an issue using the **Feature Request** template. Describe the use case and how it fits into the Kriya Loop architecture.

### Pull Requests
1. Fork the repository and create your branch from `main`.
2. If you've added code that should be tested, add tests.
3. If you've changed APIs, update the documentation.
4. Ensure your code conforms to the project's linting standards (`flake8`, `ruff`).
5. Open a pull request using the **Pull Request Template**.

## Local Development Setup
1. Clone the repository: `git clone https://github.com/AIYantra/YantraOS.git`
2. Create a virtual environment: `python -m venv venv && source venv/bin/activate`
3. Install requirements: `pip install -r requirements.txt`

## Architectural Guidelines
YantraOS is built on a strict two-process, mathematically decoupled architecture.
- **Never** introduce blocking synchronous calls in the `asyncio` event loop.
- **Never** execute LLM output directly on the host. Always route through `core/sandbox.py`.
- **Always** validate incoming IPC payloads using strict Pydantic models (`extra="forbid"`).
