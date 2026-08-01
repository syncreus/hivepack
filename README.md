# HivePack

Agent team packs for [Buzz](https://buzz.xyz), Block's open source workspace where humans and AI agents share channels.

Buzz gives you the office. HivePack gives you the team: opinionated multi-agent squads you can stand up in minutes, a converter that turns the Claude Code agents you already have into Buzz personas, and `buzzctl`, an agent-native CLI that drives Buzz itself.

## What's in the box

1. **Persona packs** (`packs/`). Ready-made squads that validate with the official `buzz pack validate`. The included `ship-squad` is a four-agent shipping team: lead, implementer, reviewer, and a receipt-backed memory agent.
2. **`hivepack convert`**. Reads a Claude Code agent file (`.claude/agents/*.md`), rewrites it as a Buzz persona with team etiquette bolted on, and bundles the skills it depends on so the agent runs on its real playbook instead of guessing.
3. **`buzzctl`**. A CLI for working with Buzz the way agents do: check your setup, list channels, and push a whole pack into Buzz as owner-reviewed agent drafts.

## Requirements

- Python 3.10+
- [Buzz](https://github.com/block/buzz) Desktop, and optionally the `buzz` CLI on your PATH (hivepack uses it for official validation and buzzctl wraps it)
- An AI harness the agents will run on: Claude Code, Codex, Goose, Grok, or Hermes. Agents use whatever subscriptions you already pay for.

## Install

```bash
git clone https://github.com/syncreus/hivepack
cd hivepack
python3 -m pip install -e '.[dev]'
hivepack doctor
```

`doctor` tells you what it found: the buzz CLI, Buzz Desktop, and which harnesses are on your PATH. Nothing else is needed for pack validation and export.

## Quick start: a squad in five minutes

```bash
hivepack validate ship-squad
hivepack add ship-squad
```

`add` validates the pack, exports one `.agent.json` snapshot per persona, and prints a checklist. Import each snapshot in Buzz Desktop (Agents, then Import), leave the harness at your default, invite the agents into a channel, and talk to them.

Faster path if you have agent credentials set up (see buzzctl below):

```bash
buzzctl draft-team ship-squad --channel <channel-uuid>
```

Each agent arrives in Buzz Desktop as a prefilled create form. You review and hit Save. Nothing is created without the owner's click, which is Buzz's own safety model.

## buzzctl

```
buzzctl doctor                     # credentials, relay round-trip, buzz binary
buzzctl channels                   # channels visible to the acting identity
buzzctl draft-team <pack> --channel <uuid> [--only a,b] [--runtime-for name=grok] [--dry-run]
```

buzzctl acts as an agent identity, because Buzz's draft flow is built for exactly that: an agent proposes, the owner approves. It reads credentials from an env file, never from arguments, so keys stay out of shell history and process lists.

Create `~/.config/buzzctl/agent.env` (or point `BUZZCTL_ENV_FILE` somewhere else):

```
BUZZ_PRIVATE_KEY=<an agent's nsec or hex key>
BUZZ_AUTH_TAG=<that agent's NIP-OA auth tag JSON>
BUZZ_RELAY_URL=<your community relay, e.g. wss://yourname.communities.buzz.xyz>
```

Any managed agent you already created in Buzz Desktop has these three values in its runtime environment. Keep the file at mode 600.

## Convert your Claude Code agents

```bash
hivepack convert --list
hivepack convert my-blogger --pack my-squad --skills blog-standard,style-guide
```

This takes `~/.claude/agents/my-blogger.md` (frontmatter or plain markdown, both work), preserves the original prompt, prepends a short Buzz team adapter (respond when mentioned, thread discipline, no secrets), and copies the named skills from `~/.claude/skills` into the pack as the agent's source of truth. Use `--skills-root` to pull skills from a project directory instead. Oversized skills ship as `SKILL.md` only.

Two guardrails:

- **Private blocklist.** Put one term per line in `~/.config/hivepack/blocklist.txt` (client names, employers, anything that must never appear in a shareable pack) and convert refuses any agent that matches. No file means no guard.
- **Snapshot hygiene.** Exported snapshots carry config only: no memory entries, no keys, no machine paths. `hivepack verify` enforces this along with the official validator.

## Always-on agents: the env vars

Buzz agents respond to mentions by default. Two variables, set per agent in Buzz Desktop under Advanced, change that:

```
BUZZ_ACP_SUBSCRIBE=all    # agent receives every channel message, not just mentions
BUZZ_ACP_KINDS=9          # kind 9 = chat messages
```

Subscription is not reply permission: the agent sees the conversation for context but reply gating is separate, so your channel does not turn into agent spam. Every pack ships an `acp.env` documenting this. One fun variant: `BUZZ_ACP_KINDS=40099` wakes an agent only when someone joins a channel, which makes a greeter that cannot be spammed by chat.

## Commands

| Command | Purpose |
|---------|---------|
| `hivepack list` | Built-in packs |
| `hivepack doctor` | Local Buzz and harness environment |
| `hivepack validate [pack]` | Schema, safety, and role-boundary checks |
| `hivepack export-snapshots [pack]` | Write `.agent.json` snapshots (memory none) |
| `hivepack add [pack]` | Validate, export, print the import checklist |
| `hivepack verify [pack]` | Full gate chain: doctor, validate, snapshots, official buzz validate, pytest |
| `hivepack convert <agent>` | Claude Code agent to Buzz persona, skills bundled |
| `buzzctl draft-team <pack>` | Push a pack into Buzz as owner-reviewed drafts |

## Formats

- Persona packs follow the spec in `block/buzz` at `crates/buzz-persona/PERSONA_PACK_SPEC.md`
- Snapshots are `buzz-agent-snapshot` v1 (`.agent.json`), always memory level none
- Everything here passes `buzz pack validate` when the CLI is present; `hivepack verify` treats that as the source of truth

## Safety

- No secrets in packs, ever. Validation scans for key-shaped material and fails hard.
- Snapshots never include keys, env vars, relay URLs, or memory entries.
- Draft creation is owner-reviewed by design. buzzctl cannot create an agent behind your back.
- The default squad prompts refuse production deploys and merges without a human approval in-channel.

## License

Apache-2.0
