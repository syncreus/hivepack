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
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
