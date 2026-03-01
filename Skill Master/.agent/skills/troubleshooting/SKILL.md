---
name: troubleshooting
description: Systematic debugging and error resolution methodology. Use this skill when the user encounters a bug, error, unexpected behavior, performance issue, or needs help diagnosing and fixing a problem in code, infrastructure, or integrations.
---

# Troubleshooting

Structured methodology for diagnosing, isolating, and resolving bugs, errors, and unexpected behavior. Follow the **Observe → Hypothesize → Isolate → Fix → Verify** cycle.

## When to Use This Skill

- The user reports a bug, error, or unexpected behavior
- Something that "was working" suddenly stopped
- Performance degraded or a feature is broken
- An error message or stack trace needs interpreting
- Deployment or integration issues arise

## Core Workflow

### 1. Observe (Gather Evidence)

Before touching any code, collect all available information:

**Error Artifacts:**
- Exact error message and stack trace
- Relevant log output (application, server, browser console)
- HTTP status codes and response bodies
- Screenshots or screen recordings of the issue

**Context:**
- When did it start? (after a deploy, config change, time-based?)
- Is it reproducible? (always, intermittent, specific conditions?)
- Who is affected? (all users, specific accounts, specific devices?)
- What changed recently? (code, dependencies, environment, data?)

> **Rule:** Never skip observation. "I think I know what it is" is the #1 cause of wasted debugging time.

### 2. Hypothesize (Form Theories)

Based on evidence, generate ranked hypotheses:

| # | Hypothesis | Evidence For | Evidence Against | Test |
| :--- | :--- | :--- | :--- | :--- |
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

**Prioritize by:**
- **Likelihood** — What does the evidence point to most strongly?
- **Blast radius** — What would cause the most damage if true?
- **Testability** — What's quickest to confirm or rule out?

### 3. Isolate (Narrow the Cause)

Systematically eliminate hypotheses using these strategies:

**Binary Search (Divide & Conquer):**
- Cut the problem space in half with each test
- Example: Does the error happen in staging? → Yes = not deploy-specific → Check data/config

**Change One Thing at a Time:**
- Revert to last known good state, then re-apply changes one by one
- Never change two variables simultaneously

**Minimal Reproduction:**
- Strip away everything until only the bug remains
- The smaller the reproduction case, the clearer the cause

**Comparison:**
- Compare working vs broken: environments, configs, data, versions
- `diff` is your best friend

### 4. Fix (Apply the Solution)

Once the root cause is confirmed:

**Apply the Minimal Fix:**
- Fix the root cause, not the symptom
- Keep the change as small as possible
- Avoid "while I'm here" refactors during hotfixes

**Error Handling Patterns:**

| Pattern | When to Use | Example |
| :--- | :--- | :--- |
| **Fail Fast** | Invalid input, preconditions | Validate at entry point |
| **Graceful Degradation** | External service failure | Serve cached data on API timeout |
| **Circuit Breaker** | Repeated external failures | Stop calling a down service |
| **Retry with Backoff** | Transient network issues | Retry 3× with exponential delay |
| **Error Aggregation** | Multi-field validation | Collect all errors, report together |
| **Fallback Chain** | Multiple data sources | Try cache → DB → default |

### 5. Verify (Confirm the Fix)

**Immediate Verification:**
- [ ] The original error no longer occurs
- [ ] Related functionality still works (regression check)
- [ ] Edge cases are handled
- [ ] Logs show expected behavior

**Prevent Recurrence:**
- [ ] Add a test that would have caught this bug
- [ ] Update monitoring/alerting if applicable
- [ ] Document the root cause and fix
- [ ] Check for the same bug pattern elsewhere in the codebase

## Error Category Quick Reference

| Category | Examples | Typical Cause | First Check |
| :--- | :--- | :--- | :--- |
| **4xx Client** | 400, 401, 403, 404 | Bad request, auth, permissions | Request payload, headers, auth token |
| **5xx Server** | 500, 502, 503 | Server crash, timeout, overload | Server logs, resource usage |
| **Network** | ECONNREFUSED, timeout | Service down, DNS, firewall | `ping`, `curl`, DNS resolution |
| **Database** | Connection refused, deadlock | Credentials, pool exhaustion | Connection string, pool config |
| **Runtime** | TypeError, NullRef | Code bug, unexpected data | Stack trace → line number |
| **Build/Deploy** | Compilation, missing deps | Version mismatch, env config | Build logs, `package.json`/lock file |
| **Performance** | Slow queries, high latency | N+1 queries, missing index | Profiler, query explain plan |

## Debugging Checklist

Use this as a quick-reference when stuck:

### The Basics (Check These First)
- [ ] Read the **full** error message — not just the first line
- [ ] Check the **logs** — application, server, and browser console
- [ ] Confirm you're looking at the **right environment** (dev/staging/prod)
- [ ] Check if **anything changed recently** — deploys, config, dependencies
- [ ] **Reproduce** the issue — can you trigger it on demand?

### If Still Stuck
- [ ] **Rubber duck it** — explain the problem out loud, step by step
- [ ] **Check the docs** — API docs, library changelogs, migration guides
- [ ] **Search the error** — verbatim error message in search engine
- [ ] **Simplify** — remove code until the error disappears, then add back
- [ ] **Sleep on it** — fresh eyes catch what tired ones miss

## Anti-Patterns to Avoid

| Anti-Pattern | Problem | Solution |
| :--- | :--- | :--- |
| Shotgun Debugging | Changing random things hoping it fixes | Observe → Hypothesize → Test systematically |
| Fix the Symptom | Suppressing errors instead of fixing cause | Always find the root cause |
| Silent Catch | `catch(e) {}` hides bugs permanently | Log or re-throw; never swallow errors |
| Blame the Framework | "It must be a library bug" | It's almost always your code; verify first |
| Printf and Pray | Adding logs everywhere without a hypothesis | Form a theory, then add targeted logging |
| Not Reverting | Leaving broken changes in while debugging | Revert to known good, re-apply carefully |

## Best Practices

1. **Observe before acting** — Collect evidence before changing code
2. **One change at a time** — Changing two things makes both results uninterpretable
3. **Fail fast, fix forward** — Validate inputs early; don't let bad data propagate
4. **Preserve context** — Include stack traces, timestamps, and metadata in errors
5. **Write meaningful messages** — "User not found for ID=abc123" beats "Error occurred"
6. **Clean up resources** — Always close connections, files, and handles in `finally` blocks
7. **Add the missing test** — Every bug fixed is a test that should have existed
8. **Document surprising fixes** — If it took >30 min to find, write it down for future you
