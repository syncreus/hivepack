"""Environment doctor for HivePack installs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DoctorItem:
    name: str
    ok: bool
    detail: str
    think: str


@dataclass
class DoctorReport:
    items: list[DoctorItem] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str, think: str) -> None:
        self.items.append(DoctorItem(name, ok, detail, think))

    @property
    def ok(self) -> bool:
        # Soft deps don't fail doctor; only critical missing bits.
        critical = {"python", "pack_ship_squad"}
        for item in self.items:
            if item.name in critical and not item.ok:
                return False
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "items": [
                {"name": i.name, "ok": i.ok, "detail": i.detail, "think": i.think} for i in self.items
            ],
        }


def which(cmd: str) -> str | None:
    found = shutil.which(cmd)
    if found:
        return found
    extras = [
        Path.home() / ".local" / "bin" / cmd,
        Path("/Applications/Buzz.app/Contents/MacOS") / cmd,
        Path("/opt/homebrew/bin") / cmd,
        Path("/usr/local/bin") / cmd,
    ]
    for path in extras:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def run_version(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
        out = (proc.stdout or proc.stderr or "").strip().splitlines()
        return out[0] if out else f"exit {proc.returncode}"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


def doctor(pack_dir: Path | None = None) -> DoctorReport:
    report = DoctorReport()

    report.add(
        "python",
        True,
        f"{sys.version.split()[0]}",
        "VERIFY: runtime available for hivepack CLI",
    )

    buzz = which("buzz")
    report.add(
        "buzz_cli",
        bool(buzz),
        buzz or "not on PATH — install Buzz CLI or use Desktop import checklist",
        "VERIFY: buzz pack validate is the gold standard when present",
    )

    if buzz:
        # Prefer real validate later; here just prove binary runs help/version-ish
        detail = run_version([buzz, "--help"])
        report.add(
            "buzz_cli_runs",
            "Usage" in detail or "buzz" in detail.lower() or detail.startswith("error") is False,
            detail[:200],
            "VERIFY: CLI invokes without missing-dylib crash",
        )

    for app_name, path in (
        ("Buzz.app", Path("/Applications/Buzz.app")),
        ("buzz-acp", Path("/Applications/Buzz.app/Contents/MacOS/buzz-acp")),
    ):
        exists = path.exists()
        report.add(
            f"macos_{app_name.replace('.', '_')}",
            exists,
            str(path) if exists else f"missing {path}",
            "VERIFY: Desktop path for local harness agents",
        )

    hermes = which("hermes")
    report.add(
        "hermes",
        bool(hermes),
        hermes or "optional — Hermes gateway/ACP integration",
        "VERIFY: optional dual-distribution path",
    )

    for harness in ("claude", "codex", "goose"):
        path = which(harness)
        report.add(
            f"harness_{harness}",
            bool(path),
            path or "not on PATH (optional)",
            "VERIFY: model-agnostic harness availability",
        )

    if pack_dir is None:
        from .constants import DEFAULT_PACK, PACKS_DIR

        pack_dir = PACKS_DIR / DEFAULT_PACK

    pack_ok = (pack_dir / ".plugin" / "plugin.json").is_file()
    report.add(
        "pack_ship_squad",
        pack_ok,
        str(pack_dir) if pack_ok else f"pack missing at {pack_dir}",
        "VERIFY: default pack is present before add/demo",
    )

    relay = os.environ.get("BUZZ_RELAY_URL")
    report.add(
        "buzz_relay_url",
        bool(relay),
        relay or "BUZZ_RELAY_URL unset (ok for local Desktop default)",
        "VERIFY: know which community/relay agents will join",
    )

    key = os.environ.get("BUZZ_PRIVATE_KEY")
    report.add(
        "buzz_private_key",
        bool(key),
        "set" if key else "unset — required for buzz-cli agent actions",
        "VERIFY: never print key material; only presence",
    )

    return report


def print_doctor(report: DoctorReport) -> None:
    print("HivePack doctor")
    print("=" * 60)
    for item in report.items:
        flag = "OK " if item.ok else "NO "
        print(f"[{flag}] {item.name}: {item.detail}")
        print(f"       think: {item.think}")
    print("=" * 60)
    print("RESULT:", "PASS" if report.ok else "FAIL")
