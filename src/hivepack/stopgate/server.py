"""StopGate — MCP lifecycle gates for Buzz agents.

Implements buzz-agent's MCP-driven hook convention (docs/MCP_DRIVEN_HOOKS.md
in block/buzz): tools named with a leading `_` are hidden from the LLM and
called by the agent at lifecycle points. `_Stop` fires when the LLM signals
end_turn; non-empty text is an objection (agent keeps working), empty text
lets it stop.

Gates (per-agent config in stopgate.toml, path via STOPGATE_CONFIG):
  ci        latest GitHub Actions run on the working branch must be green
  approval  a human must react with the approval emoji to the wrap-up
            message the gate posts to a Buzz channel

Gates fail OPEN after `timeout_minutes` so a dead backend or an absent
human never bricks the agent. Every backend call is capped well under
buzz-agent's 2.5s hook timeout (two consecutive timeouts kill the server).

StopGate occupies the agent's single MCP server slot, displacing
buzz-dev-mcp and with it the native agent's reply path — so it also exposes
one visible tool, `send_message`, that posts to the approval channel.

Credentials: buzz-acp forwards BUZZ_RELAY_URL / BUZZ_PRIVATE_KEY /
BUZZ_AUTH_TAG into the MCP server env, so the gate posts as the agent
itself. `approval.env_file` (k=v lines, buzzctl style) is the manual
fallback.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

VERSION = "0.1.0"
GATE_CMD_TIMEOUT = 2.0  # keep every _Stop under buzz-agent's 2.5s hook cap

DEFAULTS: dict = {
    "timeout_minutes": 30,  # fail-open deadline; 0 = never
    "ci": {"enabled": False, "workdir": ".", "branch": ""},
    "approval": {
        "enabled": False,
        "channel": "",
        "emoji": "👍",
        "approvers": [],  # pubkeys allowed to approve; empty = anyone
        "message": "",
        "buzz_bin": "buzz",
        "env_file": "",
    },
}


def load_config(path: str | None = None) -> dict:
    p = Path(path or os.environ.get("STOPGATE_CONFIG") or "stopgate.toml")
    raw: dict = {}
    if p.is_file():
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
    else:
        print(f"stopgate: no config at {p}; all gates disabled", file=sys.stderr)
    cfg = {"timeout_minutes": raw.get("timeout_minutes", DEFAULTS["timeout_minutes"])}
    for section in ("ci", "approval"):
        cfg[section] = {**DEFAULTS[section], **raw.get(section, {})}
    return cfg


def _run(argv: list[str], *, cwd: str | None = None,
         env: dict[str, str] | None = None,
         timeout: float = GATE_CMD_TIMEOUT) -> tuple[int, str, str]:
    try:
        r = subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                           text=True, timeout=timeout, check=False)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, "", str(e)


def _budget(state: dict) -> float:
    """Remaining share of the current _Stop call's 2.5s hook window.

    A hook call that overruns the window counts as NO objection upstream,
    which would silently open the gate — so backend calls only get what's
    left of the window, and callers must skip the backend entirely (and
    object with a retry note) when less than MIN_CALL_BUDGET remains.
    """
    deadline = state.get("_stop_deadline")
    if deadline is None:
        return GATE_CMD_TIMEOUT
    return min(GATE_CMD_TIMEOUT, deadline - time.monotonic())


MIN_CALL_BUDGET = 0.35
RETRY_NOTE = "gate: ran out of time this attempt; try ending your turn again."


# ── ci gate ──────────────────────────────────────────────────────────────

def ci_check(cfg: dict, state: dict) -> str:
    ci = cfg["ci"]
    if not ci["enabled"] or state.get("ci_green"):
        return ""
    if _budget(state) < MIN_CALL_BUDGET:
        return "ci " + RETRY_NOTE
    workdir = os.path.expanduser(ci["workdir"])
    branch = ci["branch"]
    if not branch:
        code, out, err = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workdir)
        if code != 0:
            return f"ci gate: cannot resolve branch in {workdir} ({err.strip() or 'git failed'})."
        branch = out.strip()
    code, out, err = _run(
        ["gh", "run", "list", "--branch", branch, "--limit", "1",
         "--json", "status,conclusion,displayTitle,url"],
        cwd=workdir, timeout=_budget(state),
    )
    if code != 0:
        return (f"ci gate: could not check CI for {branch} "
                f"({err.strip() or 'gh failed'}). Retry ending your turn shortly.")
    try:
        runs = json.loads(out)
    except ValueError:
        return "ci gate: unparseable gh output; retry ending your turn shortly."
    if not runs:
        return ""  # no workflow runs on this branch — nothing to gate
    run = runs[0]
    title, url = run.get("displayTitle", ""), run.get("url", "")
    if run.get("status") != "completed":
        return (f"ci gate: CI is still running on {branch} ({title} {url}). "
                "Wait for it to finish (sleep, then re-check), then end your turn.")
    if run.get("conclusion") == "success":
        # ponytail: sticky green — CI won't flip red between end_turn attempts
        # unless the agent pushes again, and it stops once gates pass.
        state["ci_green"] = True
        return ""
    return (f"ci gate: CI is {run.get('conclusion') or 'red'} on {branch}: "
            f"{title} {url}. Fix the failure (or wait for a rerun), then end your turn.")


# ── approval gate ────────────────────────────────────────────────────────

DEFAULT_REQUEST = ("🛑 Wrap-up ready for review. React {emoji} to this message "
                   "to let me end my turn.")

_EMOJI_JUNK = re.compile("[️\U0001f3fb-\U0001f3ff]")  # VS16 + skin tones


def _norm_emoji(e: str) -> str:
    return _EMOJI_JUNK.sub("", e)


def _buzz_env(ap: dict) -> dict[str, str]:
    env = dict(os.environ)
    if ap["env_file"]:
        p = Path(os.path.expanduser(ap["env_file"]))
        if p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    env[k] = v
    return env


def approval_check(cfg: dict, state: dict) -> str:
    ap = cfg["approval"]
    if not ap["enabled"] or state.get("approved"):
        return ""
    if not ap["channel"]:
        return "approval gate: misconfigured (no channel set); ask the operator to fix stopgate.toml."
    if _budget(state) < MIN_CALL_BUDGET:
        return "approval " + RETRY_NOTE
    env = _buzz_env(ap)
    emoji = ap["emoji"]
    eid = state.get("request_event_id")
    if not eid:
        msg = ap["message"] or DEFAULT_REQUEST.format(emoji=emoji)
        code, out, err = _run(
            [ap["buzz_bin"], "messages", "send", "--channel", ap["channel"],
             "--content", msg], env=env, timeout=_budget(state))
        try:
            eid = json.loads(out).get("event_id") if code == 0 else None
        except ValueError:
            eid = None
        if not eid:
            return (f"approval gate: could not post the approval request "
                    f"({err.strip() or 'buzz send failed'}). Retry ending your turn shortly.")
        state["request_event_id"] = eid
        return (f"approval gate: posted the wrap-up approval request (event {eid}). "
                f"A human must react {emoji} before you can end your turn. "
                "Wait, then try ending your turn again.")
    code, out, err = _run([ap["buzz_bin"], "reactions", "get", "--event", eid], env=env,
                          timeout=_budget(state))
    if code == 0:
        try:
            reactions = json.loads(out).get("reactions", [])
        except ValueError:
            reactions = None
        if reactions is not None:
            approvers = set(ap["approvers"])
            for r in reactions:
                if _norm_emoji(r.get("emoji", "")) != _norm_emoji(emoji):
                    continue
                pubkeys = set(r.get("pubkeys", []))
                if not approvers or approvers & pubkeys:
                    state["approved"] = True
                    return ""
    return (f"approval gate: still waiting for a {emoji} reaction on event {eid}. "
            "Wait, then try ending your turn again.")


# ── hook + tool dispatch ─────────────────────────────────────────────────

def stop_verdict(cfg: dict, state: dict, now: float | None = None) -> str:
    t = time.monotonic() if now is None else now
    state.setdefault("started_at", t)
    state["_stop_deadline"] = time.monotonic() + 2.0  # 2.5s hook window minus overhead margin
    deadline_min = cfg["timeout_minutes"]
    if deadline_min and t - state["started_at"] > deadline_min * 60:
        print("stopgate: fail-open deadline reached, allowing stop", file=sys.stderr)
        return ""
    return ci_check(cfg, state) or approval_check(cfg, state)


def post_compact_note(cfg: dict, state: dict) -> str:
    if state.get("request_event_id") and not state.get("approved"):
        return (f"stopgate: an approval request is still outstanding "
                f"(event {state['request_event_id']}). You cannot end your turn "
                f"until a human reacts {cfg['approval']['emoji']} to it.")
    return ""


def send_message(cfg: dict, args: dict) -> tuple[str, bool]:
    content = args.get("content", "")
    channel = cfg["approval"]["channel"]
    if not content or not channel:
        return "send_message needs 'content' and a configured approval.channel", True
    code, out, err = _run(
        [cfg["approval"]["buzz_bin"], "messages", "send", "--channel", channel,
         "--content", content], env=_buzz_env(cfg["approval"]), timeout=10)
    if code != 0:
        return f"send failed: {err.strip() or out.strip() or code}", True
    return out.strip(), False


TOOLS = [
    {
        "name": "_Stop",
        "description": "Lifecycle gate: objects to end_turn until CI is green "
                       "and/or a human has approved the wrap-up.",
        "inputSchema": {"type": "object"},
    },
    {
        "name": "_PostCompact",
        "description": "Re-injects pending-approval state after context compaction.",
        "inputSchema": {"type": "object"},
    },
    {
        "name": "send_message",
        "description": "Post a message to this agent's Buzz channel. Use this to "
                       "reply and to post your wrap-up summary.",
        "inputSchema": {
            "type": "object",
            "properties": {"content": {"type": "string", "description": "Message text (markdown)"}},
            "required": ["content"],
        },
    },
]


def dispatch(name: str, args: dict, cfg: dict, state: dict) -> tuple[str, bool]:
    if name == "_Stop":
        with _hook_lock:
            text = stop_verdict(cfg, state)
        label = f"objection ({text[:90]}…)" if text else "allow"
        print(f"stopgate: _Stop -> {label}", file=sys.stderr)
        return text, False
    if name == "_PostCompact":
        return post_compact_note(cfg, state), False
    if name == "send_message":
        return send_message(cfg, args)
    return f"unknown tool: {name}", True


# ── MCP stdio loop (newline-delimited JSON-RPC; no SDK needed) ───────────

_hook_lock = threading.Lock()   # serializes gate state; a queued hook burns
                                # its own deadline and exits via RETRY_NOTE
_write_lock = threading.Lock()


def _reply(obj: dict) -> None:
    with _write_lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def serve() -> None:
    cfg = load_config()
    state: dict = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        rid = req.get("id")
        method = req.get("method", "")
        if method == "initialize":
            result = {
                "protocolVersion": (req.get("params") or {}).get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "stopgate", "version": VERSION},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            # threaded so a slow send_message can't head-of-line-block the
            # next _Stop past its 2.5s window
            params = req.get("params") or {}

            def _call(rid=rid, params=params):
                text, is_error = dispatch(params.get("name", ""),
                                          params.get("arguments") or {}, cfg, state)
                _reply({"jsonrpc": "2.0", "id": rid, "result":
                        {"content": [{"type": "text", "text": text}], "isError": is_error}})

            # non-daemon: interpreter waits for in-flight replies on stdin EOF
            threading.Thread(target=_call).start()
            continue
        elif method == "ping":
            result = {}
        elif rid is None:
            continue  # notification (e.g. notifications/initialized)
        else:
            _reply({"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"method not found: {method}"}})
            continue
        if rid is not None:
            _reply({"jsonrpc": "2.0", "id": rid, "result": result})


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
