"""Journal bridge (Heptabase journal -> Obsidian daily notes) on a temp vault.

sync.py is imported with a throwaway both-backend config; heptabase CLI calls
are monkeypatched, so no real vault or Heptabase is touched.
"""
import datetime
import json
import os
import sys
import tempfile
import unittest

REPO = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
sys.path.insert(0, os.path.join(REPO, "skills", "_shared"))
sys.path.insert(0, os.path.join(REPO, "skills", "obsidian-sync"))

EMPTY_DOC = {"type": "doc", "content": [{"type": "paragraph", "attrs": {"id": None}}]}


def para_doc(text):
    return {"type": "doc", "content": [
        {"type": "paragraph", "attrs": {"id": None},
         "content": [{"type": "text", "text": text}]}]}


def file_doc(text, fid):
    """A doc with a paragraph and a local file (image) node."""
    return {"type": "doc", "content": [
        {"type": "paragraph", "attrs": {"id": None},
         "content": [{"type": "text", "text": text}]},
        {"type": "file", "attrs": {"id": None, "fileId": fid}}]}


def load_sync(tmp):
    cfg = {"backend": "both",
           "heptabase": {"workspace_id": "0" * 8,
                         "collections": {"papers": {"tag_id": "0" * 36}}},
           "obsidian": {"vault": tmp, "folders": {"papers": "Papers"},
                        "journal": {"enabled": True, "days": 3}}}
    cfg_path = os.path.join(tmp, "config.json")
    json.dump(cfg, open(cfg_path, "w"))
    os.environ["RESEARCH_CARDS_CONFIG"] = cfg_path
    for m in ("sync", "hbconfig", "backend", "md2pm", "pmmd"):
        sys.modules.pop(m, None)
    import sync
    return sync


