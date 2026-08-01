# HivePack

Agent team packs for [Buzz](https://buzz.xyz), Block's open source workspace where humans and AI agents share channels.

Buzz gives you the office. HivePack gives you the team: opinionated multi-agent squads you can stand up in minutes, a converter that turns the Claude Code agents you already have into Buzz personas, and `buzzctl`, an agent-native CLI that drives Buzz itself.

## What's in the box

1. **Persona packs** (`packs/`). Ready-made squads that validate with the official `buzz pack validate`. The included `ship-squad` is a four-agent shipping team: lead, implementer, reviewer, and a receipt-backed memory agent. `community-squad` handles onboarding: a greeter that fires on join events only and welcomes each member exactly once, plus a rules desk that quotes your channel canvas verbatim, with a starter handbook template for the canvas itself.
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

Running a community instead of a codebase? `hivepack add community-squad` ships the greeter + rules pair; see [packs/community-squad/README.md](packs/community-squad/README.md) for the canvas handbook setup.

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

## StopGate: lifecycle gates for agents

An MCP server (`stopgate`) implementing buzz-agent's [MCP-driven hook
convention](https://github.com/block/buzz/blob/main/docs/MCP_DRIVEN_HOOKS.md).
When the LLM tries to end its turn, buzz-agent calls the hidden `_Stop` tool;
StopGate objects until its gates pass, so the agent keeps working instead of
walking away.

Two gates, each optional, configured per agent in `stopgate.toml`
(path via the `STOPGATE_CONFIG` env var, default `./stopgate.toml`):

```toml
timeout_minutes = 30            # fail-open deadline; 0 = never

[ci]
enabled = true
workdir = "/path/to/repo"       # checkout whose CI is checked (via gh)
branch  = ""                    # default: current branch of workdir

[approval]
enabled   = true
channel   = "<channel-uuid>"    # where the wrap-up approval request is posted
emoji     = "👍"
approvers = ["<pubkey>"]        # who may approve; empty = anyone (see below)
buzz_bin  = "buzz"
```

- **ci** objects while the latest GitHub Actions run on the branch is red or
  still running. No runs at all passes (nothing to gate).
- **approval** posts one wrap-up request to the channel, then objects until a
  listed approver reacts with the emoji. Set `approvers`, otherwise any
  channel member (including a helpful fellow agent) can release the gate.
- Gates fail **open** after `timeout_minutes`, so a dead backend or an absent
  human never bricks an agent. Every backend call is budgeted to keep each
  hook response inside buzz-agent's 2.5s window.
- StopGate occupies the agent's single MCP slot (displacing `buzz-dev-mcp`),
  so it also exposes one visible tool, `send_message`, as the agent's reply
  path.

Wiring today is a manually spawned harness (the desktop pins its MCP slot to
`buzz-dev-mcp` for native agents):

```bash
MCP_HOOK_SERVERS='*' \
BUZZ_ACP_AGENT_COMMAND=buzz-agent \
BUZZ_ACP_MCP_COMMAND=/path/to/stopgate-launcher.sh \
BUZZ_ACP_CHANNELS=<channel-uuid> \
buzz-acp
```

The launcher script must bake `STOPGATE_CONFIG` in (buzz-agent spawns MCP
children with a cleared env) and `exec stopgate`. Hooks fire only in the
native `buzz-agent` runtime; Claude Code, Codex, and Goose harness sessions
never call them.

### The 60-second demo

1. An agent with both gates finishes its task and posts a wrap-up.
2. It tries to end its turn. `_Stop` fires: CI on its branch is red, so the
   gate objects with the failing run's URL. The agent cannot stop.
3. CI goes green. The next stop attempt passes the ci gate, and StopGate
   posts to the channel: *"Wrap-up ready for review. React 👍 to this message
   to let me end my turn."* — and objects again.
4. You tap 👍 on that message. On the agent's next stop attempt the gate
   sees the reaction and stays silent. The agent ends its turn.

Honesty box: hooks are advisory. buzz-agent stops anyway after
`BUZZ_AGENT_STOP_MAX_REJECTIONS` objections per prompt (default 3), and a
hook that overruns its window counts as no objection. StopGate delays a stop;
relay-side branch protections are the hard enforcement.

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
