"""branchtheater parsing + poll loop against a stubbed buzz CLI."""

import json

from hivepack import branchtheater as bt

PATCH = """From eda65340 Mon Sep 17 00:00:00 2001
From: HivePack Demo <demo@hivepack.local>
Date: Sat, 1 Aug 2026 00:59:33 -0400
Subject: [PATCH] feat: expand hello, add goodbye

---
 demo.py | 5 ++++-
 1 file changed, 4 insertions(+), 1 deletion(-)

diff --git a/demo.py b/demo.py
index 1111111..2222222 100644
--- a/demo.py
+++ b/demo.py
@@ -1,2 +1,5 @@
 def hello():
-    return "hive"
+    return "hive, world"
+
+def goodbye():
+    return "bye"
"""


def test_diffstat_counts_files_and_lines():
    files, plus, minus = bt.diffstat(PATCH)
    assert files == ["demo.py"]
    assert (plus, minus) == (4, 1)


def test_patch_meta_strips_patch_prefix():
    meta = bt.patch_meta(PATCH)
    assert meta["subject"] == "feat: expand hello, add goodbye"
    assert meta["author"] == "HivePack Demo"


def test_patch_card_layout():
    card = bt.build_card("Patch", "hivepack-demo", {"id": "abcd1234ffff", "content": PATCH})
    assert "🎭 **Patch** · `hivepack-demo` — feat: expand hello, add goodbye" in card
    assert "1 file(s) · +4 −1 · by HivePack Demo" in card
    assert "`demo.py`" in card
    assert "`event abcd1234`" in card


def test_issue_card_prefers_subject_tag():
    card = bt.build_card("Issue", "hivepack-demo", {
        "id": "beef0000", "content": "long body text",
        "tags": [["subject", "Bot posts twice"]],
    })
    assert "🎭 **Issue** · `hivepack-demo` — Bot posts twice" in card


def test_issue_card_falls_back_to_first_line():
    card = bt.build_card("Issue", "hivepack-demo", {"id": "beef0000", "content": "\nBot posts twice\ndetails"})
    assert "🎭 **Issue** · `hivepack-demo` — Bot posts twice" in card


def test_poll_once_posts_new_events_only(monkeypatch):
    posted = []

    def fake_run_buzz(args, env, *, stdin=None):
        if args[0] == "patches" and args[1] == "list":
            return 0, json.dumps([
                {"id": "e1", "kind": 1617, "content": PATCH, "created_at": 2},
                {"id": "e0", "kind": 1617, "content": PATCH, "created_at": 1},
            ]), ""
        if args[:2] == ["pr", "list"] or args[:2] == ["issues", "list"]:
            return 0, "[]", ""
        if args[:2] == ["messages", "send"]:
            posted.append(stdin)
            return 0, json.dumps({"accepted": True, "event_id": f"m{len(posted)}"}), ""
        raise AssertionError(f"unexpected buzz call: {args}")

    monkeypatch.setattr(bt, "run_buzz", fake_run_buzz)
    state = {"seen": {"e0": {"kind": 1617, "msg": "old"}}}
    log = bt.poll_once({}, "chan-uuid", [("f" * 64, "hivepack-demo")], state)
    # e0 already seen -> exactly one card, for e1.
    assert len(posted) == 1
    assert "feat: expand hello" in posted[0]
    assert state["seen"]["e1"]["msg"] == "m1"
    assert any("card patch e1" in line for line in log)


def test_poll_once_survives_surface_errors(monkeypatch):
    def fake_run_buzz(args, env, *, stdin=None):
        if args[0] == "patches":
            return 2, "", "relay down"
        return 0, "[]", ""

    monkeypatch.setattr(bt, "run_buzz", fake_run_buzz)
    state = {}
    log = bt.poll_once({}, "chan-uuid", [("f" * 64, "demo")], state)
    assert any("WARN patches list" in line for line in log)
