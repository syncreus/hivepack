"""ReceiptMem store — sqlite + FTS5, every memory pinned to its Nostr event id.

One database holds all channels; recall is channel-scoped by default.
Forgetting is a tombstone, never a delete: provenance survives.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

DEFAULT_DB = Path(
    os.environ.get("RECEIPTMEM_DB", str(Path.home() / ".local/share/receiptmem/receiptmem.db"))
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    entry TEXT NOT NULL,
    author TEXT NOT NULL,
    channel TEXT NOT NULL,
    thread TEXT,
    event_id TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    salience REAL NOT NULL DEFAULT 1.0,
    tombstone INTEGER NOT NULL DEFAULT 0
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    entry, content='memories', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, entry) VALUES (new.id, new.entry);
END;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seen_events (event_id TEXT PRIMARY KEY);
"""


def _fts_quote(query: str) -> str:
    """Neutralize FTS5 operators (quote every token) and OR them:
    natural-language recall queries match on any word, bm25 ranks best first."""
    tokens = [t.replace('"', "") for t in query.split()]
    return " OR ".join(f'"{t}"' for t in tokens if t)


class Store:
    def __init__(self, path: Path | str = DEFAULT_DB):
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def remember(
        self,
        entry: str,
        author: str,
        channel: str,
        event_id: str,
        created_at: int | None = None,
        thread: str | None = None,
        salience: float = 2.0,
    ) -> int | None:
        """Store verbatim. Returns row id, or None if event_id already stored."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO memories (entry, author, channel, thread, event_id, created_at, salience)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry, author, channel, thread, event_id, created_at or int(time.time()), salience),
        )
        self.db.commit()
        return cur.lastrowid if cur.rowcount else None

    def recall(self, query: str, channel: str | None = None, limit: int = 5) -> list[sqlite3.Row]:
        match = _fts_quote(query)
        if not match:
            return []
        sql = (
            "SELECT m.* FROM memories_fts f JOIN memories m ON m.id = f.rowid"
            " WHERE memories_fts MATCH ? AND m.tombstone = 0"
        )
        args: list = [match]
        if channel:
            sql += " AND m.channel = ?"
            args.append(channel)
        sql += " ORDER BY rank LIMIT ?"
        args.append(limit)
        return self.db.execute(sql, args).fetchall()

    def get(self, ref: str) -> sqlite3.Row | None:
        """Look up by row id ('#7' or '7') or event-id prefix (8+ hex chars)."""
        ref = ref.strip().lstrip("#")
        if ref.isdigit():
            return self.db.execute("SELECT * FROM memories WHERE id = ?", (int(ref),)).fetchone()
        if len(ref) >= 8:
            return self.db.execute(
                "SELECT * FROM memories WHERE event_id LIKE ?", (ref + "%",)
            ).fetchone()
        return None

    def forget(self, ref: str) -> sqlite3.Row | None:
        row = self.get(ref)
        if row:
            self.db.execute("UPDATE memories SET tombstone = 1 WHERE id = ?", (row["id"],))
            self.db.commit()
        return row

    def recent(self, channel: str, limit: int = 10) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM memories WHERE channel = ? AND tombstone = 0"
            " ORDER BY created_at DESC LIMIT ?",
            (channel, limit),
        ).fetchall()

    # -- listener state (survives restarts) --------------------------------

    def seen(self, event_id: str) -> bool:
        return bool(
            self.db.execute("SELECT 1 FROM seen_events WHERE event_id = ?", (event_id,)).fetchone()
        )

    def mark_seen(self, event_id: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO seen_events (event_id) VALUES (?)", (event_id,))
        self.db.commit()

    def get_watermark(self, channel: str) -> int | None:
        row = self.db.execute(
            "SELECT value FROM meta WHERE key = ?", (f"watermark:{channel}",)
        ).fetchone()
        return int(row["value"]) if row else None

    def set_watermark(self, channel: str, ts: int) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (f"watermark:{channel}", str(ts)),
        )
        self.db.commit()
