"""Shared paths and constants."""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = PACKAGE_ROOT / "packs"
DEFAULT_PACK = "ship-squad"

# buzz-agent-snapshot v1
SNAPSHOT_FORMAT = "buzz-agent-snapshot"
SNAPSHOT_VERSION = 1

# buzz-acp harness env for pack agents. The snapshot format strips env vars by
# design (agent_snapshot.rs secret exclusion), so these ship as a pack-level
# acp.env file and an import-checklist step instead.
# subscribe=all: agent receives every channel message (mention-gating still
# controls replies). kinds=9: chat messages.
ACP_ENV_FILENAME = "acp.env"
ACP_ENV_DEFAULTS = (
    ("BUZZ_ACP_SUBSCRIBE", "all"),
    ("BUZZ_ACP_KINDS", "9"),
)

# Fields Beekeep forbids in shared snapshots (defense in depth)
FORBIDDEN_SNAPSHOT_SUBSTRINGS = (
    "private_key",
    "nsec",
    "auth_tag",
    "env_vars",
    "relay_url",
    "acp_command",
    "agent_command",
    "mcp_command",
    "api_key",
    "secret",
    "password",
)
