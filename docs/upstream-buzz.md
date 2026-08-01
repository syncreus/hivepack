# Upstream contributions to block/buzz (ROADMAP workstream 6)

Prepared drafts. Nothing here has been submitted; each item below is ready
to file once Daniel says go. The docs change exists as a commit on branch
`hivepack/ws6-upstream` in the local buzz clone
(`~/projects/buzz/.worktrees/ws6-upstream`, commit `f313473`).

## PR (ready): NIP-AP behavioral-fields status + "which respond_to is live"

**Branch:** `hivepack/ws6-upstream`, one commit touching
`docs/nips/NIP-AP.md` only.

**Body draft:**

> The "Status: reserved" paragraph under Optional fields predates the
> current implementation. As of the current desktop, writers emit
> `respond_to` / `respond_to_allowlist` / `parallelism` on kind:30175
> events whenever they are set locally (verified against a live retention
> store), the local definition store carries them
> (`definition_respond_to` etc. on key-less records in the unified agent
> store), and instance creation resolves explicit input > definition
> default > client default.
>
> This PR updates the status paragraph and adds a short "Which value is
> live?" note. The note exists because the two same-named fields invite a
> real operator error we hit while building fleet tooling: editing the
> definition-level value and expecting a running agent's gate to change.
> The instance-level value (kind:30177 head) is what the spawner enforces;
> the definition value only seeds new instances.

## Issue draft: draft-create cannot carry config (deliberate) — surface it in the review form instead

Roadmap 6.1 assumed `agents draft-create` should accept `--runtime
--model --env --respond-to`. Reading the code shows the asymmetry is
deliberate, not an oversight: `desktop/src/features/agents/agentManagement.ts`
rejects create requests with any key beyond
channelId/displayName/systemPrompt, and there is an explicit test named
"chat creation cannot choose runtime, provider, model, or access". The
protection makes sense: create drafts arrive from agent identities, and an
agent should not be able to propose itself `respond_to: anyone` plus an
elevated runtime into a review form whose advanced section renders
collapsed.

Proposed issue: keep the restriction, but let the create form carry a
*visible* proposal. Concretely: accept the same optional quad the update
path already accepts (runtime/provider/model/respondTo), and render any
proposed values expanded and highlighted in the owner review form (never
collapsed), so the owner explicitly sees what the agent asked for before
saving. A reference diff for the transport side (CLI + parser + tests,
~185 lines) is prepared and can be attached; the real work is the form UX.
Until then the working pattern is post-create configuration by the owner
(hivepack's `buzzctl fleet set`).

## Issue draft: agent key rotation in place

Today an agent's private key is shown once at creation and there is no
rotation: replacing a compromised or lost key means delete-and-recreate,
which loses engrams (NIP-AE memory is keyed to the agent identity),
channel membership, and message history attribution. Proposed issue:
`buzz agents rotate-key <pubkey>` producing a new keypair for the same
managed-agent record, with (a) a kind:30177 head published for the new
pubkey carrying a `rotated_from` link, (b) engram re-encryption or a
migration path for `mem/*` entries, and (c) the old key tombstoned via
NIP-09. Needs upstream design input on how relays should treat the
continuity link; filing as a design issue, not a PR.

## Issue draft: snapshot v2 carrying skills

`agent_snapshot.rs` specs skills as deferred. hivepack's `convert` bundles
`~/.claude/skills/` into packs today and is a natural round-trip test
case: export a snapshot of an agent with bundled skills, import it on a
second machine, agent still has its skills. Offer: we can contribute the
test fixtures and a draft of the zip layout from hivepack's pack format if
the maintainers want to pick the format discussion back up.

## Issue draft: no read surface for NIP-34 status events

`buzz patches/pr/issues status` can SET kind:1630-1633 status events, but
nothing in the CLI reads them back: `list` returns only the root events
and `get --event` returns the single event with no status envelope. Any
tool that wants to render current status (Branch Theater's card threads,
CI-style dashboards) has to speak raw relay filters. Proposed issue:
either a `--with-status` flag on `list`/`get`, or a `status get` twin to
`status`.

## Submission checklist (when approved)

1. `gh repo fork block/buzz --clone=false` under the syncreus (or
   personal) account; add fork remote to the buzz clone.
2. Push `hivepack/ws6-upstream`, open the docs PR with the body above.
3. File the three issues; attach
   `draft-create-config.reference.diff` to the first.
