---
name: ship-protocol
description: Shared shipping protocol for HivePack squad handoffs, status, and safety rails.
---

# Ship protocol

## Handoff

```
Task: <one line>
Owner: @lead | @implementer | @reviewer | @mem | human
Done when: <testable>
Risks: <optional>
```

## Status

```
Status: blocked | in_progress | ready_for_review | done
Evidence: <tests/PR/path>
Next: <one action>
```

## Safety checklist

- [ ] No secrets in chat or commits
- [ ] Scope matches the ask
- [ ] Tests named or run
- [ ] Human approval before merge/deploy to protected branches
