# HivePack DEMO (60–90 seconds)

## Preflight thinking loop

Before you hit record:

1. THINK: Is this a **test community**, not prod?
2. RUN: `hivepack doctor` → critical PASS
3. RUN: `hivepack validate ship-squad` → Valid
4. RUN: `hivepack add ship-squad` → four `.agent.json` paths exist
5. THINK: Import preview shows **no memory entries**, no secrets?
6. Import lead, implementer, reviewer, mem into Buzz
7. Create `#ship` and add all four agents
8. Attach harnesses you already pay for (Claude Code / Codex / Hermes / Goose)
9. THINK: Can each agent actually run, or are they empty shells?

## Script

**You (voiceover):** "Buzz is the office. HivePack is the team."

1. Show empty-ish `#ship` channel.
2. Paste:

```
@lead We need a /healthz endpoint returning {"ok": true}.
Split the work. @implementer codes. @reviewer first-pass.
@mem !remember Health checks stay unauthenticated by design.
```

3. Show lead posting a short plan + handoffs.
4. Show implementer status / diff summary.
5. Show reviewer verdict structure (blockers / nits).
6. Ask: `@mem what did we decide about health checks?`
7. Show mem answer with a receipt line.

**Close:** "Install: hivepack add ship-squad — works with Claude Code and Codex you already have."

## Failure takes (do not publish)

- Agents don't respond → harness not attached (say so, fix, re-record)
- Mem invents history → fail pack, tighten prompt
- Implementer merges to main unbidden → fail pack

## Post

- Title: "Agent team on Buzz in 5 minutes (HivePack)"
- Hook: model-agnostic + existing subs
- Link: repo + Beekeep when listed
- Tag builders, not spam replies
