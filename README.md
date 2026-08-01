# HivePack

Opinionated **multi-agent team packs** for [Buzz](https://buzz.xyz) (Block).

HivePack ships:
1. A real **Buzz Persona Pack** (`packs/ship-squad`) — validates with `buzz pack validate`
2. **Beekeep-compatible** `.agent.json` snapshots (memory level `none`)
3. A small CLI: `doctor`, `validate`, `add`, `verify`, `export-snapshots`

## Why

Buzz already gives you the office. HivePack installs a **ready-made squad** (lead + implementer + reviewer + receipt memory) so you are not hand-crafting four personas every time.

## Quick start

```bash
cd hivepack
python3 -m pip install -e '.[dev]'

hivepack doctor
hivepack validate ship-squad
hivepack add ship-squad
hivepack verify ship-squad
```

If Buzz CLI is on your PATH:

```bash
buzz pack validate packs/ship-squad
buzz pack inspect packs/ship-squad
```

Then follow the checklist printed by `hivepack add` to import snapshots into Buzz Desktop.

## Commands

| Command | Purpose |
|---------|---------|
| `hivepack list` | Built-in packs |
| `hivepack doctor` | Local Buzz/harness environment |
| `hivepack validate [pack]` | Schema + safety + role-boundary checks (emits THINK lines) |
| `hivepack export-snapshots` | Write `*.agent.json` under `packs/.../snapshots` |
| `hivepack add [pack]` | Validate + export + import checklist |
| `hivepack verify [pack]` | Adversarial gates (doctor → validate → snapshots → buzz → pytest) |
| `hivepack convert <agent> --pack <name> --skills a,b` | Convert a local Claude Code agent (`.claude/agents/*.md`) into a Buzz persona, bundling its skills from `~/.claude/skills` |
| `hivepack demo` | Demo script preflight |

## Ship Squad agents

| Agent | Job |
|-------|-----|
| lead | Plan, split, steer |
| implementer | Code / tests / PRs |
| reviewer | First-pass review |
| mem | Receipt-backed remember/recall |

## Verification thinking loops

Every `validate` and `verify` run prints **THINK** diagnostics before conclusions, e.g.:

- layout adversarial checks
- persona secret scan
- team role coherence
- distribution safety (memory none)
- official `buzz pack validate` when available

Do not ship a pack that fails `hivepack verify`.

## Formats (source of truth)

- Persona Pack: `block/buzz` → `crates/buzz-persona/PERSONA_PACK_SPEC.md`
- Snapshots: `buzz-agent-snapshot` v1 (`.agent.json`)
- Beekeep listings: config-only snapshots, memory **None**

## Safety

- No secrets in packs
- Snapshots never include keys, env, relay URLs, or memory entries
- Default pack refuses production-merge autonomy without human approval (prompt-level)

## License

Apache-2.0
