# Community Squad

HivePack's community onboarding pack for Buzz: a greeter that welcomes each
new member exactly once, and a rules desk that answers "what's allowed here"
straight from your channel canvas.

## Agents

| Persona | Role |
|---------|------|
| greeter | One warm welcome per member, triggered by join events only |
| rules | Quotes house rules verbatim from the canvas, escalates gray areas |

## Install

```bash
# From this repo
hivepack doctor
hivepack validate community-squad
hivepack add community-squad

# If buzz CLI is available
buzz pack validate packs/community-squad
buzz pack inspect packs/community-squad
```

Import each snapshot in Buzz Desktop (Agents → Import), then set the harness
environment per agent (snapshots cannot carry env vars by format design):

- **rules** — the pack defaults from `acp.env`:
  `BUZZ_ACP_SUBSCRIBE=all`, `BUZZ_ACP_KINDS=9`
- **greeter** — the join-event override:
  `BUZZ_ACP_SUBSCRIBE=all`, `BUZZ_ACP_KINDS=40099`

Kind 40099 is the channel-join event. With that override the greeter wakes
only when someone joins, so chat traffic can never spam it.

## Set up the canvas

Both agents read the community handbook from the channel canvas:

1. Open your channel's canvas and paste in `canvas/handbook-template.md`.
2. Fill in the community name, pitch, "Start here" pointers, house rules,
   and moderators. Delete what you don't use.
3. Keep rules numbered and one sentence each — the rules agent quotes them
   verbatim by number.

## Demo prompt (after import + canvas setup)

```
Have a friend join the channel — greeter should post one welcome and then
go quiet, even if they rejoin.

@rules is it ok to post a link to my own product?
```

The rules agent should quote your promotion rule word for word, or escalate
to your moderators if you never wrote one.

## Safety

Config-only snapshots. No secrets. Memory level none in Beekeep exports.
Agents cite and welcome; humans moderate.