class TestJournalBridge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rc-test-journal-")
        self._old_env = os.environ.get("RESEARCH_CARDS_CONFIG")
        self.sync = load_sync(self.tmp)

    def tearDown(self):
        # env isolation: this key outranks HEPTABASE_CARDS_CONFIG, so a
        # leftover would poison other tests' config loading
        if self._old_env is None:
            os.environ.pop("RESEARCH_CARDS_CONFIG", None)
        else:
            os.environ["RESEARCH_CARDS_CONFIG"] = self._old_env
        sys.modules.pop("sync", None)
        # deterministic dates
        self.today = datetime.date(2026, 7, 8)

    def _run(self, journals, state=None, dry=False, file_export=None,
             count_renders=False, rebuild=False):
        """journals: date -> PM doc; missing dates read as empty docs.
        file_export: callable(fid, out_dir) -> filename, or raises.
        count_renders: wraps render_journal with a call counter
        (self.render_calls)."""
        sync = self.sync

        def fake_cli(*args, **kw):
            if args[0] == "file" and args[1] == "export":
                if file_export is None:
                    raise AssertionError("unexpected file export in this test")
                name = file_export(args[2], args[4])
                return {"filename": name, "mimeType": "image/png"}
            assert args[0] == "journal" and args[1] == "read"
            date = args[2]
            doc = journals.get(date, EMPTY_DOC)
            return {"date": date, "title": date,
                    "content": json.dumps(doc),
                    "contentMd5": "md5-" + str(hash(json.dumps(doc)) % 10**8)}

        import re as _re

        class R:  # link resolver stub: only local-file embeds are resolved
            in_set = {}
            titles = {}

            def resolve(self, md, self_id, files, anchors=None):
                return _re.sub(
                    r"%%HEPTA-LOCALFILE:([0-9a-f-]{36})%%",
                    lambda m: (f"![[{files[m.group(1)]}]]"
                               if m.group(1) in files else ""), md)

        orig_cli, orig_today = sync.cli, sync.datetime.date
        orig_render, orig_rebuild = sync.render_journal, sync.REBUILD
        sync.cli = fake_cli
        sync.REBUILD = rebuild
        self.render_calls = 0
        if count_renders:
            def counting(*a, **kw):
                self.render_calls += 1
                return orig_render(*a, **kw)
            sync.render_journal = counting

        class FixedDate(datetime.date):
            @classmethod
            def today(cls):
                return datetime.date(2026, 7, 8)
        sync.datetime.date = FixedDate
        try:
            st = state if state is not None else {"cards": {}, "files": {},
                                                  "titles": {}}
            sync.report["journals"].clear()
            sync.report["conflicts"].clear()
            sync.report["errors"].clear()
            sync.sync_journals(st, R(), dry)
            return st
        finally:
            sync.cli = orig_cli
            sync.datetime.date = orig_today
            sync.render_journal = orig_render
            sync.REBUILD = orig_rebuild

    def note(self, date):
        return os.path.join(self.tmp, f"{date}.md")

    def read(self, date):
        return open(self.note(date), encoding="utf-8").read()

    def test_create_and_content(self):
        self._run({"2026-07-08": para_doc("hello journal")})
        text = self.read("2026-07-08")
        self.assertIn(self.sync.J_START, text)
        self.assertIn("hello journal", text)
        self.assertIn(self.sync.J_END, text)
        # empty days with no existing note are not created
        self.assertFalse(os.path.exists(self.note("2026-07-07")))

    def test_user_content_preserved(self):
        with open(self.note("2026-07-08"), "w") as f:
            f.write("my handwritten idea\n")
        self._run({"2026-07-08": para_doc("from heptabase")})
        text = self.read("2026-07-08")
        self.assertIn("my handwritten idea", text)
        self.assertIn("from heptabase", text)
        # managed block sits above the user content
        self.assertLess(text.index(self.sync.J_END),
                        text.index("my handwritten idea"))

    def test_incremental_skip_and_update(self):
        st = self._run({"2026-07-08": para_doc("v1")}, count_renders=True)
        self.assertEqual(self.render_calls, 1)
        day = st["journals"]["2026-07-08"]
        self.assertIn("md5", day)
        self.assertIn("rd", day)          # render-input digest is part of the key
        self.assertTrue(day["managed"])
        mtime = os.path.getmtime(self.note("2026-07-08"))
        st = self._run({"2026-07-08": para_doc("v1")}, state=st,
                       count_renders=True)
        self.assertEqual(self.render_calls, 0)   # true fast path: no re-render
        self.assertEqual(os.path.getmtime(self.note("2026-07-08")), mtime)
        st = self._run({"2026-07-08": para_doc("v2")}, state=st)
        self.assertIn("v2", self.read("2026-07-08"))
        self.assertNotIn("v1", self.read("2026-07-08"))

    def test_rebuild_forces_rerender(self):
        st = self._run({"2026-07-08": para_doc("v1")})
        st = self._run({"2026-07-08": para_doc("v1")}, state=st,
                       count_renders=True, rebuild=True)
        self.assertEqual(self.render_calls, 1)

    def test_markers_deleted_after_manage_is_conflict(self):
        # both markers removed by the user AFTER we managed the note: the
        # incremental fast path must not skip it, and we must NOT re-claim
        # (that would duplicate v1 as stale text outside a fresh block)
        st = self._run({"2026-07-08": para_doc("v1")})
        with open(self.note("2026-07-08"), "w") as f:
            f.write("v1 leftover without any markers\n")
        st = self._run({"2026-07-08": para_doc("v1")}, state=st)  # same md5!
        self.assertTrue(any(c["card"] == "journal:2026-07-08"
                            for c in self.sync.report["conflicts"]))
        self.assertNotIn(self.sync.J_START, self.read("2026-07-08"))

    def test_duplicate_markers_conflict(self):
        pair = self.sync.J_START + "\nx\n" + self.sync.J_END + "\n"
        with open(self.note("2026-07-08"), "w") as f:
            f.write(pair + "user text\n" + pair)
        self._run({"2026-07-08": para_doc("y")})
        self.assertTrue(any(c["card"] == "journal:2026-07-08"
                            for c in self.sync.report["conflicts"]))

    def test_frontmatter_preserved_on_claim(self):
        fm = "---\ntags: [daily]\n---\n"
        body = "\n\nuser body after blank lines\n"
        with open(self.note("2026-07-08"), "w") as f:
            f.write(fm + body)
        self._run({"2026-07-08": para_doc("from hepta")})
        text = self.read("2026-07-08")
        self.assertTrue(text.startswith(fm))     # Properties stay at byte 0
        idx = text.index(self.sync.J_START)
        self.assertGreater(idx, 0)
        self.assertTrue(text.endswith(body))     # user bytes byte-exact,
                                                 # leading blank lines included

    def test_user_bytes_outside_block_exact(self):
        st = self._run({"2026-07-08": para_doc("v1")})
        text = self.read("2026-07-08")
        prefix = text.split(self.sync.J_START)[0]
        suffix = "\nafter-block user text\n"
        with open(self.note("2026-07-08"), "a") as f:
            f.write(suffix)
        st = self._run({"2026-07-08": para_doc("v2")}, state=st)
        text2 = self.read("2026-07-08")
        self.assertEqual(text2.split(self.sync.J_START)[0], prefix)
        self.assertTrue(text2.endswith(suffix))

    def test_empty_source_never_claims_existing_note(self):
        with open(self.note("2026-07-08"), "w") as f:
            f.write("pure user note, bridge never touched it\n")
        st = self._run({})   # all days empty
        text = self.read("2026-07-08")
        self.assertNotIn(self.sync.J_START, text)
        self.assertEqual(text, "pure user note, bridge never touched it\n")
        # and the day is checkpointed so it stays cheap
        self.assertIn("2026-07-08", st["journals"])
        # fast path on rerun: nothing rendered, still untouched
        st = self._run({}, state=st, count_renders=True)
        self.assertEqual(self.render_calls, 0)
        self.assertNotIn(self.sync.J_START, self.read("2026-07-08"))

    def test_attachment_failure_not_checkpointed(self):
        def failing_export(fid, out_dir):
            raise RuntimeError("network down")
        st = self._run({"2026-07-08": file_doc("with image", "f" * 36)},
                       file_export=failing_export)
        self.assertNotIn("2026-07-08", st["journals"])   # retries next run
        self.assertTrue(any("journal:2026-07-08" == e["card"]
                            for e in self.sync.report["errors"]))
        # next run with a working export succeeds and checkpoints
        def ok_export(fid, out_dir):
            open(os.path.join(out_dir, "img.png"), "wb").write(b"x")
            return "img.png"
        st = self._run({"2026-07-08": file_doc("with image", "f" * 36)},
                       state=st, file_export=ok_export)
        self.assertIn("2026-07-08", st["journals"])
        self.assertIn("img.png", self.read("2026-07-08"))

    def test_single_day_failure_isolated(self):
        sync = self.sync
        orig = sync.render_journal

        def boom(note, date, *a, **kw):
            if date == "2026-07-07":
                raise RuntimeError("render exploded")
            return orig(note, date, *a, **kw)
        sync.render_journal = boom
        try:
            self._run({"2026-07-08": para_doc("ok day"),
                       "2026-07-07": para_doc("bad day"),
                       "2026-07-06": para_doc("also ok")})
        finally:
            sync.render_journal = orig
        self.assertTrue(os.path.exists(self.note("2026-07-08")))
        self.assertTrue(os.path.exists(self.note("2026-07-06")))
        self.assertTrue(any(e["card"] == "journal:2026-07-07"
                            for e in self.sync.report["errors"]))

    def test_body_with_marker_literal_conflicts(self):
        st = self._run({"2026-07-08": para_doc(
            "evil " + self.sync.J_START + " smuggled")})
        self.assertTrue(any(c["card"] == "journal:2026-07-08"
                            for c in self.sync.report["conflicts"]))
        self.assertFalse(os.path.exists(self.note("2026-07-08")))

    def test_out_of_window_journal_conflict_stays_open(self):
        sync = self.sync
        st = {"cards": {}, "files": {}, "titles": {},
              "journal_window": ["2026-07-08"],
              "conflict_log": {"k1": {"first": "2026-07-01", "resolved": None,
                                      "entry": {"card": "journal:2026-06-01",
                                                "file": "2026-06-01",
                                                "reason": "markers"}}}}
        sync.report["conflicts"].clear()
        # a card conflict absent from this run WOULD resolve; the out-of-window
        # journal one must stay open
        sync.CONFLICT_NOTE = os.path.join(self.tmp, "Sync Conflicts.md")
        sync.update_conflict_log(st)
        self.assertIsNone(st["conflict_log"]["k1"]["resolved"])

    def test_emptied_day_clears_block_keeps_user_text(self):
        st = self._run({"2026-07-08": para_doc("to be removed")})
        with open(self.note("2026-07-08"), "a") as f:
            f.write("user tail\n")
        self._run({}, state=st)  # source day now empty
        text = self.read("2026-07-08")
        self.assertNotIn("to be removed", text)
        self.assertIn("user tail", text)
        self.assertIn(self.sync.J_START, text)  # markers keep the claim

    def test_malformed_markers_conflict(self):
        with open(self.note("2026-07-08"), "w") as f:
            f.write(self.sync.J_START + "\nonly start marker\n")
        self._run({"2026-07-08": para_doc("x")})
        self.assertIn("only start marker", self.read("2026-07-08"))
        self.assertTrue(any(c["card"] == "journal:2026-07-08"
                            for c in self.sync.report["conflicts"]))

    def test_dry_run_writes_nothing(self):
        # a doc WITH an attachment: dry-run must not mkdir/export/rename
        st = self._run({"2026-07-08": file_doc("dry", "f" * 36)}, dry=True,
                       file_export=None)   # any export call would assert
        self.assertFalse(os.path.exists(self.note("2026-07-08")))
        self.assertFalse(os.path.isdir(os.path.join(self.tmp, "attachments")))
        self.assertEqual(st["files"], {})
        self.assertNotIn("2026-07-08", st.get("journals", {}))

    def test_doc_is_empty(self):
        self.assertTrue(self.sync._doc_is_empty(EMPTY_DOC))
        self.assertTrue(self.sync._doc_is_empty({"type": "doc", "content": []}))
        self.assertFalse(self.sync._doc_is_empty(para_doc("x")))


