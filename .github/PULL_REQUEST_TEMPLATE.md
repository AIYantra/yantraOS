## Description

Please include a summary of the change and which issue is fixed. Please also include relevant motivation and context. 

Fixes # (issue)

## Type of change

Please delete options that are not relevant.

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update

## Architectural Compliance

YantraOS adheres to strict isolation and security rules. Please check all that apply:
- [ ] My code does not introduce blocking synchronous calls in the `asyncio` event loop.
- [ ] My code does not execute LLM output directly on the host (it routes through the sandbox).
- [ ] My code leverages Pydantic `extra="forbid"` for any new IPC endpoint models.

## Checklist:

- [ ] My code follows the style guidelines of this project
- [ ] I have performed a self-review of my own code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings/linter errors
