"""Install / checklist flow for packs."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .snapshot import export_pack_snapshots
from .validate import validate_pack


@dataclass
class AddResult:
    pack_dir: Path
    snapshots: list[Path]
    checklist: list[str]
    buzz_validate: str | None


def _try_buzz_pack_validate(pack_dir: Path) -> str | None:
    from .doctor import which

    buzz = which("buzz")
    if not buzz:
        return None
    try:
        proc = subprocess.run(
            [buzz, "pack", "validate", str(pack_dir)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        return f"exit={proc.returncode}\n{out}\n{err}".strip()
    except Exception as exc:  # noqa: BLE001
        return f"buzz pack validate failed to run: {exc}"


def add_pack(pack_dir: Path, *, export_dir: Path | None = None) -> AddResult:
    pack_dir = pack_dir.resolve()
    report = validate_pack(pack_dir)
    if not report.ok:
        msgs = "; ".join(f"{d.code}: {d.message}" for d in report.errors)
        raise SystemExit(f"validate failed: {msgs}")

    snapshots = export_pack_snapshots(pack_dir, export_dir)

    checklist = [
        "THINK/VERIFY: Confirm target Buzz community (hosted buzz.xyz vs self-host relay).",
        "Open Buzz Desktop (or buzz.xyz) and sign in to the community.",
        "Create a channel e.g. #ship (topic: HivePack Ship Squad).",
        "For each snapshot below: Agents → Import → drop the .agent.json → confirm Import.",
        "Leave the harness at your DEFAULT user harness on import — you can change it per-agent later.",
        "For each imported agent: Agents → Environment → add BUZZ_ACP_SUBSCRIBE=all and BUZZ_ACP_KINDS=9 "
        "(see the pack's acp.env; snapshots cannot carry env vars by format design).",
        "Invite the four agents into #ship.",
        "Post the demo prompt from DEMO.md and verify roll-call behavior.",
        "THINK/VERIFY: No agent should have production secrets; scope to a test repo first.",
        "Optional: install buzz-hooks CI/approval gates for implementer/reviewer sessions.",
        "Optional: `buzz pack validate` on this pack directory if buzz CLI is available.",
    ]

    for snap in snapshots:
        checklist.append(f"Import file: {snap}")

    buzz_out = _try_buzz_pack_validate(pack_dir)
    return AddResult(pack_dir=pack_dir, snapshots=snapshots, checklist=checklist, buzz_validate=buzz_out)


def print_add_result(result: AddResult) -> None:
    print("HivePack add")
    print("=" * 60)
    print(f"pack: {result.pack_dir}")
    print(f"snapshots ({len(result.snapshots)}):")
    for s in result.snapshots:
        print(f"  - {s}")
    print()
    print("Checklist (do these in order):")
    for i, step in enumerate(result.checklist, 1):
        print(f"  {i}. {step}")
    if result.buzz_validate is not None:
        print()
        print("buzz pack validate:")
        print(result.buzz_validate)
    print()
    print("THINK/VERIFY gate: stop if any import preview shows memory entries or secrets.")
