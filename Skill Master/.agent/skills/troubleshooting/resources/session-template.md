# Troubleshooting Session Template

Copy this template when starting a structured troubleshooting session.

---

# Troubleshooting: {Issue Title}

**Date:** YYYY-MM-DD
**Severity:** Critical / High / Medium / Low
**Status:** Investigating / Root Cause Found / Fixed / Verified

---

## 1. Observe — Evidence

**Error Message / Stack Trace:**
```
Paste the full error here
```

**Relevant Logs:**
```
Paste relevant log output
```

**Context:**
- When did it start?
- Is it reproducible? (Always / Intermittent / Specific conditions)
- Who is affected?
- What changed recently?

---

## 2. Hypothesize — Theories

| # | Hypothesis | Evidence For | Evidence Against | Status |
| :--- | :--- | :--- | :--- | :--- |
| 1 | | | | ❓ Untested |
| 2 | | | | ❓ Untested |
| 3 | | | | ❓ Untested |

---

## 3. Isolate — Testing

| Test | Expected Result | Actual Result | Conclusion |
| :--- | :--- | :--- | :--- |
| | | | |
| | | | |

---

## 4. Root Cause

**What:** {One sentence description of root cause}
**Why:** {Why did this happen?}
**Where:** {File, line, function, or config where the bug lives}

---

## 5. Fix

**Change Made:**
```diff
- old code or config
+ new code or config
```

**Verification:**
- [ ] Original error no longer occurs
- [ ] Related functionality still works
- [ ] Edge cases handled
- [ ] Test added to prevent recurrence

---

## 6. Lessons Learned

- What made this hard to find?
- How could we have caught it earlier?
- Are there similar patterns elsewhere that need fixing?
