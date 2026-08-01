"""hivepack CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .add import add_pack, print_add_result
from .constants import DEFAULT_PACK, PACKS_DIR
from .convert import convert_agent, list_claude_agents
from .doctor import doctor, print_doctor
from .snapshot import export_pack_snapshots
from .validate import validate_pack
from .verify import print_verify, verify


def _pack_path(name_or_path: str) -> Path:
    p = Path(name_or_path)
    if p.exists():
        return p.resolve()
    candidate = PACKS_DIR / name_or_path
    if candidate.exists():
        return candidate.resolve()
    raise SystemExit(f"pack not found: {name_or_path} (looked at {candidate})")


def cmd_validate(args: argparse.Namespace) -> int:
    pack = _pack_path(args.pack)
    report = validate_pack(pack)
    for d in report.diagnostics:
        prefix = {
            "error": "ERROR",
            "warning": "WARN ",
            "info": "INFO ",
            "think": "THINK",
        }[d.level]
        loc = f" ({d.path})" if d.path else ""
        print(f"{prefix} [{d.code}]{loc} {d.message}")
    print()
    if report.ok:
        print(f"Valid. personas={report.persona_names}")
        return 0
    print(f"Invalid. {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    return 1


def cmd_doctor(args: argparse.Namespace) -> int:
    pack = _pack_path(args.pack) if args.pack else None
    report = doctor(pack)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print_doctor(report)
    return 0 if report.ok else 1


def cmd_export_snapshots(args: argparse.Namespace) -> int:
    pack = _pack_path(args.pack)
    report = validate_pack(pack)
    if not report.ok:
        print("Refusing to export: pack invalid", file=sys.stderr)
        return 1
    paths = export_pack_snapshots(pack, Path(args.out) if args.out else None)
    for p in paths:
        print(p)
    print(f"THINK/VERIFY: exported {len(paths)} snapshots with memory.level=none")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    pack = _pack_path(args.pack)
    result = add_pack(pack)
    print_add_result(result)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    report = verify(args.pack)
    print_verify(report)
    return 0 if report.ok else 1


def cmd_list_packs(_: argparse.Namespace) -> int:
    if not PACKS_DIR.is_dir():
        print("no packs dir")
        return 1
    for p in sorted(PACKS_DIR.iterdir()):
        if (p / ".plugin" / "plugin.json").is_file():
            print(p.name)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    pack = _pack_path(args.pack)
    demo = pack.parents[1] / "DEMO.md"
    if not demo.is_file():
        demo = Path(__file__).resolve().parents[2] / "DEMO.md"
    print(demo.read_text(encoding="utf-8") if demo.is_file() else "DEMO.md missing")
    print()
    print("THINK/VERIFY before recording:")
    print("  1) doctor PASS")
    print("  2) validate PASS")
    print("  3) four agents imported into one channel")
    print("  4) no secrets in the workspace")
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    if args.list:
        for p in list_claude_agents():
            print(p.stem, f"({p})")
        return 0
    if not args.agent:
        print("agent name or path required (or use --list)", file=sys.stderr)
        return 1
    skills = [s.strip() for s in (args.skills or "").split(",") if s.strip()]
    kwargs = {}
    if args.skills_root:
        kwargs["skills_root"] = Path(args.skills_root).expanduser().resolve()
    result = convert_agent(args.agent, args.pack, skills, **kwargs)
    print(f"persona: {result.persona_path}")
    for s in result.skills_copied:
        trimmed = " (SKILL.md only — source too large)" if s in result.skills_trimmed else ""
        print(f"skill bundled: {s}{trimmed}")
    for note in result.notes:
        print(f"NOTE: {note}")

    report = validate_pack(result.pack_dir)
    if not report.ok:
        for d in report.errors:
            print(f"ERROR [{d.code}] {d.message}", file=sys.stderr)
        print("Converted but pack is INVALID — fix before add.", file=sys.stderr)
        return 1
    snaps = export_pack_snapshots(result.pack_dir)
    print(f"Valid. snapshots={len(snaps)} → next: hivepack add {args.pack}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hivepack",
        description="Opinionated agent-team packs for Buzz (Persona Pack + Beekeep snapshots)",
    )
    p.add_argument("--version", action="version", version=f"hivepack {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="Validate a pack (with thinking-loop diagnostics)")
    v.add_argument("pack", nargs="?", default=DEFAULT_PACK)
    v.set_defaults(func=cmd_validate)

    d = sub.add_parser("doctor", help="Check local Buzz/harness environment")
    d.add_argument("pack", nargs="?", default=None)
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_doctor)

    e = sub.add_parser("export-snapshots", help="Write .agent.json snapshots (memory none)")
    e.add_argument("pack", nargs="?", default=DEFAULT_PACK)
    e.add_argument("--out", default=None, help="Output directory (default: pack/snapshots)")
    e.set_defaults(func=cmd_export_snapshots)

    a = sub.add_parser("add", help="Validate, export snapshots, print import checklist")
    a.add_argument("pack", nargs="?", default=DEFAULT_PACK)
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("verify", help="Full adversarial verification gates")
    r.add_argument("pack", nargs="?", default=DEFAULT_PACK)
    r.set_defaults(func=cmd_verify)

    lp = sub.add_parser("list", help="List built-in packs")
    lp.set_defaults(func=cmd_list_packs)

    c = sub.add_parser("convert", help="Convert a local Claude Code agent into a Buzz persona")
    c.add_argument("agent", nargs="?", default=None, help="Agent name (in .claude/agents) or path to .md")
    c.add_argument("--pack", default="my-squad", help="Target pack name (created if missing)")
    c.add_argument("--skills", default=None, help="Comma-separated skill names to bundle from ~/.claude/skills")
    c.add_argument("--skills-root", default=None, help="Primary skills directory (falls back to ~/.claude/skills per skill)")
    c.add_argument("--list", action="store_true", help="List discoverable Claude agents")
    c.set_defaults(func=cmd_convert)

    dm = sub.add_parser("demo", help="Print demo script + preflight thinks")
    dm.add_argument("pack", nargs="?", default=DEFAULT_PACK)
    dm.set_defaults(func=cmd_demo)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
