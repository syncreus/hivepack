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


def test_fleet_set_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    store = _with_store(tmp_path, monkeypatch)
    before = store.read_text(encoding="utf-8")

    def boom(fn):
        raise AssertionError("dry run must not bounce the desktop")

    monkeypatch.setattr(buzzctl, "_desktop_quit_and_relaunch", boom)
    rc = buzzctl.main(["fleet", "set", "--all", "--respond", "anyone", "--dry-run"])
    assert rc == 0
    assert store.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "[DRY]" in out and "respond_to: owner-only -> anyone" in out
    # One instance flip each for atlas + scout, plus atlas's definition seed.
    assert "3 change(s)" in out


def test_fleet_set_noop_skips_desktop_bounce(tmp_path, monkeypatch, capsys):
    _with_store(tmp_path, monkeypatch)

    def boom(fn):
        raise AssertionError("no-op set must not bounce the desktop")

    monkeypatch.setattr(buzzctl, "_desktop_quit_and_relaunch", boom)
    rc = buzzctl.main(["fleet", "set", "--all", "--respond", "owner-only"])
    assert rc == 0
    assert "nothing to do" in capsys.readouterr().out


def test_fleet_doctor_flags_drift_and_not_running(tmp_path, monkeypatch, capsys):
    _with_store(tmp_path, monkeypatch)
    monkeypatch.setattr(buzzctl, "_live_agent_envs", lambda: {
        "Atlas": {"BUZZ_ACP_RESPOND_TO": "anyone", "BUZZ_ACP_MODEL": "opus",
                  "BUZZ_ACP_SUBSCRIBE": "all"},
        "Ghost": {"BUZZ_ACP_RESPOND_TO": "anyone"},
    })
    rc = buzzctl.main(["fleet", "doctor", "--json"])
    out = json.loads(capsys.readouterr().out)
    agents = {r["agent"]: r for r in out["agents"]}
    assert rc == 2 and out["ok"] is False
    # Store says owner-only, live process spawned with anyone -> drift.
    assert agents["Atlas"]["state"] == "drift"
    assert agents["Atlas"]["drift"] == {
        "respond_to": {"store": "owner-only", "live": "anyone"}}
    assert agents["Scout"]["state"] == "not-running"
    assert agents["Ghost"]["state"] == "unmanaged"


def test_fleet_doctor_passes_when_live_matches(tmp_path, monkeypatch, capsys):
    _with_store(tmp_path, monkeypatch)
    monkeypatch.setattr(buzzctl, "_live_agent_envs", lambda: {
        "Atlas": {"BUZZ_ACP_RESPOND_TO": "owner-only", "BUZZ_ACP_MODEL": "opus",
                  "BUZZ_ACP_SUBSCRIBE": "all"},
        "Scout": {"BUZZ_ACP_RESPOND_TO": "owner-only"},
    })
    rc = buzzctl.main(["fleet", "doctor"])
    assert rc == 0
    assert "RESULT: PASS" in capsys.readouterr().out


def test_fleet_doctor_fails_with_no_live_processes(tmp_path, monkeypatch, capsys):
    _with_store(tmp_path, monkeypatch)
    monkeypatch.setattr(buzzctl, "_live_agent_envs", lambda: {})
    rc = buzzctl.main(["fleet", "doctor"])
    assert rc == 2
    assert "no live buzz-acp" in capsys.readouterr().out


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
