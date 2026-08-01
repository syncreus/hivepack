"""Convert existing Claude Code agents (.claude/agents/*.md) into Buzz personas.

Reads a Claude agent file (YAML-frontmatter subagent or plain markdown),
Buzz-ifies the system prompt, bundles named skills into the pack so the
agent runs on its real playbook instead of guessing, and registers the
persona in the pack's plugin.json.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .constants import PACKS_DIR

CLAUDE_AGENTS_DIRS = (
    Path.home() / ".claude" / "agents",
    Path(".claude") / "agents",
)
DEFAULT_SKILLS_ROOT = Path.home() / ".claude" / "skills"

# Packs are distributable. A local blocklist (one term per line) keeps private
# material out of converted personas — e.g. client names, employers, projects
# that must never appear in shareable packs. Missing file = guard disabled.
BLOCKLIST_FILE = Path(
    os.environ.get("HIVEPACK_BLOCKLIST_FILE", str(Path.home() / ".config" / "hivepack" / "blocklist.txt"))
)


def _blocklist_re() -> re.Pattern | None:
    if not BLOCKLIST_FILE.is_file():
        return None
    terms = [t.strip() for t in BLOCKLIST_FILE.read_text(encoding="utf-8").splitlines() if t.strip()]
    if not terms:
        return None
    return re.compile(r"(?i)\b(" + "|".join(re.escape(t) for t in terms) + r")\b")

# Skill dirs larger than this get SKILL.md only (the seo skill is 507MB).
MAX_FULL_SKILL_BYTES = 2 * 1024 * 1024

SKILL_COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".venv", ".git", "node_modules", "failures.jsonl", ".DS_Store"
)

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)


@dataclass
class ConvertResult:
    persona_path: Path
    pack_dir: Path
    skills_copied: list[str] = field(default_factory=list)
    skills_trimmed: list[str] = field(default_factory=list)  # SKILL.md only (too big)
    notes: list[str] = field(default_factory=list)


def find_claude_agent(name_or_path: str) -> Path:
    p = Path(name_or_path).expanduser()
    if p.is_file():
        return p.resolve()
    for base in CLAUDE_AGENTS_DIRS:
        candidate = base / f"{name_or_path}.md"
        if candidate.is_file():
            return candidate.resolve()
    raise SystemExit(f"claude agent not found: {name_or_path} (looked in {[str(b) for b in CLAUDE_AGENTS_DIRS]})")


def list_claude_agents() -> list[Path]:
    out: list[Path] = []
    for base in CLAUDE_AGENTS_DIRS:
        if base.is_dir():
            out.extend(sorted(base.glob("*.md")))
    return out


def parse_claude_agent(path: Path) -> tuple[str, str, str]:
    """Return (name, description, body) from either agent flavor."""
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if match:
        meta = yaml.safe_load(match.group(1)) or {}
        if isinstance(meta, dict) and meta.get("name"):
            name = str(meta["name"]).strip()
            desc = str(meta.get("description") or "").strip()
            body = match.group(2).strip()
            return name, _first_sentence(desc) or f"Converted from Claude agent {name}", body
    # Plain markdown: derive from filename + first meaningful line.
    name = path.stem.lower()
    body = text.strip()
    desc = ""
    for line in body.splitlines():
        line = line.strip().lstrip("#*_ ").strip()
        if line:
            desc = line
            if not line.endswith(":"):
                break
    return name, _first_sentence(desc) or f"Converted from Claude agent {name}", body


def _first_sentence(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return text


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")
    return slug or "agent"


def _display_name(slug: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", slug))


def buzz_adapter(display_name: str) -> str:
    return f"""## Buzz team adapter

You operate as **{display_name}** inside a Buzz channel alongside humans and other agents.

