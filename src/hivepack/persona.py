"""Parse Buzz .persona.md files (YAML frontmatter + markdown body)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)


@dataclass
class Persona:
    path: Path
    name: str
    display_name: str
    description: str
    body: str
    raw_frontmatter: dict[str, Any] = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)
    version: str | None = None
    author: str | None = None

    @property
    def system_prompt(self) -> str:
        return self.body.strip() + "\n"


def parse_persona_md(path: Path) -> Persona:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{path}: missing YAML frontmatter delimited by ---")

    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError(f"{path}: frontmatter must be a mapping")

    body = match.group(2).strip()
    if not body:
        raise ValueError(f"{path}: empty persona body (system prompt)")

    name = str(meta.get("name") or "").strip()
    display_name = str(meta.get("display_name") or "").strip()
    description = str(meta.get("description") or "").strip()
    if not name:
        raise ValueError(f"{path}: name is required")
    if not display_name:
        raise ValueError(f"{path}: display_name is required")
    if not description:
        raise ValueError(f"{path}: description is required")

    skills = meta.get("skills") or []
    if not isinstance(skills, list):
        raise ValueError(f"{path}: skills must be a list")

    return Persona(
        path=path,
        name=name,
        display_name=display_name,
        description=description,
        body=body,
        raw_frontmatter=meta,
        skills=[str(s) for s in skills],
        version=(str(meta["version"]) if meta.get("version") is not None else None),
        author=(str(meta["author"]) if meta.get("author") is not None else None),
    )
