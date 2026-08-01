"""Export Buzz Desktop / Beekeep-compatible .agent.json snapshots from personas."""

from __future__ import annotations

import json
from pathlib import Path

from .constants import ACP_ENV_DEFAULTS, ACP_ENV_FILENAME, SNAPSHOT_FORMAT, SNAPSHOT_VERSION
from .persona import Persona, parse_persona_md


def persona_to_snapshot(persona: Persona, *, runtime: str | None = None) -> dict:
    """Build buzz-agent-snapshot v1 (camelCase) with memory level none."""
    # Append pack role tag into about for import preview clarity.
    about = persona.description
    system_prompt = persona.system_prompt
    # runtime stays unset so the importer uses the user's default harness
    # (changeable per-agent later). respondTo is omitted: valid values are
    # owner-only/allowlist/anyone and the importer default is correct.
    return {
        "format": SNAPSHOT_FORMAT,
        "version": SNAPSHOT_VERSION,
        "definition": {
            "name": persona.name,
            "sourceIsBuiltin": False,
            "systemPrompt": system_prompt,
            **({"runtime": runtime} if runtime else {}),
        },
        "profile": {
            "displayName": persona.display_name,
            "about": about,
        },
        "memory": {
            "level": "none",
            "entries": [],
        },
    }


def write_acp_env(pack_dir: Path) -> Path:
    """Write the pack's buzz-acp env file (idempotent, keeps user edits)."""
    path = pack_dir / ACP_ENV_FILENAME
    if not path.is_file():
        lines = [
            "# buzz-acp harness environment for this pack's agents.",
            "# Desktop: add these in Agents -> <agent> -> Environment after import.",
            "# Headless: `set -a; source acp.env; set +a` before launching buzz-acp.",
            "# subscribe=all lets agents see all channel traffic; replies stay mention-gated.",
        ]
        lines += [f"{k}={v}" for k, v in ACP_ENV_DEFAULTS]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def export_pack_snapshots(pack_dir: Path, out_dir: Path | None = None) -> list[Path]:
    pack_dir = pack_dir.resolve()
    plugin = json.loads((pack_dir / ".plugin" / "plugin.json").read_text(encoding="utf-8"))
    out_dir = (out_dir or (pack_dir / "snapshots")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    write_acp_env(pack_dir)

    written: list[Path] = []
    for rel in plugin.get("personas") or []:
        persona = parse_persona_md(pack_dir / str(rel))
        # Runtime left unset so importers pick local harness (Claude/Codex/Hermes/Goose).
        snap = persona_to_snapshot(persona, runtime=None)
        path = out_dir / f"{persona.name}.agent.json"
        path.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)
    return written