- Respond when @mentioned or when a task clearly matches your role; otherwise stay quiet.
- Keep replies short and thread-scoped. Post status and results, not logs.
- When a task matches an attached skill below, follow that skill exactly. Do not improvise a process your skill already defines.
- Hand off out-of-scope work to the right teammate or a human instead of guessing.
- Never paste secrets, API keys, tokens, or credentials.
"""


def skills_section(pack_dir: Path, skill_names: list[str]) -> str:
    if not skill_names:
        return ""
    lines = ["## Attached skills (source of truth)", ""]
    for name in skill_names:
        desc = ""
        skill_md = pack_dir / "skills" / name / "SKILL.md"
        if skill_md.is_file():
            m = FRONTMATTER_RE.match(skill_md.read_text(encoding="utf-8"))
            if m:
                meta = yaml.safe_load(m.group(1)) or {}
                desc = _first_sentence(str(meta.get("description") or ""), 160)
        lines.append(f"- `{name}` (./skills/{name}/) — {desc}")
    lines += [
        "",
        "If your harness (Claude Code, Codex, Goose) has these skills installed, invoke them "
        "by name via its skill mechanism. Otherwise use the copy bundled in this pack. "
        "These skills define HOW you do your job; do not guess.",
    ]
    return "\n".join(lines) + "\n"


def copy_skill(skill_name: str, pack_dir: Path, skills_root: Path) -> tuple[bool, bool]:
    """Copy a skill into the pack. Returns (copied, trimmed_to_skill_md_only)."""
    src = skills_root / skill_name
    if not (src / "SKILL.md").is_file():
        raise SystemExit(f"skill not found or missing SKILL.md: {src}")
    dst = pack_dir / "skills" / skill_name
    size = sum(f.stat().st_size for f in src.rglob("*") if f.is_file())
    if size > MAX_FULL_SKILL_BYTES:
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / "SKILL.md", dst / "SKILL.md")
        return True, True
    shutil.copytree(src, dst, ignore=SKILL_COPY_IGNORE, dirs_exist_ok=True)
    return True, False


def scaffold_pack(pack_dir: Path, pack_name: str) -> None:
    plugin_path = pack_dir / ".plugin" / "plugin.json"
    if plugin_path.is_file():
        return
    plugin_path.parent.mkdir(parents=True, exist_ok=True)
    plugin = {
        "$schema": "https://open-plugin-spec.org/schema/v1/plugin.json",
        "id": f"com.hivepack.{pack_name}",
        "name": f"HivePack {_display_name(pack_name)}",
        "version": "0.1.0",
        "description": f"Custom agent pack '{pack_name}' converted from local Claude Code agents.",
        "author": "HivePack",
        "license": "Apache-2.0",
        "keywords": ["buzz", "agents", "hivepack", pack_name],
        "engines": {"buzz": ">=0.5.0"},
        "personas": [],
        "pack_instructions": "instructions.md",
        "defaults": {
            "triggers": {"mentions": True, "keywords": [], "all_messages": False},
            "subscribe": [],
            "thread_replies": True,
            "broadcast_replies": False,
        },
    }
    plugin_path.write_text(json.dumps(plugin, indent=2) + "\n", encoding="utf-8")
    instructions = pack_dir / "instructions.md"
    if not instructions.is_file():
        instructions.write_text(
            f"# HivePack {_display_name(pack_name)} — team instructions\n\n"
            "Agents converted from local Claude Code agents. Humans steer; agents execute.\n\n"
            "- @mention the right specialist; do not all reply to every message.\n"
            "- Prefer threads per task; keep the channel for status and decisions.\n"
            "- Never paste secrets, API keys, tokens, or production credentials.\n"
            "- No production deploys or force-pushes without explicit human approval in-channel.\n",
            encoding="utf-8",
        )


def register_persona(pack_dir: Path, rel_path: str) -> None:
    plugin_path = pack_dir / ".plugin" / "plugin.json"
    plugin = json.loads(plugin_path.read_text(encoding="utf-8"))
    personas = plugin.setdefault("personas", [])
    if rel_path not in personas:
        personas.append(rel_path)
    plugin_path.write_text(json.dumps(plugin, indent=2) + "\n", encoding="utf-8")


def convert_agent(
    agent: str,
    pack_name: str,
    skills: list[str] | None = None,
    *,
    skills_root: Path = DEFAULT_SKILLS_ROOT,
    packs_dir: Path = PACKS_DIR,
) -> ConvertResult:
    agent_path = find_claude_agent(agent)
    name, description, body = parse_claude_agent(agent_path)

    block_re = _blocklist_re()
    if block_re:
        blocked = block_re.search(agent_path.name) or block_re.search(body) or block_re.search(name)
        if blocked:
            raise SystemExit(
                f"refusing to convert '{agent_path.name}': matches private-blocklist term "
                f"('{blocked.group(0)}'). Packs are distributable; keep blocklisted material out."
            )

    slug = _slugify(name)
    pack_dir = (packs_dir / pack_name).resolve()
    scaffold_pack(pack_dir, pack_name)

    result = ConvertResult(persona_path=pack_dir / "agents" / f"{slug}.persona.md", pack_dir=pack_dir)

    for skill_name in skills or []:
        # Per-skill root fallback: project skills root first, then global.
        root = skills_root if (skills_root / skill_name / "SKILL.md").is_file() else DEFAULT_SKILLS_ROOT
        _, trimmed = copy_skill(skill_name, pack_dir, root)
        result.skills_copied.append(skill_name)
        if trimmed:
            result.skills_trimmed.append(skill_name)

    display = _display_name(slug)
    frontmatter = {
        "name": slug,
        "display_name": display,
        "description": description,
        "version": "0.1.0",
        "author": "HivePack convert",
        "skills": [f"./skills/{s}/" for s in (skills or [])],
        "triggers": {"mentions": True, "keywords": [], "all_messages": False},
        "thread_replies": True,
        "broadcast_replies": False,
    }
    parts = [buzz_adapter(display)]
    sk = skills_section(pack_dir, skills or [])
    if sk:
        parts.append(sk)
    parts.append("## Original agent brief\n\n" + body)

    persona_text = (
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
        + "\n---\n\n"
        + "\n".join(parts).strip()
        + "\n"
    )
    result.persona_path.parent.mkdir(parents=True, exist_ok=True)
    result.persona_path.write_text(persona_text, encoding="utf-8")
    register_persona(pack_dir, f"agents/{slug}.persona.md")

    # Suggest skills the agent body mentions but were not attached.
    if skills_root.is_dir():
        attached = set(skills or [])
        lower_body = body.lower()
        for cand in sorted(p.name for p in skills_root.iterdir() if (p / "SKILL.md").is_file()):
            if cand not in attached and len(cand) > 4 and cand.lower() in lower_body:
                result.notes.append(f"agent text mentions skill '{cand}' — consider --skills {cand}")
    return result
