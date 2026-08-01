# HivePack Roadmap

What Buzz is missing, what users are asking for, and how HivePack fills it.
Each workstream is scoped to be built independently. Status keys:
SHIPPED, READY (spec complete, start building), SPEC (needs a design pass).

---

## 0. Fleet hardening: durable respond-to (SHIPPED)

**Root cause (found by reading block/buzz `managed_agents/` source, not by
store diffing).** The managed-agents store mixes two record kinds: key-less
DEFINITION records (`display_name` set, empty `pubkey`) and INSTANCE records
(`pubkey` set, `name` set, `display_name` null). `BUZZ_ACP_RESPOND_TO` is
spawned from the INSTANCE record's `respond_to`. The old `fleet set` matched
on `display_name`, so it only ever edited definition records — whose
`respond_to` field is cosmetic and reset to `owner-only` by every persona
save (`AgentDefinition::into_agent_record` fills it with
`RespondTo::default()`). That reset is the "revert" fleet status showed; the
instances were never edited at all.

**Suspects cleared.** `teams.json` holds only the builtin Welcome Team.
`retention.db` (per-scope, `agents/retention/<scope>.db`) is real but needs
no direct writes: the desktop's boot reconcile
(`reconcile_agents_to_events`, present in the installed build) projects
edited instance records into signed kind:30177 events with a monotonic
`created_at` bump and `pending_sync=1`, and the flush loop publishes them to
the relay. Editing the instance records while the desktop is quit IS the
durable path.

**Fix.** `fleet set` now matches records by `display_name` OR `name`;
`--respond` writes `respond_to` on instance records (the value that spawns)
and `definition_respond_to` on definition records (seeds future instances).
`fleet status` reads instance truth merged with definition env. Unit tests
against a fixture store in `tests/test_buzzctl.py`.

**Verified.** `fleet set --respond anyone --all` → all 21 instance records,
all 21 retained kind:30177 events (synced, `pending_sync=0`), and every live
`buzz-acp` process env (`ps eww`) show `anyone` across three desktop
quit/relaunch cycles.

**Still open (moved to workstream 6).** Foreign-owner reply test needs a
second identity; `agents draft-create --respond-to` upstream would remove
the need for post-create flips.

---

## 1. buzzctl fleet + mem portability (SHIPPED (harden next))

`fleet status` (table or `--json`), `fleet set` (bulk model / runtime /
respond / env / avatar with automatic desktop quit, backup, relaunch),
`mem-export` / `mem-import` (engram round-trip via `buzz mem`, solving the
"my agent's memories are trapped on this machine" problem).

**Hardening list.** Unit tests against a fixture store; `fleet set --dry-run`;
`fleet doctor` cross-check of store values vs live process env (catches the
respond-to drift automatically); ghost-record cleanup subcommand (archived
builtins leave stubs behind).

---

## 2. ReceiptMem: provenance-first workspace memory (READY)

**Problem.** Multi-agent chat gets amnesia. Buzz engrams are per-agent and
per-machine; channel knowledge evaporates. The community's most-wished item.

**Shape.** A memory agent + a real store + an MCP tool, so OTHER agents can
recall shared context, not just the memory agent itself.

**Components.**
- `receiptmem/store.py`: sqlite with FTS5: entry, author pubkey, channel,
  thread, event id, created_at, salience, tombstone.
- `receiptmem/listener.py`: buzz-cli subscription loop as the mem agent
  identity: `!remember` (verbatim, high salience), `!recall <q>`, `!forget
  <id>` (author or operator only), plus passive decision-distillation from
  messages it sees (subscribe=all, kinds=9).
- `receiptmem/mcp_server.py`: one tool: `recall(query, channel?) ->
  [{text, author, date, event_id}]`, so every agent's harness can query
  shared memory. This is the moat: memory as infrastructure, not a chatbot.
- Persona: reply format is receipts-first (`[Decision] … — @who, date,
  event <id>`), refuses to store secrets, never invents history.

