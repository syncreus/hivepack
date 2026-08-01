"""Gate logic with mocked backends, plus an MCP stdio contract test."""

import json
import os
import stat
import subprocess
import sys
import time

import pytest

from hivepack.stopgate import server as sg


def cfg(**over):
    c = sg.load_config("/nonexistent/stopgate.toml")
    c["ci"].update({"enabled": True, "branch": "main"})
    c["approval"].update({"enabled": True, "channel": "chan-uuid"})
    for k, v in over.items():
        if isinstance(v, dict):
            c[k].update(v)
        else:
            c[k] = v
    return c


def fake_run(responses):
    """responses: list of (code, stdout) popped per call; last one repeats."""
    calls = []

    def run(argv, cwd=None, env=None, timeout=None):
        calls.append(argv)
        code, out = responses.pop(0) if len(responses) > 1 else responses[0]
        return code, out, ""

    run.calls = calls
    return run


GH_GREEN = (0, json.dumps([{"status": "completed", "conclusion": "success",
                            "displayTitle": "build", "url": "u"}]))
GH_RED = (0, json.dumps([{"status": "completed", "conclusion": "failure",
                          "displayTitle": "build", "url": "u"}]))
GH_RUNNING = (0, json.dumps([{"status": "in_progress", "conclusion": None,
                              "displayTitle": "build", "url": "u"}]))
SEND_OK = (0, json.dumps({"accepted": True, "event_id": "e" * 64}))


def reactions(emoji="👍", pubkeys=("alice",)):
    return (0, json.dumps({"reactions": [{"count": len(pubkeys), "emoji": emoji,
                                          "pubkeys": list(pubkeys)}]}))


# ── ci gate ──────────────────────────────────────────────────────────────

def test_ci_red_objects(monkeypatch):
    monkeypatch.setattr(sg, "_run", fake_run([GH_RED]))
    out = sg.ci_check(cfg(approval={"enabled": False}), {})
    assert "failure" in out and "main" in out


def test_ci_running_objects(monkeypatch):
    monkeypatch.setattr(sg, "_run", fake_run([GH_RUNNING]))
    assert "still running" in sg.ci_check(cfg(), {})


def test_ci_green_allows_and_sticks(monkeypatch):
    run = fake_run([GH_GREEN])
    monkeypatch.setattr(sg, "_run", run)
    state = {}
    assert sg.ci_check(cfg(), state) == ""
    assert state["ci_green"]
    assert sg.ci_check(cfg(), state) == ""
    assert len(run.calls) == 1  # sticky green skips the second gh call


def test_ci_no_runs_allows(monkeypatch):
    monkeypatch.setattr(sg, "_run", fake_run([(0, "[]")]))
    assert sg.ci_check(cfg(), {}) == ""


def test_ci_backend_error_objects(monkeypatch):
    monkeypatch.setattr(sg, "_run", fake_run([(-1, "")]))
    assert "could not check" in sg.ci_check(cfg(), {})


def test_ci_disabled_allows():
    assert sg.ci_check(cfg(ci={"enabled": False}), {}) == ""


# ── approval gate ────────────────────────────────────────────────────────

def test_approval_posts_request_then_objects(monkeypatch):
    monkeypatch.setattr(sg, "_run", fake_run([SEND_OK]))
    state = {}
    out = sg.approval_check(cfg(), state)
    assert "must react" in out and state["request_event_id"] == "e" * 64


def test_approval_reaction_releases(monkeypatch):
    monkeypatch.setattr(sg, "_run", fake_run([reactions()]))
    state = {"request_event_id": "e" * 64}
    assert sg.approval_check(cfg(), state) == ""
    assert state["approved"]


def test_approval_wrong_emoji_still_objects(monkeypatch):
    monkeypatch.setattr(sg, "_run", fake_run([reactions(emoji="👀")]))
    assert "waiting" in sg.approval_check(cfg(), {"request_event_id": "e" * 64})


def test_approval_skin_tone_variant_matches(monkeypatch):
    monkeypatch.setattr(sg, "_run", fake_run([reactions(emoji="👍🏽")]))
    assert sg.approval_check(cfg(), {"request_event_id": "e" * 64}) == ""


def test_approval_respects_approver_list(monkeypatch):
    monkeypatch.setattr(sg, "_run", fake_run([reactions(pubkeys=("mallory",))]))
    c = cfg(approval={"approvers": ["alice"]})
    assert "waiting" in sg.approval_check(c, {"request_event_id": "e" * 64})
    monkeypatch.setattr(sg, "_run", fake_run([reactions(pubkeys=("mallory", "alice"))]))
    assert sg.approval_check(c, {"request_event_id": "e" * 64}) == ""


def test_approval_send_failure_objects(monkeypatch):
    monkeypatch.setattr(sg, "_run", fake_run([(2, "")]))
    state = {}
    assert "could not post" in sg.approval_check(cfg(), state)
    assert "request_event_id" not in state  # retries the post next _Stop


