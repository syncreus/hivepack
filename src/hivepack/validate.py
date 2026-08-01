"""Validate HivePack / Buzz persona packs with structured diagnostics."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .persona import parse_persona_md

DiagLevel = Literal["error", "warning", "info", "think"]


@dataclass
class Diagnostic:
    level: DiagLevel
    code: str
    message: str
    path: str | None = None


@dataclass
class ValidationReport:
    pack_dir: Path
    diagnostics: list[Diagnostic] = field(default_factory=list)
    plugin: dict[str, Any] | None = None
    persona_names: list[str] = field(default_factory=list)

    def add(self, level: DiagLevel, code: str, message: str, path: str | None = None) -> None:
        self.diagnostics.append(Diagnostic(level, code, message, path))

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.level == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.level == "warning"]

    @property
    def thinks(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.level == "think"]

    @property
    def ok(self) -> bool:
        return not self.errors


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SECRETISH_RE = re.compile(
    r"(?i)(api[_-]?key\s*[:=]|secret\s*[:=]|password\s*[:=]|BEGIN (RSA |OPENSSH )?PRIVATE KEY|nsec1[a-z0-9]{20,})"
)


def _thinking_loop(report: ValidationReport, step: str, checks: list[str]) -> None:
    """Record an explicit verification thinking loop for humans/CI logs."""
    bullets = "; ".join(checks)
    report.add(
        "think",
        "VERIFY_LOOP",
        f"[{step}] adversarial checks → {bullets}",
    )


def validate_pack(pack_dir: Path) -> ValidationReport:
    pack_dir = pack_dir.resolve()
    report = ValidationReport(pack_dir=pack_dir)

    _thinking_loop(
        report,
        "layout",
        [
            "plugin.json present and JSON",
            "personas[] paths resolve",
            "no nested agents/",
            "skills referenced exist with SKILL.md",
        ],
    )

    if not pack_dir.is_dir():
        report.add("error", "PACK_NOT_DIR", f"not a directory: {pack_dir}")
        return report

    plugin_path = pack_dir / ".plugin" / "plugin.json"
    if not plugin_path.is_file():
        report.add("error", "PLUGIN_MISSING", "missing .plugin/plugin.json", str(plugin_path))
        return report

    try:
        plugin = json.loads(plugin_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.add("error", "PLUGIN_JSON", f"invalid JSON: {exc}", str(plugin_path))
        return report

    report.plugin = plugin
    for key in ("id", "name", "version", "description", "personas"):
        if key not in plugin:
            report.add("error", "PLUGIN_FIELD", f"plugin.json missing required field: {key}", str(plugin_path))

    personas = plugin.get("personas") or []
    if not isinstance(personas, list) or not personas:
        report.add("error", "PERSONAS_EMPTY", "plugin.json personas must be a non-empty list", str(plugin_path))
        return report

    _thinking_loop(
        report,
        "personas",
        [
            "required identity fields",
            "unique names",
            "non-empty system prompts",
            "no secret-looking material",
            "role separation still coherent for multi-agent packs",
        ],
    )

    seen: set[str] = set()
    bodies: dict[str, str] = {}
    for rel in personas:
        rel_s = str(rel)
        ppath = (pack_dir / rel_s).resolve()
        if not str(ppath).startswith(str(pack_dir)):
            report.add("error", "PATH_ESCAPE", f"persona path escapes pack: {rel_s}", rel_s)
            continue
        if not ppath.is_file():
            report.add("error", "PERSONA_MISSING", f"persona file missing: {rel_s}", rel_s)
            continue
        try:
            persona = parse_persona_md(ppath)
        except Exception as exc:  # noqa: BLE001 - surface parse errors as diagnostics
            report.add("error", "PERSONA_PARSE", str(exc), rel_s)
            continue

        if not NAME_RE.match(persona.name):
            report.add(
                "error",
                "PERSONA_NAME",
                f"invalid name '{persona.name}' (use lowercase slug)",
                rel_s,
            )
        if persona.name in seen:
            report.add("error", "PERSONA_DUP", f"duplicate persona name: {persona.name}", rel_s)
        seen.add(persona.name)
        report.persona_names.append(persona.name)
        bodies[persona.name] = persona.system_prompt.lower()

        if len(persona.system_prompt) < 80:
            report.add("warning", "PROMPT_SHORT", f"{persona.name}: system prompt is very short", rel_s)

        if SECRETISH_RE.search(persona.system_prompt) or SECRETISH_RE.search(json.dumps(persona.raw_frontmatter)):
            report.add("error", "SECRET_LEAK", f"{persona.name}: possible secret material in persona", rel_s)

        for skill_rel in persona.skills:
            skill_path = (pack_dir / skill_rel).resolve()
            skill_md = skill_path / "SKILL.md" if skill_path.is_dir() else skill_path
            if skill_path.is_dir():
                if not (skill_path / "SKILL.md").is_file():
                    report.add("error", "SKILL_MISSING", f"missing SKILL.md for {skill_rel}", rel_s)
                else:
                    _validate_skill_md(report, skill_path / "SKILL.md")
            elif not skill_md.is_file():
                report.add("error", "SKILL_MISSING", f"skill path not found: {skill_rel}", rel_s)

    # Pack-level files
    if plugin.get("pack_instructions"):
        ip = pack_dir / str(plugin["pack_instructions"])
        if not ip.is_file():
            report.add("error", "INSTRUCTIONS_MISSING", f"pack_instructions missing: {plugin['pack_instructions']}")

    if plugin.get("hooks_config"):
        hp = pack_dir / str(plugin["hooks_config"])
        if not hp.is_file():
            report.add("error", "HOOKS_MISSING", f"hooks_config missing: {plugin['hooks_config']}")
        else:
            try:
                json.loads(hp.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                report.add("error", "HOOKS_JSON", f"hooks JSON invalid: {exc}", str(hp))

    _thinking_loop(
        report,
        "team-coherence",
        [
            "multi-agent packs should not all claim the same exclusive duty",
            "memory agent should not also claim to implement code",
        ],
    )

    if {"lead", "implementer", "reviewer"}.issubset(set(report.persona_names)):
        impl = bodies.get("implementer", "")
        rev = bodies.get("reviewer", "")
        mem = bodies.get("mem", "")
        if "do not implement" not in rev and "do not write" not in rev:
            report.add(
                "warning",
                "REVIEWER_BOUNDARY",
                "reviewer prompt may lack a clear non-implementation boundary",
            )
        if mem and ("write code" in mem or "open a pr" in mem):
            report.add("warning", "MEM_SCOPE", "mem persona may be drifting into coding duties")
        if "do not write large code" not in bodies.get("lead", "") and "do not write large" not in bodies.get("lead", ""):
            # soft check — lead.persona uses "Do not write large code"
            if "bulk code" not in bodies.get("lead", "") and "do not write large code" not in bodies.get("lead", ""):
                report.add("warning", "LEAD_BOUNDARY", "lead persona may lack non-coding boundary")

    _thinking_loop(
        report,
        "distribution-safety",
        [
            "Beekeep wants memory none",
            "no machine-local commands in shared artifacts",
        ],
    )

    # snapshots if present
    snap_dir = pack_dir / "snapshots"
    if snap_dir.is_dir():
        for snap in sorted(snap_dir.glob("*.agent.json")):
            _validate_snapshot_file(report, snap)

    return report


def _validate_skill_md(report: ValidationReport, path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        report.add("error", "SKILL_FM", "SKILL.md must start with YAML frontmatter", str(path))
        return
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        report.add("error", "SKILL_FM", "SKILL.md frontmatter malformed", str(path))
        return
    try:
        meta = yaml_safe(match.group(1))
    except Exception:  # noqa: BLE001
        # Official `buzz pack validate` tolerates loose YAML (e.g. unquoted
        # colons in descriptions). Match it: fall back to line-level extraction.
        fm = match.group(1)
        meta = {
            key: True
            for key in ("name", "description")
            if re.search(rf"^{key}\s*:\s*\S", fm, re.MULTILINE)
        }
    if not meta.get("name") or not meta.get("description"):
        report.add("error", "SKILL_FIELDS", "SKILL.md requires name and description", str(path))


def yaml_safe(text: str) -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("expected mapping")
    return data


def _validate_snapshot_file(report: ValidationReport, path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.add("error", "SNAP_JSON", f"invalid snapshot JSON: {exc}", str(path))
        return

    if data.get("format") != "buzz-agent-snapshot":
        report.add("error", "SNAP_FORMAT", "format must be buzz-agent-snapshot", str(path))
    if data.get("version") != 1:
        report.add("error", "SNAP_VERSION", "version must be 1", str(path))

    definition = data.get("definition") or {}
    profile = data.get("profile") or {}
    memory = data.get("memory") or {}

    if not str(definition.get("name") or "").strip():
        report.add("error", "SNAP_NAME", "definition.name required", str(path))
    if not str(profile.get("displayName") or "").strip():
        report.add("error", "SNAP_DISPLAY", "profile.displayName required", str(path))
    if memory.get("level") not in (None, "none") and memory.get("level") != "none":
        # accept snake enum none
        if memory.get("level") != "none":
            report.add(
                "warning",
                "SNAP_MEMORY",
                f"Beekeep prefers memory.level none; found {memory.get('level')!r}",
                str(path),
            )
    if memory.get("entries"):
        report.add("error", "SNAP_MEMORY_ENTRIES", "shared snapshots must not include memory entries", str(path))

    raw = path.read_text(encoding="utf-8").lower()
    from .constants import FORBIDDEN_SNAPSHOT_SUBSTRINGS

    for token in FORBIDDEN_SNAPSHOT_SUBSTRINGS:
        # allow the word "secret" in prompts only if discussing policy — still warn on key patterns
        if token in ("secret", "password") and token in raw:
            if re.search(rf"{token}\s*[:=]\s*\S+", raw):
                report.add("error", "SNAP_FORBIDDEN", f"forbidden pattern near {token}", str(path))
            continue
        if token in raw and token not in ("secret", "password"):
            # system prompts may say "Never request secrets" — only fail hard keys
            if token in ("private_key", "nsec", "api_key", "auth_tag"):
                report.add("error", "SNAP_FORBIDDEN", f"forbidden token '{token}' in snapshot", str(path))
