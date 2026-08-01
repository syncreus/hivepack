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

**Hardening list.** SHIPPED 2026-08-01: unit tests against a fixture store
(`tests/test_buzzctl.py`); `fleet set --dry-run` (prints planned changes,
never writes or bounces the desktop — a no-op set also skips the bounce);
`fleet doctor` cross-check of store values vs live process env (respond_to,
model, subscribe, kinds; flags drifted / not-running / unmanaged agents,
exit 2 on drift; env extraction is allowlisted so BUZZ_PRIVATE_KEY never
leaves the process line). Still open: ghost-record cleanup subcommand
(archived builtins leave stubs behind).

---

## 2. ReceiptMem: provenance-first workspace memory (SHIPPED (store + listener + MCP); distill is v2)

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

**MVP cut (shipped 2026-08-01).** `receiptmem/store.py` (sqlite + FTS5,
tombstone forgets, watermark + seen-event state) and `receiptmem/listener.py`
(`receiptmem --channel <uuid>`), handling `!remember`/`!recall`/`!forget`/
`!memories` with receipts pinned to the original message's event id. Refuses
key-shaped content (SECRETISH_RE). E2E-proven: store, two listener restarts,
recall returned the original event id. Distill mode and MCP server are v2.
Both mem personas updated to defer `!` commands to the daemon (the running
desktop mem agent double-posts until its persona is redeployed).

**Acceptance gates.** Recall returns the pinned event id of the original
message; restart loses nothing; a second agent retrieves a memory stored via
the first through the MCP tool.

**Estimate.** Two to three sessions. Highest product value on this list.

---

## 3. StopGate kit: approval, CI, and budget gates (SHIPPED (MVP: ci + approval))

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

**Shipped 2026-08-01.** `src/hivepack/stopgate/server.py` (console script
`stopgate`, stdlib-only MCP stdio server), README section with config +
60-second demo, 19 pytest cases including an stdio contract test that
drives the built server exactly like buzz-agent does. Red-CI blocking and
timeout fail-open proven by tests; approval release proven LIVE in the
`stopgate-demo` channel (native buzz-agent + qwen2.5:7b via ollama,
manual buzz-acp spawn): request posted on first `_Stop`, objection while
unreacted, `allow` on the poll after the 👍 from the configured approver.

**Learned building it.** Hooks fire only in the native `buzz-agent`
runtime (claude/codex/goose ACP harnesses never call them). The desktop
pins the MCP slot per-runtime (`BUZZ_ACP_MCP_COMMAND` is a reserved env
key and record `mcp_command` is ignored at spawn), so wiring is a manual
`buzz-acp` spawn until upstream allows per-record MCP override — worth
adding to the workstream-6 PR list. buzz-agent `env_clear()`s MCP
children (launcher must bake `STOPGATE_CONFIG`), and every `_Stop` must
answer inside 2.5s total or the objection silently becomes an allow —
the server budgets backend calls against a 2.0s deadline and skips them
(objecting with a retry note) when out of time.

**Next.** `budget` + `secrets` gates; desktop-managed wiring via upstream
PR; per-agent stopgate.toml distribution in packs.

---

## 4. Branch Theater: visible agent work (SHIPPED (MVP))

**Problem.** "I lose fidelity of what agents are doing": agent work is
buried in prose. Diffs, tool calls, and CI status deserve rich rendering.

**Shipped (2026-08-01).** `branchtheater` console script
(`src/hivepack/branchtheater.py`): polls the NIP-34 surface of watched
repos (`--repo OWNER_HEX:REPO_ID`, repeatable) and posts one markdown card
per new patch (kind:1617), PR (1618), and issue (1621) to a channel.
Patch cards carry subject, author, diffstat, and files touched (parsed
from the format-patch content); issue/PR titles come from the NIP-34
`subject` tag. State file records seen event ids AND each card's message
event id, so v2 can thread updates under the original card via
`messages send --reply-to`. Verified E2E in hive-test against a live
announced repo (`hivepack-demo`).

**Card format (design pass result).** Buzz messages render markdown but
cards must survive narrow sidebars: no tables, max 4 lines —
`🎭 **Patch** · repo — title` / `N file(s) · +A −B · by author` /
backticked file list (first 8) / `event <id8>`.

**v2.** Status-change lines threaded under cards — blocked upstream: the
buzz CLI can SET patch/PR/issue statuses (kind:1630-1633) but has no read
surface for them (noted in docs/upstream-buzz.md). CI badges (needs a CI
event source), tool-trace summaries from harness transcripts.

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

## 6. Upstream PRs to block/buzz (PREPPED — submission gated on owner go)

Drafts live in `docs/upstream-buzz.md`; the docs commit sits on branch
`hivepack/ws6-upstream` in the local buzz clone. Nothing submitted yet.

1. `agents draft-create` config flags: **deliberately restricted upstream**
   (explicit test: "chat creation cannot choose runtime, provider, model,
   or access" — an agent must not propose itself elevated config into a
   collapsed review form). Reshaped as an issue proposing a visible
   "proposed settings" panel; transport-side reference diff prepared
   (`docs/draft-create-config.reference.diff`). Local answer remains
   `buzzctl fleet set` post-create.
2. Agent key rotation: issue drafted (design questions on identity
   continuity + engram migration make this an issue, not a PR).
3. Snapshot v2 carrying skills: issue drafted; hivepack convert offered as
   the round-trip test case.
4. Docs — respond_to vs definition_respond_to and which store is canonical:
   **PR ready** (NIP-AP status paragraph was stale; live desktop already
   emits behavioral fields). Findings from workstream 0.

---

## Suggested order

0 → 1-hardening → 2 (ReceiptMem) → 3 (StopGate) → 5 (community pack) → 6 → 4.

Rationale: 0 unblocks a promise fleet already makes; ReceiptMem is the
product; StopGate is the demo; the community pack is cheap distribution; the
upstream PRs compound goodwill while 2 and 3 are in review.
