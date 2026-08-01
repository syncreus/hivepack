from pathlib import Path

import pytest

from hivepack.persona import parse_persona_md
from hivepack.snapshot import export_pack_snapshots, persona_to_snapshot
from hivepack.validate import validate_pack
from hivepack.constants import PACKS_DIR, DEFAULT_PACK


@pytest.fixture
def ship_squad() -> Path:
    return PACKS_DIR / DEFAULT_PACK


def test_parse_lead(ship_squad: Path):
    p = parse_persona_md(ship_squad / "agents" / "lead.persona.md")
    assert p.name == "lead"
    assert "orchestrator" in p.system_prompt.lower() or "Lead" in p.display_name


def test_validate_ship_squad_ok(ship_squad: Path):
    report = validate_pack(ship_squad)
    assert report.ok, [d.message for d in report.errors]
    assert set(report.persona_names) == {"lead", "implementer", "reviewer", "mem"}
    assert any(d.level == "think" for d in report.diagnostics)


def test_snapshot_memory_none(ship_squad: Path, tmp_path: Path):
    paths = export_pack_snapshots(ship_squad, tmp_path)
    assert len(paths) == 4
    import json

    for path in paths:
        data = json.loads(path.read_text())
        assert data["format"] == "buzz-agent-snapshot"
        assert data["version"] == 1
        assert data["memory"]["level"] == "none"
        assert data["memory"]["entries"] == []
        assert data["definition"]["systemPrompt"]
        assert data["profile"]["displayName"]


def test_rejects_missing_plugin(tmp_path: Path):
    report = validate_pack(tmp_path)
    assert not report.ok
    assert any(d.code == "PLUGIN_MISSING" for d in report.errors)


def test_persona_to_snapshot_shape():
    from hivepack.persona import Persona
    from pathlib import Path as P

    persona = Persona(
        path=P("x"),
        name="lead",
        display_name="Lead",
        description="d",
        body="You are lead." * 5,
    )
    snap = persona_to_snapshot(persona)
    assert "sourceIsBuiltin" in snap["definition"]
    assert "displayName" in snap["profile"]
