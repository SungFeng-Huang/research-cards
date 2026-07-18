"""ObsidianBackend behavior on a throwaway temp vault (no Heptabase needed)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "skills", "_shared"))


def make_backend(tmp):
    cfg = {"backend": "obsidian",
           "obsidian": {"vault": tmp,
                        "folders": {"papers": "Papers", "overviews": "Overviews"}}}
    cfg_path = os.path.join(tmp, "config.json")
    json.dump(cfg, open(cfg_path, "w"))
    os.environ["HEPTABASE_CARDS_CONFIG"] = cfg_path
    for m in ("hbconfig", "backend", "md2pm", "pmmd"):
        sys.modules.pop(m, None)
    import backend
    return backend.ObsidianBackend(backend.hbconfig.load_config())


class TestObsidianBackend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hbcards-test-vault-")
        self.be = make_backend(self.tmp)

    def test_create_read_props_roundtrip(self):
        cid = self.be.create_card("papers", "測試: A/B?", "內文。",
                                  {"Tasks": ["TTS"], "Status": "TODO"})
        self.assertEqual(cid, "Papers/測試- A-B")  # sanitized filename
        card = self.be.read_card(cid)
        self.assertEqual(card.title, "測試: A/B?")
        self.assertEqual(card.props["tasks"], ["TTS"])
        self.be.set_props(cid, {"Status": "Done"})
        self.assertEqual(self.be.read_card(cid).props["status"], "Done")

    def test_doc_roundtrip_stable_and_title_synthetic(self):
        cid = self.be.create_card("papers", "T", "## 節\n\n- ⏵ 摘要\n    內容。")
        ver, doc = self.be.read_doc(cid)
        self.assertEqual(doc["content"][0]["type"], "heading")  # synthetic H1
        self.be.save_doc(cid, ver, doc)  # no-op save
        ver2, _ = self.be.read_doc(cid)
        self.assertEqual(ver, ver2)

    def test_save_doc_optimistic_lock(self):
        cid = self.be.create_card("papers", "T2", "x")
        _, doc = self.be.read_doc(cid)
        with self.assertRaises(RuntimeError):
            self.be.save_doc(cid, "bogus-hash", doc)

    def test_path_guard_rejects_escape(self):
        for bad in ("../outside", "/etc/passwd", "Papers/../../x"):
            with self.assertRaises(ValueError, msg=bad):
                self.be._path(bad)

    def test_wikilink_resolution_to_mentions(self):
        self.be.create_card("papers", "目標卡", "x")
        cid = self.be.create_card("overviews", "總覽", "涵蓋 [[目標卡]] 一篇。")
        _, doc = self.be.read_doc(cid)
        mentions = []
        def walk(n):
            if n.get("type") == "card":
                mentions.append(n["attrs"]["cardId"])
            for c in n.get("content") or []:
                walk(c)
        walk(doc)
        self.assertEqual(mentions, ["Papers/目標卡"])

    def test_journal_append_and_doc(self):
        self.be.journal_append("2026-01-01", "第一筆")
        ver, doc = self.be.journal_read_doc("2026-01-01")
        self.be.journal_save_doc("2026-01-01", ver, doc)
        self.assertIn("第一筆", open(os.path.join(self.tmp, "2026-01-01.md")).read())


class TestListTodoExclusionVisibility(unittest.TestCase):
    def test_excluded_by_filter_counted(self):
        import tempfile, subprocess, sys as _sys
        tmp = tempfile.mkdtemp(prefix="hbcards-listtodo-")
        cfg = {"backend": "obsidian",
               "obsidian": {"vault": tmp, "folders": {"papers": "Papers"}}}
        cp = os.path.join(tmp, "config.json")
        json.dump(cfg, open(cp, "w"))
        env = dict(os.environ, HEPTABASE_CARDS_CONFIG=cp)
        env.pop("RESEARCH_CARDS_CONFIG", None)
        code = """
import sys, os, json
sys.path.insert(0, %r); sys.path.insert(0, %r)
import backend, rewrite_lib as L
be = backend.get_backend()
be.create_card("papers", "AX Paper", "內文", {"Source Type": "alphaXiv"})
be.create_card("papers", "Hand Note", "內文", {"Source Type": "Note"})
r = L.list_todo()
print(json.dumps({"todo": len(r["todo"]), "excluded": r["excluded_by_filter"]}))
""" % (os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "skills", "card-rewrite"),
       os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "skills", "_shared"))
        r = subprocess.run([_sys.executable, "-c", code], env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        out = json.loads(r.stdout.splitlines()[-1])
        self.assertEqual(out, {"todo": 1, "excluded": 1})
        self.assertIn("未列入本清單", r.stderr)


class TestSyncCollectionsGuard(unittest.TestCase):
    """sync.py must skip collection entries without a usable tag_id (e.g. the
    example's projects entry, which exists as project-direction metadata) —
    importing it with such a config used to KeyError."""

    def test_import_skips_tagless_collections(self):
        import subprocess, sys as _sys, tempfile
        tmp = tempfile.mkdtemp(prefix="hbcards-collguard-")
        cfg = {"backend": "both",
               "obsidian": {"vault": tmp, "folders": {"papers": "Papers"}},
               "heptabase": {"workspace_id": "w",
                             "collections": {
                                 "papers": {"tag_id": "aaaa-bbbb"},
                                 "projects": {"hub_card": "<uuid>", "tag_name": "project"},
                                 "guides": {"tag_id": "<tag-uuid>"}}}}
        cp = os.path.join(tmp, "config.json")
        json.dump(cfg, open(cp, "w"))
        env = dict(os.environ, HEPTABASE_CARDS_CONFIG=cp)
        env.pop("RESEARCH_CARDS_CONFIG", None)
        sync_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "skills", "heptabase-sync")
        r = subprocess.run(
            [_sys.executable, "-c",
             "import sync; print([c['key'] for c in sync.COLLECTIONS])"],
            cwd=sync_dir, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertIn("['papers']", r.stdout)


if __name__ == "__main__":
    unittest.main()
