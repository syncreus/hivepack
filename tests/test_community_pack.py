import json
from pathlib import Path

import pytest

from hivepack.constants import PACKS_DIR
from hivepack.persona import parse_persona_md
from hivepack.snapshot import export_pack_snapshots
from hivepack.validate import validate_pack


@pytest.fixture
def community_squad() -> Path:
    return PACKS_DIR / "community-squad"


def test_validate_community_squad_ok(community_squad: Path):
    report = validate_pack(community_squad)
    assert report.ok, [d.message for d in report.errors]
    assert set(report.persona_names) == {"greeter", "rules"}


def test_greeter_join_trigger_and_never_twice(community_squad: Path):
    p = parse_persona_md(community_squad / "agents" / "greeter.persona.md")
    body = p.system_prompt.lower()
    assert "40099" in body
    assert "never welcome the same person twice" in body
    # generalized: no trace of the private community it was proven in
    assert "hcc" not in body
    assert "hcc" not in p.description.lower()


def test_rules_cites_verbatim_and_escalates(community_squad: Path):
    p = parse_persona_md(community_squad / "agents" / "rules.persona.md")
    body = p.system_prompt.lower()
    assert "verbatim" in body
    assert "canvas" in body
    assert "escalate" in body
    assert "moderator" in body


def test_acp_env_has_greeter_join_override(community_squad: Path):
    env = (community_squad / "acp.env").read_text()
    assert "BUZZ_ACP_KINDS=9" in env
    assert "BUZZ_ACP_KINDS=40099" in env


def test_canvas_template_covers_handbook_sections(community_squad: Path):
    text = (community_squad / "canvas" / "handbook-template.md").read_text()
    for heading in ("## Start here", "## Desks", "## House rules", "## Moderators"):
        assert heading in text


def test_snapshots_config_only(community_squad: Path, tmp_path: Path):
    paths = export_pack_snapshots(community_squad, tmp_path)
    assert len(paths) == 2
    for path in paths:
        data = json.loads(path.read_text())
        assert data["format"] == "buzz-agent-snapshot"
        assert data["version"] == 1
        assert data["memory"]["level"] == "none"
        assert data["memory"]["entries"] == []
        assert data["definition"]["systemPrompt"]
        assert data["profile"]["displayName"]
