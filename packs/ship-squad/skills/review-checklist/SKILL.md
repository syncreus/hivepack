---
name: review-checklist
description: Structured first-pass code review checklist for HivePack reviewer agent.
---

# Review checklist

## Always check

1. Correctness vs stated done criteria
2. Tests for behavior changes
3. Error handling on external I/O
4. AuthZ / tenancy boundaries if applicable
5. Secret leakage (logs, fixtures, env samples)
6. API/compat breakage

## Output shape

**Summary:** …

**Blockers:**
- …

**Questions:**
- …

**Nits:**
- …

**Verdict:** Approve | Request changes | Comment-only
