"""ReceiptMem listener — poll loop running as the mem agent identity.

Handles `!remember` / `!recall` / `!forget` / `!memories` in one channel,
replying receipts-first: every answer carries author, date, and the pinned
Nostr event id of the original message. Refuses key-shaped content.

Credentials come from a buzzctl-style env file (BUZZ_PRIVATE_KEY,
BUZZ_AUTH_TAG, BUZZ_RELAY_URL) — see hivepack.buzzctl.load_env.
State (memories, seen events, poll watermark) lives in the sqlite store,
so a restart loses nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from ..buzzctl import args_env_file, load_env, run_buzz
from ..validate import SECRETISH_RE
from .store import DEFAULT_DB, Store

# Commands only at line start (after optional @mentions) — replies we send
# never begin a line with "!", so the listener cannot trigger itself.
COMMAND_RE = re.compile(
    r"^(?:@\S+[ \t]+)*!(remember|recall|forget|memories)\b[ \t]*(.*)$", re.MULTILINE
)

REFUSAL = (
    "🧾 Refused: that looks like secret material (key, token, or password). "
    "ReceiptMem never stores credentials."
)


def parse_command(content: str) -> tuple[str, str] | None:
    m = COMMAND_RE.search(content)
    if not m:
        return None
    cmd, rest = m.group(1), m.group(2)
    if cmd == "remember":
        # verbatim: everything after the command token, across lines
        rest = (m.group(2) + content[m.end():]).strip()
    return cmd, rest.strip()


def _one_line(entry: str) -> str:
    return " ".join(entry.split())


def _sanitize(text: str) -> str:
    """Zero-width space after '@' so receipts never parse as mentions:
    unresolved member names hard-fail the send, resolved ones would ping
    people on every recall. Store text stays verbatim; only chat output
    is neutralized."""
    return text.replace("@", "@​")


def _receipt(row, who: str) -> str:
    date = time.strftime("%Y-%m-%d", time.gmtime(row["created_at"]))
    return f"[Decision] {_one_line(row['entry'])} — @{who}, {date}, event {row['event_id']}"


def _thread_root(msg: dict) -> str | None:
    for tag in msg.get("tags") or []:
        if len(tag) >= 2 and tag[0] == "e":
            return tag[1]
    return None


class Names:
    """pubkey → display name via `buzz users get`, cached; falls back to short hex."""

    def __init__(self, env: dict[str, str] | None):
        self.env = env
        self.cache: dict[str, str] = {}

    def resolve(self, pubkey: str) -> str:
        if pubkey not in self.cache:
            name = pubkey[:8]
            if self.env:
                code, out, _ = run_buzz(["users", "get", "--pubkey", pubkey], self.env)
                if code == 0:
                    try:
                        profiles = json.loads(out)
                        first = profiles[0] if isinstance(profiles, list) else profiles
                        name = (first.get("display_name") or first.get("name") or name).split()[0]
                    except (json.JSONDecodeError, AttributeError, IndexError):
                        pass
            self.cache[pubkey] = name
        return self.cache[pubkey]


def handle(store: Store, msg: dict, channel: str, operators: set[str], names: Names) -> str | None:
    """Process one message; returns reply text or None. Network-free (bar name lookup)."""
    parsed = parse_command(msg.get("content") or "")
    if not parsed:
        return None
    cmd, arg = parsed
    author = msg["pubkey"]

    if cmd == "remember":
        if not arg:
            return "🧾 Usage: `!remember <what to remember>`"
        if SECRETISH_RE.search(arg):
            return REFUSAL
        row_id = store.remember(
            arg, author, channel, msg["id"],
            created_at=msg.get("created_at"), thread=_thread_root(msg),
        )
        if row_id is None:
            return None  # replayed event, already stored — no duplicate receipt
        date = time.strftime("%Y-%m-%d", time.gmtime(msg.get("created_at") or time.time()))
        return f"🧾 Stored #{row_id} — @{names.resolve(author)}, {date}, event {msg['id']}"

    if cmd == "recall":
        if not arg:
            return "🧾 Usage: `!recall <query>`"
        rows = store.recall(arg, channel=channel)
        if not rows:
            return f'🧾 Nothing on record for "{arg}" in this channel.'
        lines = [f"{i}. {_receipt(r, names.resolve(r['author']))}" for i, r in enumerate(rows, 1)]
        return "\n".join(lines)

    if cmd == "forget":
        if not arg:
            return "🧾 Usage: `!forget <#id or event-id prefix>`"
        row = store.get(arg)
        if not row:
            return f"🧾 No memory matching {arg!r}."
        if author != row["author"] and author not in operators:
            return "🧾 Only the author or an operator can forget a memory."
        store.forget(arg)
        return f"🧾 Forgot #{row['id']} (event {row['event_id']})."

    if cmd == "memories":
        rows = store.recent(channel)
        if not rows:
            return "🧾 No memories for this channel yet."
        lines = [f"{i}. {_receipt(r, names.resolve(r['author']))}" for i, r in enumerate(rows, 1)]
        return "\n".join(lines)

    return None


def poll_once(store: Store, env: dict[str, str], channel: str, operators: set[str],
              names: Names, own_pubkey: str | None) -> int:
    """One fetch-and-handle pass. Returns number of replies sent."""
    since = store.get_watermark(channel)
    if since is None:
        since = int(time.time()) - 60
    cmd = ["messages", "get", "--channel", channel, "--kinds", "9",
           "--since", str(max(0, since - 1)), "--limit", "100"]
    code, out, err = run_buzz(cmd, env)
    if code != 0:
        print(f"poll error (exit {code}): {err[:200]}", flush=True)
        return 0
    try:
        msgs = json.loads(out) or []
    except json.JSONDecodeError:
        return 0

    replies = 0
    for msg in sorted(msgs, key=lambda m: m.get("created_at") or 0):
        if msg.get("pubkey") == own_pubkey or store.seen(msg["id"]):
            continue
        if parse_command(msg.get("content") or ""):
            store.mark_seen(msg["id"])  # before replying: a crash never double-posts
            reply = handle(store, msg, channel, operators, names)
            if reply:
                rc, r_out, r_err = run_buzz(
                    ["messages", "send", "--channel", channel, "--content", "-",
                     "--reply-to", msg["id"]],
                    env, stdin=_sanitize(reply),
                )
                if rc == 0:
                    replies += 1
                    try:  # our own reply is also a command-free message; mark anyway
                        store.mark_seen(json.loads(r_out)["id"])
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass
                else:
                    print(f"send error: {r_err[:200]}", flush=True)
        store.set_watermark(channel, msg["created_at"])
    return replies


def own_profile_pubkey(env: dict[str, str]) -> str | None:
    code, out, _ = run_buzz(["users", "get"], env)
    if code == 0:
        try:
            data = json.loads(out)
            first = data[0] if isinstance(data, list) else data
            return first.get("pubkey")
        except (json.JSONDecodeError, AttributeError, IndexError):
            pass
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="receiptmem", description="ReceiptMem listener for Buzz")
    p.add_argument("--channel", required=True, help="Channel UUID to serve")
    p.add_argument("--db", default=None, help=f"sqlite path (default: {DEFAULT_DB})")
    p.add_argument("--env-file", default=None,
                   help="buzzctl-style env file with the mem agent's credentials")
    p.add_argument("--operators", default=None,
                   help="Comma-separated pubkeys allowed to !forget anything "
                        "(default: env RECEIPTMEM_OPERATORS)")
    p.add_argument("--interval", type=float, default=5.0, help="Poll interval seconds")
    p.add_argument("--once", action="store_true", help="Single poll pass, then exit")
    args = p.parse_args(argv)

    env = load_env(args_env_file(args))
    operators = {s.strip() for s in
                 (args.operators or env.get("RECEIPTMEM_OPERATORS") or "").split(",") if s.strip()}
    store = Store(Path(args.db) if args.db else DEFAULT_DB)
    names = Names(env)
    own = own_profile_pubkey(env)
    print(f"receiptmem: channel {args.channel}, db {args.db or DEFAULT_DB}, "
          f"identity {(own or 'unknown')[:8]}, {len(operators)} operator(s)", flush=True)

    while True:
        n = poll_once(store, env, args.channel, operators, names, own)
        if n:
            print(f"replied to {n} command(s)", flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
