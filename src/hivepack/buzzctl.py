"""buzzctl — agent-native CLI for driving Buzz, built CLI-Anything style.

Wraps the official `buzz` CLI with the flows hivepack needs:
  - doctor:     credentials + relay + binary sanity
  - channels:   list channels visible to the acting identity
  - draft-team: push a hivepack pack into Buzz as owner-reviewed agent drafts

Conventions (per HKUDS/CLI-Anything): every command supports --json for
machine output; human output is short tables; exit 0 ok / 1 bad input /
2 downstream failure. Credentials come from an env file (never argv) so
secrets stay out of process lists and transcripts.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .constants import PACKS_DIR
from .doctor import which
from .persona import parse_persona_md

DEFAULT_ENV_FILE = Path(
    os.environ.get("BUZZCTL_ENV_FILE", str(Path.home() / ".config" / "buzzctl" / "agent.env"))
)
MANAGED_AGENTS = Path.home() / "Library/Application Support/xyz.block.buzz.app/agents/managed-agents.json"


def load_env(env_file: Path) -> dict[str, str]:
    if not env_file.is_file():
        raise SystemExit(f"env file missing: {env_file} (capture agent creds first)")
    env = dict(os.environ)
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v
    return env


def run_buzz(args: list[str], env: dict[str, str], *, stdin: str | None = None) -> tuple[int, str, str]:
    buzz = which("buzz")
    if not buzz:
        raise SystemExit("buzz CLI not on PATH")
    proc = subprocess.run(
        [buzz, *args], env=env, input=stdin, capture_output=True, text=True, timeout=60, check=False
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def existing_agent_names() -> set[str]:
    if not MANAGED_AGENTS.is_file():
        return set()
    try:
        recs = json.loads(MANAGED_AGENTS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    # First word only: display names carry emoji suffixes ("Editor 🗞️").
    names = set()
    for r in recs:
        if isinstance(r, dict) and r.get("display_name"):
            names.add(str(r["display_name"]).split()[0].strip().lower())
    return names


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = []
    env_ok = args_env_file(args).is_file()
    checks.append({"name": "env_file", "ok": env_ok, "detail": str(args_env_file(args))})
    checks.append({"name": "buzz_cli", "ok": bool(which("buzz")), "detail": which("buzz") or "missing"})
    relay = ""
    if env_ok:
        env = load_env(args_env_file(args))
        relay = env.get("BUZZ_RELAY_URL", "")
        checks.append({"name": "credentials", "ok": bool(env.get("BUZZ_PRIVATE_KEY")) and bool(env.get("BUZZ_AUTH_TAG")), "detail": "key+auth_tag present" if env.get("BUZZ_PRIVATE_KEY") else "missing"})
        code, out, err = run_buzz(["channels", "list"], env)
        checks.append({"name": "relay_roundtrip", "ok": code == 0, "detail": f"{relay} exit={code}" + (f" {err[:120]}" if code else "")})
    ok = all(c["ok"] for c in checks)
    if args.json:
        print(json.dumps({"ok": ok, "checks": checks}, indent=2))
    else:
        for c in checks:
            print(f"[{'OK ' if c['ok'] else 'NO '}] {c['name']}: {c['detail']}")
        print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 2


def args_env_file(args: argparse.Namespace) -> Path:
    return Path(args.env_file).expanduser() if args.env_file else DEFAULT_ENV_FILE


def cmd_channels(args: argparse.Namespace) -> int:
    env = load_env(args_env_file(args))
    code, out, err = run_buzz(["channels", "list"], env)
    if code != 0:
        print(err or out, file=sys.stderr)
        return 2
    print(out)
    return 0


def compose_prompt(pack_dir: Path, persona_body: str) -> str:
    instructions = pack_dir / "instructions.md"
    prompt = persona_body.strip()
    if instructions.is_file():
        prompt += "\n\n# Team instructions\n\n" + instructions.read_text(encoding="utf-8").strip()
    return prompt + "\n"


def cmd_draft_team(args: argparse.Namespace) -> int:
    pack_dir = Path(args.pack) if Path(args.pack).exists() else PACKS_DIR / args.pack
    if not (pack_dir / ".plugin" / "plugin.json").is_file():
        print(f"not a pack: {pack_dir}", file=sys.stderr)
        return 1
    env = load_env(args_env_file(args))
    plugin = json.loads((pack_dir / ".plugin" / "plugin.json").read_text(encoding="utf-8"))
    only = {s.strip().lower() for s in args.only.split(",")} if args.only else None
    existing = existing_agent_names()

    results = []
    for rel in plugin.get("personas") or []:
        persona = parse_persona_md(pack_dir / str(rel))
        if only and persona.name.lower() not in only:
            continue
        prompt = compose_prompt(pack_dir, persona.system_prompt)
        # Existing agent with the same display name → owner-reviewed update.
        base_display = persona.display_name.split()[0].strip().lower()
        is_update = persona.name.lower() in existing or base_display in existing
        if is_update:
            cli_args = [
                "agents", "draft-update",
                "--channel", args.channel,
                "--agent-name", persona.display_name.split()[0],
                "--system-prompt", "-",
            ]
            if args.runtime_for and persona.name in dict(p.split("=") for p in args.runtime_for.split(",")):
                cli_args += ["--runtime", dict(p.split("=") for p in args.runtime_for.split(","))[persona.name]]
        else:
            cli_args = [
                "agents", "draft-create",
                "--channel", args.channel,
                "--display-name", persona.display_name,
                "--system-prompt", "-",
            ]
        if args.dry_run:
            results.append({"agent": persona.name, "action": "update" if is_update else "create", "ok": None, "detail": "dry-run"})
            continue
        code, out, err = run_buzz(cli_args, env, stdin=prompt)
        results.append({
            "agent": persona.name,
            "action": "update" if is_update else "create",
            "ok": code == 0,
            "detail": (out or err)[:200],
        })

    ok = all(r["ok"] is not False for r in results)
    if args.json:
        print(json.dumps({"ok": ok, "channel": args.channel, "results": results}, indent=2))
    else:
        for r in results:
            flag = "OK " if r["ok"] else ("DRY" if r["ok"] is None else "NO ")
            print(f"[{flag}] {r['action']:6} {r['agent']}: {r['detail']}")
        print(f"{'PASS' if ok else 'FAIL'} — drafts land as review forms in Buzz Desktop; save each to finish.")
    return 0 if ok else 2


def _desktop_quit_and_relaunch(edit_fn) -> str:
    """Quit Buzz Desktop, run edit_fn() against the agent store, relaunch."""
    import shutil as _shutil
    import time

    subprocess.run(["osascript", "-e", 'quit app "Buzz"'], capture_output=True, check=False)
    for _ in range(30):
        if subprocess.run(["pgrep", "-q", "buzz-desktop"], check=False).returncode != 0:
            break
        time.sleep(1)
    backup = str(MANAGED_AGENTS) + ".bak-buzzctl"
    _shutil.copy2(MANAGED_AGENTS, backup)
    result = edit_fn()
    subprocess.run(["open", "-a", "Buzz"], capture_output=True, check=False)
    return f"{result} (backup: {backup})"


def _normalize_label(label: str) -> str | None:
    """Agent name minus decorative emoji tokens ("Beacon SEO 🔦" -> "Beacon SEO").

    Grouping MUST use the full name: distinct agents can share a first word
    ("Beacon Design" / "Beacon SEO"), and first-word grouping cross-compared
    one agent's store against the other's live process — a false drift page.
    """
    words = [w for w in label.split() if any(c.isascii() and c.isalnum() for c in w)]
    return " ".join(words) or (label.strip() or None)


def _record_label(r: dict) -> str | None:
    """Normalized agent name across record kinds.

    The unified store mixes key-less DEFINITION records (display_name set,
    empty pubkey) with INSTANCE records (pubkey set, name set, display_name
    None). Both kinds must match so callers can address either.
    """
    return _normalize_label(r.get("display_name") or r.get("name") or "")


def _fleet_view() -> dict[str, dict]:
    """Per-agent merged config view from the store, keyed by first-word name.

    Per agent keep the newest definition record AND the newest instance
    record. The instance (pubkey set) is what actually spawns — its
    respond_to feeds BUZZ_ACP_RESPOND_TO — while definition-linked config
    (env_vars, runtime defaults) lives on the definition.
    """
    recs = json.loads(MANAGED_AGENTS.read_text(encoding="utf-8"))
    defs: dict[str, dict] = {}
    insts: dict[str, dict] = {}
    for r in recs:
        if not isinstance(r, dict):
            continue
        first = _record_label(r)
        if not first:
            continue
        bucket = insts if r.get("pubkey") else defs
        if first not in bucket or str(r.get("updated_at") or "") > str(bucket[first].get("updated_at") or ""):
            bucket[first] = r
    view: dict[str, dict] = {}
    for first in set(defs) | set(insts):
        d, i = defs.get(first, {}), insts.get(first, {})
        env = {**(d.get("env_vars") or {}), **(i.get("env_vars") or {})}
        view[first] = {
            "runtime": i.get("runtime") or d.get("runtime"),
            "model": i.get("model") or d.get("model"),
            "respond_to": i.get("respond_to") if i else d.get("definition_respond_to"),
            "subscribe": env.get("BUZZ_ACP_SUBSCRIBE"),
            "kinds": env.get("BUZZ_ACP_KINDS"),
        }
    return view


def cmd_fleet_status(args: argparse.Namespace) -> int:
    if not MANAGED_AGENTS.is_file():
        print("no managed agents store found", file=sys.stderr)
        return 1
    seen = _fleet_view()
    if args.json:
        print(json.dumps(seen, indent=2))
    else:
        print(f"{'agent':14} {'runtime':8} {'model':22} {'respond':11} {'sub':4} kinds")
        for n, c in sorted(seen.items()):
            print(f"{n:14} {c.get('runtime') or '-':8} {c.get('model') or '-':22} "
                  f"{c.get('respond_to') or '-':11} {c.get('subscribe') or '-':4} {c.get('kinds') or '-'}")
    return 0


# Spawn-env keys doctor may extract from a live process. The raw `ps eww`
# line also carries BUZZ_PRIVATE_KEY — extraction is allowlisted to these
# keys and the raw line is never returned, stored, or printed.
_DOCTOR_ENV_KEYS = (
    "BUZZ_ACP_SESSION_TITLE",
    "BUZZ_ACP_RESPOND_TO",
    "BUZZ_ACP_MODEL",
    "BUZZ_ACP_SUBSCRIBE",
    "BUZZ_ACP_KINDS",
)


def _live_agent_envs() -> dict[str, dict[str, str]]:
    """Map agent first-word name -> allowlisted spawn env of its live buzz-acp process."""
    import re

    pids = subprocess.run(
        ["pgrep", "buzz-acp"], capture_output=True, text=True, check=False
    ).stdout.split()
    live: dict[str, dict[str, str]] = {}
    for pid in pids:
        line = subprocess.run(
            ["ps", "eww", "-o", "command=", "-p", pid],
            capture_output=True, text=True, check=False,
        ).stdout
        env: dict[str, str] = {}
        for key in _DOCTOR_ENV_KEYS:
            # Value runs until the next VAR= assignment (titles contain spaces).
            m = re.search(rf"{key}=(.*?)(?= [A-Z_][A-Z0-9_]*=|$)", line)
            if m:
                env[key] = m.group(1).strip()
        title = _normalize_label(env.pop("BUZZ_ACP_SESSION_TITLE", ""))
        if title:
            live[title] = env
    return live


def cmd_fleet_doctor(args: argparse.Namespace) -> int:
    """Cross-check store config against live process env — catches drift
    (e.g. an edit the desktop hasn't respawned agents for) automatically."""
    if not MANAGED_AGENTS.is_file():
        print("no managed agents store found", file=sys.stderr)
        return 1
    view = _fleet_view()
    live = _live_agent_envs()
    checks = {  # store field -> live env key
        "respond_to": "BUZZ_ACP_RESPOND_TO",
        "model": "BUZZ_ACP_MODEL",
        "subscribe": "BUZZ_ACP_SUBSCRIBE",
        "kinds": "BUZZ_ACP_KINDS",
    }
    rows = []
    for name in sorted(set(view) | set(live)):
        want, got = view.get(name), live.get(name)
        if got is None:
            rows.append({"agent": name, "state": "not-running", "drift": {}})
            continue
        if want is None:
            rows.append({"agent": name, "state": "unmanaged", "drift": {}})
            continue
        drift = {
            f: {"store": want[f], "live": got[k]}
            for f, k in checks.items()
            # Only compare when both sides carry a value: builtins have no
            # runtime/model in the store, stopped pool slots no env.
            if want.get(f) is not None and k in got and str(want[f]) != got[k]
        }
        rows.append({"agent": name, "state": "drift" if drift else "ok", "drift": drift})
    drifted = [r for r in rows if r["state"] == "drift"]
    ok = bool(live) and not drifted
    if args.json:
        print(json.dumps({"ok": ok, "agents": rows}, indent=2))
    else:
        for r in rows:
            flag = {"ok": "OK ", "drift": "NO ", "not-running": "-- ", "unmanaged": "?? "}[r["state"]]
            detail = "; ".join(
                f"{f}: store={d['store']} live={d['live']}" for f, d in r["drift"].items()
            )
            print(f"[{flag}] {r['agent']:14} {r['state']}" + (f" ({detail})" if detail else ""))
        if not live:
            print("RESULT: FAIL — no live buzz-acp processes (desktop not running?)")
        else:
            print("RESULT:", "PASS" if ok else f"FAIL — {len(drifted)} agent(s) drifted; run fleet set (or restart Buzz) to re-spawn")
    return 0 if ok else 2


def _find_ghosts(recs: list) -> list[dict]:
    """Instance records whose persona_id no longer matches any definition.

    Archiving a persona deletes its definition record but leaves the keyed
    instance stub behind — the stub keeps spawning (or erroring) with config
    that can never be edited again. persona_id=None instances are standalone
    agents (their own definition) and are never ghosts. Age is NOT a signal:
    a live store showed the ghost with a NEWER updated_at than its sibling.
    """
    slugs = {r.get("slug") for r in recs if isinstance(r, dict) and not r.get("pubkey")}
    return [
        r for r in recs
        if isinstance(r, dict) and r.get("pubkey") and r.get("persona_id")
        and r["persona_id"] not in slugs
    ]


def cmd_fleet_cleanup(args: argparse.Namespace) -> int:
    if not MANAGED_AGENTS.is_file():
        print("no managed agents store found", file=sys.stderr)
        return 1
    recs = json.loads(MANAGED_AGENTS.read_text(encoding="utf-8"))
    ghosts = _find_ghosts(recs)
    rows = [
        {"agent": _record_label(g) or "?", "pubkey": g["pubkey"], "persona_id": g["persona_id"]}
        for g in ghosts
    ]
    if args.json:
        print(json.dumps({"ghosts": rows, "applied": bool(args.apply and rows)}, indent=2))
    else:
        for r in rows:
            print(f"ghost {r['agent']:12} pubkey={r['pubkey'][:12]} persona_id={r['persona_id']} (definition gone)")
    if not ghosts:
        if not args.json:
            print("no ghost records")
        return 0
    if not args.apply:
        if not args.json:
            print(f"{len(ghosts)} ghost(s); rerun with --apply to remove (quits+relaunches desktop, with backup)")
        return 0

    doomed = {g["pubkey"] for g in ghosts}

    def edit() -> str:
        fresh = json.loads(MANAGED_AGENTS.read_text(encoding="utf-8"))
        kept = [r for r in fresh if not (isinstance(r, dict) and r.get("pubkey") in doomed)]
        MANAGED_AGENTS.write_text(json.dumps(kept, indent=2), encoding="utf-8")
        return f"removed {len(fresh) - len(kept)} ghost record(s)"

    print(_desktop_quit_and_relaunch(edit))
    return 0


# Mirror of the desktop's RESERVED_ENV_KEYS (env_vars.rs), matched
# case-insensitively like the desktop. Spawn silently strips these from
# env_vars, so writing one via --env is a guaranteed no-op that costs two
# desktop bounces to diagnose (found the hard way wiring MCP servers).
_RESERVED_ENV_KEYS = frozenset(k.lower() for k in (
    "BUZZ_PRIVATE_KEY", "NOSTR_PRIVATE_KEY", "BUZZ_AUTH_TAG", "BUZZ_API_TOKEN",
    "BUZZ_ACP_PRIVATE_KEY", "BUZZ_ACP_API_TOKEN", "BUZZ_RELAY_URL",
    "BUZZ_ACP_AGENT_COMMAND", "BUZZ_ACP_AGENT_ARGS", "BUZZ_ACP_MCP_COMMAND",
    "BUZZ_ACP_RESPOND_TO", "BUZZ_ACP_RESPOND_TO_ALLOWLIST", "BUZZ_ACP_AGENT_OWNER",
    "BUZZ_ACP_SETUP_PAYLOAD", "BUZZ_MANAGED_AGENT", "BUZZ_MANAGED_AGENT_START_NONCE",
))
_RESERVED_ENV_HINTS = {
    "buzz_acp_respond_to": "use --respond instead",
    "buzz_acp_respond_to_allowlist": "set via the desktop edit form",
    "buzz_acp_mcp_command": "MCP servers are wired per harness, not per agent record "
                            "(claude mcp add / codex config.toml [mcp_servers.*] / grok mcp add)",
}


def cmd_fleet_set(args: argparse.Namespace) -> int:
    targets = None if args.all else {s.strip().lower() for s in (args.agents or "").split(",") if s.strip()}
    if targets is not None and not targets:
        print("pass --agents a,b or --all", file=sys.stderr)
        return 1
    env_pairs = dict(p.split("=", 1) for p in (args.env or []))
    reserved = [k for k in env_pairs if k.lower() in _RESERVED_ENV_KEYS]
    if reserved:
        for k in reserved:
            hint = _RESERVED_ENV_HINTS.get(k.lower(), "")
            print(f"refusing --env {k}: reserved key, the desktop strips it at spawn"
                  + (f" — {hint}" if hint else ""), file=sys.stderr)
        return 1
    if not any([args.model, args.runtime, args.respond, env_pairs, args.avatar]):
        print("nothing to set (use --model/--runtime/--respond/--env/--avatar)", file=sys.stderr)
        return 1
    avatar_uri = None
    if args.avatar:
        import base64
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            subprocess.run(["sips", "-Z", "384", args.avatar, "--out", tmp.name],
                           capture_output=True, check=True)
            avatar_uri = "data:image/png;base64," + base64.b64encode(Path(tmp.name).read_bytes()).decode()

    def apply(recs: list) -> list[dict]:
        """Mutate recs in place; return the real changes (old != new)."""
        changes: list[dict] = []

        def setval(r: dict, agent: str, kind: str, field: str, new) -> None:
            old = r.get(field)
            if old != new:
                r[field] = new
                changes.append({"agent": agent, "record": kind, "field": field, "old": old, "new": new})

        for r in recs:
            if not isinstance(r, dict):
                continue
            label = _record_label(r)
            if not label:
                continue
            first = label.lower()
            # A target matches the full name ("beacon seo") or, for
            # convenience, the first word ("atlas"; "beacon" hits both Beacons).
            if targets is not None and first not in targets and first.split()[0] not in targets:
                continue
            if r.get("pubkey"):
                # INSTANCE record: respond_to here is what the desktop spawns
                # as BUZZ_ACP_RESPOND_TO, and its boot reconcile signs + syncs
                # the edited value (kind:30177) so it survives restarts. The
                # old code only edited definition records — the desktop reset
                # their cosmetic respond_to to owner-only on every persona
                # save, which looked like a revert.
                if args.respond:
                    setval(r, first, "instance", "respond_to", args.respond)
                continue
            # DEFINITION record (no key): definition_respond_to seeds future
            # instances; model/runtime/env/avatar edits here are the proven
            # persistent path for definition-linked agents.
            if args.model:
                setval(r, first, "definition", "model", args.model)
            if args.runtime:
                setval(r, first, "definition", "runtime", args.runtime)
            if args.respond:
                setval(r, first, "definition", "definition_respond_to", args.respond)
            for k, v in env_pairs.items():
                env = r.setdefault("env_vars", {})
                if env.get(k) != v:
                    changes.append({"agent": first, "record": "definition", "field": f"env_vars.{k}", "old": env.get(k), "new": v})
                    env[k] = v
            if avatar_uri:
                setval(r, first, "definition", "avatar_url", avatar_uri)
        return changes

    def show(c: dict) -> str:
        def clip(v) -> str:
            s = str(v)
            return s[:40] + "…" if len(s) > 40 else s

        return f"{c['agent']:12} {c['record']}.{c['field']}: {clip(c['old'])} -> {clip(c['new'])}"

    # Pre-check against the current store: a no-op set (or a dry run) must
    # not bounce the desktop.
    planned = apply(json.loads(MANAGED_AGENTS.read_text(encoding="utf-8")))
    if args.dry_run or not planned:
        for c in planned:
            print(f"[DRY] {show(c)}")
        print(f"{len(planned)} change(s)" + ("" if planned else " — nothing to do") + ("" if args.dry_run else "; store already up to date, desktop untouched"))
        return 0

    def edit() -> str:
        # Re-read and re-apply after the desktop quits: it may rewrite the
        # store on shutdown, so the pre-check copy above is stale by now.
        recs = json.loads(MANAGED_AGENTS.read_text(encoding="utf-8"))
        changes = apply(recs)
        MANAGED_AGENTS.write_text(json.dumps(recs, indent=2), encoding="utf-8")
        for c in changes:
            print(show(c))
        return f"updated {sorted({c['agent'] for c in changes})}"

    print(_desktop_quit_and_relaunch(edit))
    return 0


def cmd_mem_export(args: argparse.Namespace) -> int:
    env = load_env(args_env_file(args))
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    code, raw, err = run_buzz(["mem", "ls"], env)
    if code != 0:
        print(err or raw, file=sys.stderr)
        return 2
    slugs = [line.split()[0] for line in raw.splitlines() if line.strip()]
    for slug in slugs:
        c, val, e = run_buzz(["mem", "get", slug], env)
        if c == 0:
            (out / f"{slug}.mem").write_text(val, encoding="utf-8")
            print(f"exported {slug} ({len(val)} bytes)")
        else:
            print(f"skip {slug}: {e[:80]}", file=sys.stderr)
    print(f"{len(slugs)} engram(s) -> {out}")
    return 0


def cmd_mem_import(args: argparse.Namespace) -> int:
    env = load_env(args_env_file(args))
    src = Path(args.dir).expanduser()
    files = sorted(src.glob("*.mem"))
    if not files:
        print(f"no .mem files in {src}", file=sys.stderr)
        return 1
    for f in files:
        slug = f.stem
        c, o, e = run_buzz(["mem", "set", slug, "-"], env, stdin=f.read_text(encoding="utf-8"))
        print(f"{'OK ' if c == 0 else 'NO '} {slug}" + ("" if c == 0 else f" {e[:80]}"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="buzzctl", description="Agent-native Buzz CLI (CLI-Anything style)")
    p.add_argument("--env-file", default=None, help=f"Credentials env file (default: {DEFAULT_ENV_FILE})")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="Check creds, relay, and buzz binary")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_doctor)

    c = sub.add_parser("channels", help="List channels visible to the acting identity")
    c.set_defaults(func=cmd_channels)

    t = sub.add_parser("draft-team", help="Push a hivepack pack as owner-reviewed agent drafts")
    t.add_argument("pack", help="Pack name or path")
    t.add_argument("--channel", required=True, help="Channel UUID the agents join after save")
    t.add_argument("--only", default=None, help="Comma-separated persona names to include")
    t.add_argument("--runtime-for", default=None, help="Per-agent runtime overrides, e.g. swain=grok")
    t.add_argument("--dry-run", action="store_true")
    t.add_argument("--json", action="store_true")
    t.set_defaults(func=cmd_draft_team)

    fs = sub.add_parser("fleet", help="Manage the whole agent fleet's settings")
    fsub = fs.add_subparsers(dest="fleet_cmd", required=True)
    st = fsub.add_parser("status", help="Table of every agent: runtime, model, respond-to, env")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=cmd_fleet_status)
    fd = fsub.add_parser("doctor", help="Cross-check store config vs live process env (drift detector)")
    fd.add_argument("--json", action="store_true")
    fd.set_defaults(func=cmd_fleet_doctor)
    fc = fsub.add_parser("cleanup", help="List ghost records (orphaned instance stubs); --apply removes them")
    fc.add_argument("--apply", action="store_true", help="Remove ghosts (quits and relaunches Buzz Desktop, with backup)")
    fc.add_argument("--json", action="store_true")
    fc.set_defaults(func=cmd_fleet_cleanup)
    se = fsub.add_parser("set", help="Bulk-set settings (quits and relaunches Buzz Desktop, with backup)")
    se.add_argument("--agents", default=None, help="Comma-separated agent names (first word, case-insensitive)")
    se.add_argument("--all", action="store_true", help="Apply to every agent")
    se.add_argument("--model", default=None)
    se.add_argument("--runtime", default=None, help="claude | codex | grok | hermes | goose")
    se.add_argument("--respond", default=None, choices=["anyone", "owner-only", "allowlist"])
    se.add_argument("--env", action="append", default=None, metavar="KEY=VALUE")
    se.add_argument("--avatar", default=None, help="Image file; resized to 384px and embedded")
    se.add_argument("--dry-run", action="store_true", help="Report what would change; no write, no desktop bounce")
    se.set_defaults(func=cmd_fleet_set)

    me = sub.add_parser("mem-export", help="Export the acting agent's engrams to files")
    me.add_argument("--out", required=True, help="Directory for <slug>.mem files")
    me.set_defaults(func=cmd_mem_export)
    mi = sub.add_parser("mem-import", help="Import <slug>.mem files as the acting agent's engrams")
    mi.add_argument("--dir", required=True)
    mi.set_defaults(func=cmd_mem_import)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