**MVP cut.** Store + listener + `!remember`/`!recall` with receipts. Distill
mode and MCP server are v2. Prompt-only mem personas (like ship-squad's)
migrate by pointing at the same store.

**Acceptance gates.** Recall returns the pinned event id of the original
message; restart loses nothing; a second agent retrieves a memory stored via
the first through the MCP tool.

**Estimate.** Two to three sessions. Highest product value on this list.

---

## 3. StopGate kit: approval, CI, and budget gates (READY)

**Problem.** Trust is the #1 objection to agent teams. Buzz's MCP lifecycle
hooks (`_Stop`, see `docs/MCP_DRIVEN_HOOKS.md` in block/buzz) exist but
first-party gate glue is unfinished. An agent should not be able to end its
turn with red CI or without human sign-off.

**Components.**
- `stopgate/server.py`: MCP server implementing `_Stop`: returns "object"
  (keep working / wait) until gates pass.
- Gates, each independently configurable per agent:
  - `ci`: latest GitHub Actions run on the working branch is green
    (`gh run list/watch`).
  - `approval`: a designated human has reacted 👍 to the agent's
    wrap-up message (poll `buzz reactions`).
  - `budget`: session spend estimate under $N (token counting per harness).
  - `secrets`: last tool outputs contain no key-shaped material (reuse
    hivepack's SECRETISH scan).
- `stopgate.toml`: per-agent gate config; ships with sane defaults for
  implementer-type agents.

**MVP cut.** `ci` + `approval` gates, wired to one agent, with a 60-second
demo: agent finishes work, tries to stop, gets objected, waits for the 👍.

**Acceptance gates.** Agent provably cannot end turn on red CI; approval
reaction releases it within one poll interval; gates fail OPEN after a
configurable timeout so a dead gate never bricks an agent.

**Estimate.** Two sessions. Best demo-clip potential of the list.

---

## 4. Branch Theater: visible agent work (SPEC)

**Problem.** "I lose fidelity of what agents are doing": agent work is
buried in prose. Diffs, tool calls, and CI status deserve rich rendering.

**Shape.** A renderer bot subscribed to NIP-34 git events (patches, PRs,
issues via `buzz patches/pr/issues`) that posts threaded cards: diffstat,
files touched, CI badge, review status, links. v2: tool-trace summaries from
harness transcripts. Needs a design pass on card format inside Buzz's
markdown limits before building.

**Estimate.** Spec session + two build sessions.

---

## 5. Community pack: greeter, rules, onboarding (SHIPPED)

A second built-in pack for hivepack: `community-squad`.
- **greeter**: wakes ONLY on channel-join events (`BUZZ_ACP_KINDS=40099`),
  so chat cannot spam it. One warm welcome per member, never twice. Proven
  pattern, generalized from the privately validated original.
- **rules**: answers "what's allowed here" from the channel canvas, cites
  the rule verbatim, escalates gray areas to moderators.
- **canvas template**: starter handbook (`canvas/handbook-template.md`):
  start-here, desks, pipeline, house rules, moderators.

Shipped with both personas plus the template in one pass; `hivepack verify`
became pack-aware along the way (it had ship-squad's roster hardcoded).

---

## 6. Upstream PRs to block/buzz (SPEC, high goodwill)

1. `agents draft-create`: accept `--runtime`, `--model`, `--env`,
   `--respond-to` so programmatic creation carries full config (today only
   name + prompt survive the draft).
2. Agent key rotation: regenerate an agent's keypair in place; today the key
   is shown once and rotation means delete-and-recreate.
3. Snapshot v2: zip format carrying skills (spec'd as deferred in
   agent_snapshot.rs): hivepack convert is the natural test case.
4. Docs: `respond_to` vs `definition_respond_to` semantics and which store
   is canonical (findings from workstream 0).

---

## Suggested order

0 → 1-hardening → 2 (ReceiptMem) → 3 (StopGate) → 5 (community pack) → 6 → 4.

Rationale: 0 unblocks a promise fleet already makes; ReceiptMem is the
product; StopGate is the demo; the community pack is cheap distribution; the
upstream PRs compound goodwill while 2 and 3 are in review.
