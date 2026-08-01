"""Tests for Claude agent → Buzz persona conversion."""

from pathlib import Path

import pytest

import json

from hivepack.convert import convert_agent, parse_claude_agent
from hivepack.persona import parse_persona_md
from hivepack.snapshot import export_pack_snapshots
from hivepack.validate import validate_pack

FRONTMATTER_AGENT = """---
name: blogger
description: Writes our blog posts to the house standard.
model: sonnet
tools: Read, Write
---

You write blog posts. Follow the house style. Research facts first.
Always run the three-stage review before shipping anything.
"""

PLAIN_AGENT = """# Widget Advisor

**Role:** You advise on widgets with citations.

## Rules
1. Cite sources
2. Flag uncertainty
"""


def _mk_skill(root: Path, name: str, big: bool = False) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: House standard for {name}.\n---\n\n# {name}\nDo it right.\n",
        encoding="utf-8",
    )
    if big:
        (d / "blob.bin").write_bytes(b"x" * (3 * 1024 * 1024))


def test_convert_frontmatter_agent_with_skill(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "blogger.md").write_text(FRONTMATTER_AGENT, encoding="utf-8")
    skills_root = tmp_path / "skills"
    _mk_skill(skills_root, "blog-standard")

    result = convert_agent(
        str(agents / "blogger.md"),
        "test-pack",
        ["blog-standard"],
        skills_root=skills_root,
        packs_dir=tmp_path / "packs",
    )
    persona = parse_persona_md(result.persona_path)
    assert persona.name == "blogger"
    assert "./skills/blog-standard/" in persona.skills
    assert "Buzz team adapter" in persona.body
    assert "three-stage review" in persona.body  # original brief preserved
    assert (result.pack_dir / "skills" / "blog-standard" / "SKILL.md").is_file()

    report = validate_pack(result.pack_dir)
    assert report.ok, [d.message for d in report.errors]

    snaps = export_pack_snapshots(result.pack_dir)
    data = json.loads(snaps[0].read_text(encoding="utf-8"))
    # runtime unset → importer uses the user's default harness; respondTo
    # omitted (its valid values are owner-only/allowlist/anyone).
    assert "runtime" not in data["definition"]
    assert "respondTo" not in data["definition"]
    env_file = result.pack_dir / "acp.env"
    assert env_file.is_file()
    env_text = env_file.read_text(encoding="utf-8")
    assert "BUZZ_ACP_SUBSCRIBE=all" in env_text
    assert "BUZZ_ACP_KINDS=9" in env_text


def test_convert_plain_agent_and_big_skill_trimmed(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "widget-advisor.md").write_text(PLAIN_AGENT, encoding="utf-8")
    skills_root = tmp_path / "skills"
    _mk_skill(skills_root, "huge-skill", big=True)

    result = convert_agent(
        str(agents / "widget-advisor.md"),
        "test-pack2",
        ["huge-skill"],
        skills_root=skills_root,
        packs_dir=tmp_path / "packs",
    )
    assert result.skills_trimmed == ["huge-skill"]
    dst = result.pack_dir / "skills" / "huge-skill"
    assert (dst / "SKILL.md").is_file()
    assert not (dst / "blob.bin").exists()
    name, desc, _ = parse_claude_agent(agents / "widget-advisor.md")
    assert name == "widget-advisor"
    assert desc


def test_convert_refuses_blocklisted_material(tmp_path: Path, monkeypatch) -> None:
    blocklist = tmp_path / "blocklist.txt"
    blocklist.write_text("secretclient\n", encoding="utf-8")
    monkeypatch.setenv("HIVEPACK_BLOCKLIST_FILE", str(blocklist))
    import importlib

    import hivepack.convert as conv
    importlib.reload(conv)

    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "helper.md").write_text(
        "# Helper\nYou support the SecretClient audit workflow.\n", encoding="utf-8"
    )
    try:
        with pytest.raises(SystemExit, match="private-blocklist"):
            conv.convert_agent(
                str(agents / "helper.md"),
                "test-pack3",
                [],
                skills_root=tmp_path / "skills",
                packs_dir=tmp_path / "packs",
            )
    finally:
        monkeypatch.delenv("HIVEPACK_BLOCKLIST_FILE")
        importlib.reload(conv)
