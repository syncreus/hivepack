"""ReceiptMem store + command-handling tests (no network: Names env=None)."""

import pytest

from hivepack.receiptmem.listener import Names, handle, parse_command
from hivepack.receiptmem.store import Store

CH = "chan-a"
EID = "a" * 64


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "mem.db")


def msg(content, *, pubkey="p1", mid=EID, ts=1785500000):
    return {"content": content, "pubkey": pubkey, "id": mid, "created_at": ts, "tags": []}


def names():
    return Names(env=None)


# -- store --------------------------------------------------------------


def test_remember_recall_roundtrip(store):
    rid = store.remember("ship the listener friday", "p1", CH, EID)
    assert rid == 1
    rows = store.recall("listener", channel=CH)
    assert len(rows) == 1
    assert rows[0]["event_id"] == EID
    assert rows[0]["entry"] == "ship the listener friday"


def test_remember_idempotent_on_event_id(store):
    assert store.remember("x", "p1", CH, EID) == 1
    assert store.remember("x", "p1", CH, EID) is None
    assert len(store.recall("x", channel=CH)) == 1


def test_forget_tombstones_and_hides(store):
    store.remember("secret plan", "p1", CH, EID)
    row = store.forget("#1")
    assert row["id"] == 1
    assert store.recall("plan", channel=CH) == []
    # tombstone, not delete: row still there for provenance
    assert store.get("1")["tombstone"] == 1


def test_get_by_event_prefix(store):
    store.remember("x", "p1", CH, EID)
    assert store.get(EID[:12])["id"] == 1
    assert store.get("bbbbbbbb") is None
    assert store.get("ab") is None  # too short for a prefix


def test_channel_scoping(store):
    store.remember("alpha decision", "p1", "chan-a", "a" * 64)
    store.remember("alpha decision", "p1", "chan-b", "b" * 64)
    assert len(store.recall("alpha", channel="chan-a")) == 1
    assert len(store.recall("alpha")) == 2


def test_fts_special_chars_dont_crash(store):
    store.remember("v2 plan (draft)", "p1", CH, EID)
    assert store.recall('what\'s the "plan"? (v2) OR NOT', channel=CH)
    assert store.recall("", channel=CH) == []


def test_state_survives_reopen(tmp_path):
    db = tmp_path / "mem.db"
    s1 = Store(db)
    s1.remember("durable", "p1", CH, EID)
    s1.mark_seen(EID)
    s1.set_watermark(CH, 12345)
    s1.db.close()
    s2 = Store(db)
    assert s2.recall("durable", channel=CH)[0]["event_id"] == EID
    assert s2.seen(EID)
    assert s2.get_watermark(CH) == 12345


# -- command parsing ----------------------------------------------------


def test_parse_basic_commands():
    assert parse_command("!remember buy the domain") == ("remember", "buy the domain")
    assert parse_command("!recall domain") == ("recall", "domain")
    assert parse_command("!forget #3") == ("forget", "#3")
    assert parse_command("!memories") == ("memories", "")


def test_parse_with_mention_prefix():
    assert parse_command("@Mem !recall domain") == ("recall", "domain")


def test_parse_multiline_remember():
    cmd, arg = parse_command("!remember line one\nline two")
    assert cmd == "remember" and arg == "line one\nline two"


def test_parse_ignores_midline_bang():
    # receipts quoting a command must never re-trigger the listener
    assert parse_command("1. [Decision] !recall foo — @p1") is None
    assert parse_command("no commands here") is None


# -- handle -------------------------------------------------------------


def test_handle_remember_receipt_pins_event_id(store):
    reply = handle(store, msg("!remember go live friday"), CH, set(), names())
    assert f"event {EID}" in reply and "#1" in reply


def test_handle_recall_returns_original_event_id(store):
    handle(store, msg("!remember go live friday"), CH, set(), names())
    reply = handle(store, msg("!recall go live", mid="c" * 64), CH, set(), names())
    assert f"event {EID}" in reply
    assert "[Decision] go live friday" in reply


def test_handle_recall_empty(store):
    reply = handle(store, msg("!recall nothing stored"), CH, set(), names())
    assert "Nothing on record" in reply


def test_handle_refuses_secrets(store):
    reply = handle(store, msg("!remember api_key = sk-123456"), CH, set(), names())
    assert "Refused" in reply
    assert store.recall("api_key", channel=CH) == []


def test_handle_forget_permissions(store):
    handle(store, msg("!remember the plan", pubkey="author"), CH, set(), names())
    denied = handle(store, msg("!forget #1", pubkey="stranger", mid="d" * 64), CH, set(), names())
    assert "Only the author" in denied
    assert store.recall("plan", channel=CH)  # still there
    ok = handle(store, msg("!forget #1", pubkey="op", mid="e" * 64), CH, {"op"}, names())
    assert "Forgot #1" in ok
    assert store.recall("plan", channel=CH) == []


def test_handle_duplicate_remember_is_silent(store):
    assert handle(store, msg("!remember once"), CH, set(), names()) is not None
    assert handle(store, msg("!remember once"), CH, set(), names()) is None


def test_handle_non_command_is_none(store):
    assert handle(store, msg("just chatting about plans"), CH, set(), names()) is None


# -- mcp server payload -------------------------------------------------


def test_mcp_recall_payload_shape(store):
    from hivepack.receiptmem.mcp_server import recall_payload

    import time as _t

    store.remember("ship friday", "p1", CH, EID, created_at=1785500000)
    out = recall_payload(store, "ship", channel=CH)
    expected_date = _t.strftime("%Y-%m-%d", _t.gmtime(1785500000))
    assert out == [
        {"text": "ship friday", "author": "p1", "date": expected_date, "event_id": EID}
    ]
    assert recall_payload(store, "ship", channel="other-chan") == []
