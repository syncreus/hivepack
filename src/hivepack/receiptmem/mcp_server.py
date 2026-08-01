"""ReceiptMem MCP server — shared memory as infrastructure.

One tool: recall(query, channel?) -> [{text, author, date, event_id}].
Point any agent harness at this binary (e.g. Buzz's BUZZ_ACP_MCP_COMMAND)
and every agent on the machine can query the workspace memory the
receiptmem listener maintains — not just the mem agent itself.

Needs the 'mcp' package: pip install 'hivepack[mcp]'
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from .store import DEFAULT_DB, Store


def recall_payload(store: Store, query: str, channel: str | None = None,
                   limit: int = 5) -> list[dict]:
    return [
        {
            "text": r["entry"],
            "author": r["author"],
            "date": time.strftime("%Y-%m-%d", time.gmtime(r["created_at"])),
            "event_id": r["event_id"],
        }
        for r in store.recall(query, channel=channel, limit=limit)
    ]


def main(argv: list[str] | None = None) -> int:
    try:
        from mcp.server.mcpserver import MCPServer as ServerApp  # mcp >= 2.0
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as ServerApp  # mcp 1.x
        except ImportError:
            raise SystemExit("receiptmem-mcp needs the 'mcp' package: pip install 'hivepack[mcp]'")

    p = argparse.ArgumentParser(prog="receiptmem-mcp", description="ReceiptMem MCP server")
    p.add_argument("--db", default=None, help=f"sqlite path (default: {DEFAULT_DB})")
    args = p.parse_args(argv)
    db_path = Path(args.db) if args.db else DEFAULT_DB
    app = ServerApp("receiptmem")

    @app.tool()
    def recall(query: str, channel: str | None = None, limit: int = 5) -> list[dict]:
        """Search the shared workspace memory. Returns provenance-pinned
        entries: text, author pubkey, date, and the Nostr event id of the
        original !remember message."""
        # per-call connection: MCP runs tools in worker threads, and sqlite
        # objects are bound to the thread that created them
        return recall_payload(Store(db_path), query, channel, limit)

    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
