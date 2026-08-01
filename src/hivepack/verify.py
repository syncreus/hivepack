"""Adversarial verification runner — thinking loop at every gate."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .add import add_pack
from .constants import DEFAULT_PACK, PACKS_DIR
from .doctor import doctor, which
from .validate import validate_pack


@dataclass
class Gate:
    name: str
    passed: bool
    detail: str
    think: str


@dataclass
class VerifyReport:
    gates: list[Gate] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str, think: str) -> None:
        self.gates.append(Gate(name, passed, detail, think))

    @property
    def ok(self) -> bool:
        return all(g.passed for g in self.gates)


def verify(pack_name: str = DEFAULT_PACK) -> VerifyReport:
    report = VerifyReport()
    pack_dir = PACKS_DIR / pack_name

    # Gate 1: doctor
    d = doctor(pack_dir)
    report.add(
        "doctor",
        d.ok,
        json.dumps(d.as_dict(), indent=2)[:500],
        "THINK: Without Python + pack on disk, nothing else matters. Soft deps may be missing.",
    )

    # Gate 2: hivepack validate
    v = validate_pack(pack_dir)
    err_n = len(v.errors)
    warn_n = len(v.warnings)
    report.add(
        "hivepack_validate",
        v.ok,
        f"errors={err_n} warnings={warn_n} personas={v.persona_names}",
        "THINK: Would Beekeep reject this? Secrets? Missing skills? Weak role boundaries?",
    )

    # Gate 3: export snapshots + re-validate
    try:
        result = add_pack(pack_dir)
        snap_ok = len(result.snapshots) >= 3
        # ensure memory none
        mem_ok = True
        for s in result.snapshots:
            data = json.loads(s.read_text(encoding="utf-8"))
            if data.get("memory", {}).get("level") != "none":
                mem_ok = False
            if data.get("memory", {}).get("entries"):
                mem_ok = False
        report.add(
            "export_snapshots",
            snap_ok and mem_ok,
            f"count={len(result.snapshots)} memory_none={mem_ok}",
            "THINK: Shared snapshots must be config-only. Any memory entries = fail.",
        )
    except SystemExit as exc:
        report.add("export_snapshots", False, str(exc), "THINK: export must not run on invalid packs")

    # Gate 4: official buzz pack validate if present
    buzz = which("buzz")
    if not buzz:
        report.add(
            "buzz_pack_validate",
            True,
            "skipped — buzz CLI not on PATH",
            "THINK: Skipping is OK offline; when buzz exists this gate is mandatory.",
        )
    else:
        proc = subprocess.run(
            [buzz, "pack", "validate", str(pack_dir)],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        # Accept Valid / Valid (with warnings)
        passed = proc.returncode == 0 and "valid" in out.lower()
        # Some builds may print differently — also accept exit 0 alone
        if proc.returncode == 0 and not passed:
            passed = True
        report.add(
            "buzz_pack_validate",
            passed,
            f"exit={proc.returncode} {out[:400]}",
            "THINK: Official validator is source of truth for Persona Pack layout.",
        )

        proc2 = subprocess.run(
            [buzz, "pack", "inspect", str(pack_dir)],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        out2 = (proc2.stdout or "") + (proc2.stderr or "")
        names_ok = all(n in out2 for n in ("lead", "implementer", "reviewer", "mem"))
        report.add(
            "buzz_pack_inspect",
            proc2.returncode == 0 and names_ok,
            out2[:400],
            "THINK: Inspect must show all four personas resolved.",
        )

    # Gate 5: unit tests
    tests = Path(__file__).resolve().parents[2] / "tests"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(tests), "-q"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    report.add(
        "pytest",
        proc.returncode == 0,
        ((proc.stdout or "") + (proc.stderr or ""))[-500:],
        "THINK: Regressions in parse/validate/snapshot break distribution.",
    )

    return report


def print_verify(report: VerifyReport) -> None:
    print("HivePack verify — thinking loop at every gate")
    print("=" * 60)
    for g in report.gates:
        flag = "PASS" if g.passed else "FAIL"
        print(f"[{flag}] {g.name}")
        print(f"  detail: {g.detail}")
        print(f"  think:  {g.think}")
        print()
    print("=" * 60)
    print("OVERALL:", "PASS" if report.ok else "FAIL")