# ── stop verdict: ordering + fail-open timeout ───────────────────────────

def test_stop_ci_objection_short_circuits_approval(monkeypatch):
    run = fake_run([GH_RED])
    monkeypatch.setattr(sg, "_run", run)
    out = sg.stop_verdict(cfg(), {}, now=0.0)
    assert "ci gate" in out and len(run.calls) == 1  # approval never called


def test_stop_all_green_allows(monkeypatch):
    monkeypatch.setattr(sg, "_run", fake_run([GH_GREEN, reactions()]))
    state = {"request_event_id": "e" * 64}
    assert sg.stop_verdict(cfg(), state, now=0.0) == ""


def test_timeout_fail_open(monkeypatch):
    monkeypatch.setattr(sg, "_run", fake_run([GH_RED]))
    c = cfg(timeout_minutes=30)
    state = {"started_at": 0.0}
    assert sg.stop_verdict(c, state, now=29 * 60) != ""
    assert sg.stop_verdict(c, state, now=31 * 60) == ""


def test_timeout_zero_never_fails_open(monkeypatch):
    monkeypatch.setattr(sg, "_run", fake_run([GH_RED]))
    state = {"started_at": 0.0}
    assert sg.stop_verdict(cfg(timeout_minutes=0), state, now=1e9) != ""


def test_exhausted_window_objects_without_backend_call(monkeypatch):
    run = fake_run([GH_GREEN])
    monkeypatch.setattr(sg, "_run", run)
    state = {"_stop_deadline": time.monotonic() - 1}  # window already burned
    assert "ran out of time" in sg.ci_check(cfg(), state)
    assert "ran out of time" in sg.approval_check(cfg(), state)
    assert run.calls == []  # no backend call may start without budget


def test_post_compact_reminds_only_while_pending():
    c = cfg()
    assert sg.post_compact_note(c, {}) == ""
    assert "outstanding" in sg.post_compact_note(c, {"request_event_id": "e" * 64})
    assert sg.post_compact_note(c, {"request_event_id": "e" * 64, "approved": True}) == ""


# ── MCP stdio contract (drives the built server like buzz-agent does) ────

@pytest.fixture
def stdio_server(tmp_path):
    """Spawn the real server with fake gh/buzz CLIs on PATH."""
    gh_out = tmp_path / "gh_out.json"
    gh_out.write_text(GH_RED[1])
    for name, body in {
        "gh": f'#!/bin/sh\ncat "{gh_out}"\n',
        "buzz": f'#!/bin/sh\necho \'{SEND_OK[1]}\'\n',
    }.items():
        p = tmp_path / name
        p.write_text(body)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "stopgate.toml").write_text(
        'timeout_minutes = 30\n'
        '[ci]\nenabled = true\nbranch = "main"\n'
        f'[approval]\nenabled = true\nchannel = "chan"\nbuzz_bin = "{tmp_path}/buzz"\n'
    )
    src_dir = os.path.dirname(os.path.dirname(os.path.dirname(sg.__file__)))
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
           "STOPGATE_CONFIG": str(tmp_path / "stopgate.toml"),
           "PYTHONPATH": src_dir}
    proc = subprocess.Popen([sys.executable, "-m", "hivepack.stopgate.server"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, env=env)
    rid = iter(range(1, 100))

    def rpc(method, params=None):
        start = time.monotonic()
        i = next(rid)
        proc.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}) + "\n")
        proc.stdin.flush()
        resp = json.loads(proc.stdout.readline())
        assert time.monotonic() - start < 2.5, "hook exceeded buzz-agent's timeout"
        assert resp["id"] == i
        return resp["result"]

    rpc.gh_out = gh_out
    yield rpc
    proc.kill()


def hook_text(result):
    assert result["isError"] is False
    return result["content"][0]["text"]


def test_contract_stop_objects_then_releases(stdio_server):
    rpc = stdio_server
    init = rpc("initialize", {"protocolVersion": "2025-06-18"})
    assert init["serverInfo"]["name"] == "stopgate"
    tools = {t["name"] for t in rpc("tools/list")["tools"]}
    assert {"_Stop", "_PostCompact", "send_message"} <= tools

    # red CI → objection
    out = hook_text(rpc("tools/call", {"name": "_Stop", "arguments": {}}))
    assert "ci gate" in out
    # CI goes green → next _Stop posts the approval request and objects
    rpc.gh_out.write_text(GH_GREEN[1])
    out = hook_text(rpc("tools/call", {"name": "_Stop", "arguments": {}}))
    assert "approval gate" in out and "e" * 64 in out
    # fake buzz now reports a 👍 on any reactions get → allowed to stop
    fake_buzz = rpc.gh_out.parent / "buzz"
    fake_buzz.write_text(
        "#!/bin/sh\necho '" +
        json.dumps({"reactions": [{"count": 1, "emoji": "👍", "pubkeys": ["h"]}]}) + "'\n")
    out = hook_text(rpc("tools/call", {"name": "_Stop", "arguments": {}}))
    assert out == ""