if __name__ == "__main__":
    unittest.main()



class TestJournalHardeningResiduals(unittest.TestCase):
    """0.17.1 fix-round residual findings: inline markers, exists-race,
    disabled-leg window clearing."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rc-test-journal-resid-")
        self._old_env = os.environ.get("RESEARCH_CARDS_CONFIG")
        self.sync = load_sync(self.tmp)

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("RESEARCH_CARDS_CONFIG", None)
        else:
            os.environ["RESEARCH_CARDS_CONFIG"] = self._old_env
        sys.modules.pop("sync", None)

    def test_inline_marker_is_conflict(self):
        sync = self.sync
        p = os.path.join(self.tmp, "2026-07-01.md")
        original = ("prefix " + sync.J_START + " suffix\nuser text\n"
                    + sync.J_END + "\n")
        with open(p, "w", encoding="utf-8") as f:
            f.write(original)
        self.assertEqual(sync.write_managed_block(p, "body", dry=False),
                         "conflict")
        self.assertEqual(open(p, encoding="utf-8").read(), original)

    def test_exists_race_surfaces_as_conflict(self):
        sync = self.sync
        p = os.path.join(self.tmp, "2026-07-02.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write("racing user note\n")
        real_exists = sync.os.path.exists
        sync.os.path.exists = lambda _p: False
        try:
            self.assertEqual(sync.write_managed_block(p, "body", dry=False),
                             "conflict")
        finally:
            sync.os.path.exists = real_exists
        self.assertEqual(open(p, encoding="utf-8").read(),
                         "racing user note\n")

    def test_disabled_journal_clears_window(self):
        sync = self.sync
        sync._cfg["obsidian"]["journal"] = {"enabled": False}
        state = {"journal_window": ["2026-07-01"]}
        sync.sync_journals(state, resolver=None, dry=True)
        self.assertEqual(state["journal_window"], [])
