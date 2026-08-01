# Ship Squad

HivePack's default multi-agent team for Buzz.

## Agents

| Persona | Role |
|---------|------|
| lead | Orchestrate and split work |
| implementer | Code, tests, PRs |
| reviewer | First-pass review |
| mem | Receipt-backed memory |

## Install

```bash
# From this monorepo
hivepack doctor
hivepack validate packs/ship-squad
hivepack add ship-squad

# If buzz CLI is available
buzz pack validate packs/ship-squad
buzz pack inspect packs/ship-squad
```

## Demo prompt (after agents are in a channel)

```
@lead Add a /healthz endpoint that returns {"ok": true}. 
@implementer owns the code. @reviewer does first-pass. 
@mem remember the decision that health checks stay unauthenticated.
```

## Safety

Config-only snapshots. No secrets. Memory level none in Beekeep exports.
