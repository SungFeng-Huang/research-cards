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

    def _run(self, journals, state=None, dry=False):
        """journals: date -> PM doc; missing dates read as empty docs."""
        sync = self.sync

        def fake_cli(*args, **kw):
            assert args[0] == "journal" and args[1] == "read"
            date = args[2]
            doc = journals.get(date, EMPTY_DOC)
            return {"date": date, "title": date,
                    "content": json.dumps(doc),
                    "contentMd5": "md5-" + str(hash(json.dumps(doc)) % 10**8)}

        class R:  # link resolver stub: journals in tests carry no links
            def resolve(self, md, self_id, files, anchors=None):
                return md

        orig_cli, orig_today = sync.cli, sync.datetime.date
        sync.cli = fake_cli

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
            sync.sync_journals(st, R(), dry)
            return st
        finally:
            sync.cli = orig_cli
            sync.datetime.date = orig_today

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
        st = self._run({"2026-07-08": para_doc("v1")})
        mtime = os.path.getmtime(self.note("2026-07-08"))
        st = self._run({"2026-07-08": para_doc("v1")}, state=st)
        self.assertEqual(os.path.getmtime(self.note("2026-07-08")), mtime)
        st = self._run({"2026-07-08": para_doc("v2")}, state=st)
        self.assertIn("v2", self.read("2026-07-08"))
        self.assertNotIn("v1", self.read("2026-07-08"))

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
        self._run({"2026-07-08": para_doc("dry")}, dry=True)
        self.assertFalse(os.path.exists(self.note("2026-07-08")))

    def test_doc_is_empty(self):
        self.assertTrue(self.sync._doc_is_empty(EMPTY_DOC))
        self.assertTrue(self.sync._doc_is_empty({"type": "doc", "content": []}))
        self.assertFalse(self.sync._doc_is_empty(para_doc("x")))


if __name__ == "__main__":
    unittest.main()
