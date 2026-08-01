"""fleet set/status against a fixture store — no desktop, no relay."""

import json

from hivepack import buzzctl

FIXTURE = [
    # Key-less definition record (display_name set, no pubkey).
    {"display_name": "Atlas 🏗️", "pubkey": "", "respond_to": "owner-only",
     "definition_respond_to": "owner-only", "env_vars": {"BUZZ_ACP_SUBSCRIBE": "all"},
     "runtime": "claude", "model": "opus", "updated_at": "2026-01-01T00:00:00+00:00"},
    # Instance record for the same agent (pubkey set, display_name absent).
    {"name": "Atlas 🏗️", "pubkey": "aa11", "respond_to": "owner-only",
     "runtime": "claude", "model": "opus", "updated_at": "2026-01-02T00:00:00+00:00"},
    # Unrelated instance, must stay untouched by --agents atlas.
    {"name": "Scout 🔬", "pubkey": "bb22", "respond_to": "owner-only",
     "updated_at": "2026-01-02T00:00:00+00:00"},
]


def _with_store(tmp_path, monkeypatch):
    store = tmp_path / "managed-agents.json"
    store.write_text(json.dumps(FIXTURE), encoding="utf-8")
    monkeypatch.setattr(buzzctl, "MANAGED_AGENTS", store)
    # Bypass the desktop quit/backup/relaunch wrapper: run the edit directly.
    monkeypatch.setattr(buzzctl, "_desktop_quit_and_relaunch", lambda fn: fn())
    return store


def test_fleet_set_respond_hits_instance_and_definition(tmp_path, monkeypatch):
    store = _with_store(tmp_path, monkeypatch)
    rc = buzzctl.main(["fleet", "set", "--agents", "atlas", "--respond", "anyone"])
    assert rc == 0
    recs = json.loads(store.read_text(encoding="utf-8"))
    inst = next(r for r in recs if r.get("pubkey") == "aa11")
    dfn = next(r for r in recs if not r.get("pubkey"))
    other = next(r for r in recs if r.get("pubkey") == "bb22")
    # Instance respond_to is what spawns BUZZ_ACP_RESPOND_TO.
    assert inst["respond_to"] == "anyone"
    # Definition seeds future instances; its cosmetic respond_to is left alone
    # (the desktop resets it to owner-only on every persona save anyway).
    assert dfn["definition_respond_to"] == "anyone"
    assert dfn["respond_to"] == "owner-only"
    assert other["respond_to"] == "owner-only"


def test_fleet_set_all_covers_every_instance(tmp_path, monkeypatch):
    store = _with_store(tmp_path, monkeypatch)
    rc = buzzctl.main(["fleet", "set", "--all", "--respond", "anyone"])
    assert rc == 0
    recs = json.loads(store.read_text(encoding="utf-8"))
    assert all(r["respond_to"] == "anyone" for r in recs if r.get("pubkey"))


def test_fleet_set_model_stays_on_definition(tmp_path, monkeypatch):
    store = _with_store(tmp_path, monkeypatch)
    rc = buzzctl.main(["fleet", "set", "--agents", "atlas", "--model", "sonnet"])
    assert rc == 0
    recs = json.loads(store.read_text(encoding="utf-8"))
    assert next(r for r in recs if not r.get("pubkey"))["model"] == "sonnet"
    assert next(r for r in recs if r.get("pubkey") == "aa11")["model"] == "opus"


def test_fleet_status_reads_instance_truth(tmp_path, monkeypatch, capsys):
    _with_store(tmp_path, monkeypatch)
    recs = json.loads(buzzctl.MANAGED_AGENTS.read_text(encoding="utf-8"))
    recs[1]["respond_to"] = "anyone"  # instance flipped; definition stays owner-only
    buzzctl.MANAGED_AGENTS.write_text(json.dumps(recs), encoding="utf-8")
    rc = buzzctl.main(["fleet", "status", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["Atlas"]["respond_to"] == "anyone"
    assert out["Atlas"]["subscribe"] == "all"  # env merged in from the definition
    assert out["Scout"]["respond_to"] == "owner-only"
