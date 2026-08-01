"""branchtheater — render NIP-34 git activity as cards in a Buzz channel.

Agent work is invisible when patches, PRs, and issues live only as relay
events. This bot polls the NIP-34 surface of watched repos and posts one
markdown card per new event to a channel, so the room sees diffstat-level
activity without leaving Buzz.

MVP scope: new-event cards for patches (kind:1617), PRs (1618), and issues
(1621). Status-change lines are v2: the buzz CLI can SET statuses
(kind:1630-1633) but has no read surface for them yet. The state file
records each card's message event id so v2 can thread updates under the
original card.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .buzzctl import DEFAULT_ENV_FILE, load_env, run_buzz

DEFAULT_STATE = Path.home() / ".local/share/branchtheater/state.json"

# (buzz subcommand, event label shown on the card)
SURFACES = (("patches", "Patch"), ("pr", "PR"), ("issues", "Issue"))


def load_state(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"seen": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)


def diffstat(patch_text: str) -> tuple[list[str], int, int]:
    """Files touched and +/- line counts from `git format-patch` content."""
    files: list[str] = []
    plus = minus = 0
    in_diff = False
    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            in_diff = True
            # "diff --git a/path b/path" — take the b/ side.
            parts = line.split(" b/", 1)
            if len(parts) == 2:
                files.append(parts[1].strip())
        elif in_diff and line.startswith("+") and not line.startswith("+++"):
            plus += 1
        elif in_diff and line.startswith("-") and not line.startswith("---"):
            minus += 1
    return files, plus, minus


def patch_meta(patch_text: str) -> dict:
    """Subject and author from a format-patch header."""
    meta = {"subject": "", "author": ""}
    for line in patch_text.splitlines()[:20]:
        if line.startswith("Subject:"):
            meta["subject"] = line.split(":", 1)[1].strip()
            # Strip the "[PATCH]"/"[PATCH 2/5]" prefix.
            if meta["subject"].startswith("[") and "]" in meta["subject"]:
                meta["subject"] = meta["subject"].split("]", 1)[1].strip()
        elif line.startswith("From:"):
            meta["author"] = line.split(":", 1)[1].strip().split("<")[0].strip()
    return meta


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def event_tag(event: dict, name: str) -> str:
    for tag in event.get("tags") or []:
        if isinstance(tag, list) and len(tag) >= 2 and tag[0] == name:
            return str(tag[1])
    return ""


def build_card(label: str, repo_id: str, event: dict) -> str:
    content = event.get("content") or ""
    eid = str(event.get("id") or "")[:8]
    if label == "Patch":
        meta = patch_meta(content)
        files, plus, minus = diffstat(content)
        title = meta["subject"] or event_tag(event, "subject") or first_line(content) or "(no subject)"
        by = f" · by {meta['author']}" if meta["author"] else ""
        lines = [
            f"🎭 **{label}** · `{repo_id}` — {title}",
            f"{len(files)} file(s) · +{plus} −{minus}{by}",
        ]
        if files:
            shown = ", ".join(f"`{f}`" for f in files[:8])
            more = f" (+{len(files) - 8} more)" if len(files) > 8 else ""
            lines.append(shown + more)
    else:
        # Issues and PRs carry the title as a NIP-34 `subject` tag.
        title = event_tag(event, "subject") or first_line(content) or "(no description)"
        if len(title) > 120:
            title = title[:117] + "…"
        lines = [f"🎭 **{label}** · `{repo_id}` — {title}"]
    lines.append(f"`event {eid}`")
    return "\n".join(lines)


def poll_once(env: dict, channel: str, repos: list[tuple[str, str]], state: dict) -> list[str]:
    """One pass over every repo surface; returns human log lines."""
    log: list[str] = []
    seen: dict = state.setdefault("seen", {})
    for owner, repo_id in repos:
        for cmd, label in SURFACES:
            code, out, err = run_buzz(
                [cmd, "list", "--repo-owner", owner, "--repo-id", repo_id], env
            )
            if code != 0:
                log.append(f"WARN {cmd} list {repo_id}: {err[:120]}")
                continue
            try:
                events = json.loads(out) if out else []
            except json.JSONDecodeError:
                log.append(f"WARN {cmd} list {repo_id}: unparsable output")
                continue
            # Oldest first so cards land in chronological order.
            for ev in sorted(events, key=lambda e: e.get("created_at") or 0):
                eid = ev.get("id")
                if not eid or eid in seen:
                    continue
                card = build_card(label, repo_id, ev)
                c, o, e = run_buzz(
                    ["messages", "send", "--channel", channel, "--content", "-"],
                    env, stdin=card,
                )
                if c != 0:
                    log.append(f"WARN send card {eid[:8]}: {e[:120]}")
                    continue
                msg_id = ""
                try:
                    msg_id = json.loads(o).get("event_id", "")
                except (json.JSONDecodeError, AttributeError):
                    pass
                seen[eid] = {"kind": ev.get("kind"), "msg": msg_id}
                log.append(f"card {label.lower()} {eid[:8]} -> msg {msg_id[:8]}")
    return log


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="branchtheater", description=__doc__.splitlines()[0])
    p.add_argument("--channel", required=True, help="Channel UUID for cards")
    p.add_argument("--repo", action="append", required=True, metavar="OWNER_HEX:REPO_ID",
                   help="Watched repo (repeatable)")
    p.add_argument("--env-file", default=None, help=f"Credentials env file (default: {DEFAULT_ENV_FILE})")
    p.add_argument("--state", default=str(DEFAULT_STATE))
    p.add_argument("--interval", type=int, default=60, help="Poll seconds (ignored with --once)")
    p.add_argument("--once", action="store_true", help="Single poll pass, then exit")
    args = p.parse_args(argv)

    repos = []
    for spec in args.repo:
        owner, _, repo_id = spec.partition(":")
        if len(owner) != 64 or not repo_id:
            p.error(f"--repo must be OWNER_HEX:REPO_ID, got {spec!r}")
        repos.append((owner, repo_id))

    env = load_env(Path(args.env_file).expanduser() if args.env_file else DEFAULT_ENV_FILE)
    state_path = Path(args.state).expanduser()
    state = load_state(state_path)
    while True:
        for line in poll_once(env, args.channel, repos, state):
            print(line, flush=True)
        save_state(state_path, state)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
