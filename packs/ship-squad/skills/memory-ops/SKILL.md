---
name: memory-ops
description: Receipt-backed memory capture and recall conventions for HivePack mem agent.
---

# Memory ops

## Capture

Prefer durable facts:
- Decisions ("we will ship behind flag X")
- Action items with owner
- Explicit rollbacks / supersessions

Skip:
- Transient chatter
- Secrets
- Raw stack traces without conclusion

## Recall format

```
1. [Decision|Action|Note] <text>
   — @author, YYYY-MM-DD, event <id|unverified-local>
```

## Conflict

If two memories disagree, list both and ask which wins. Do not silent-merge.
