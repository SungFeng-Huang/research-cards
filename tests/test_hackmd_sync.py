"""hackmd-sync: link rewriting, incremental skip / conflict logic on a
mocked hackmd-cli and a temp-vault obsidian backend. No network."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
sys.path.insert(0, os.path.join(REPO, "skills", "_shared"))


def load_hackmd_sync():
    """Load skills/hackmd-sync/sync.py under a NON-colliding module name.
    heptabase-sync also ships a `sync.py` whose module-level guard sys.exit()s
    outside backend='both' — a bare `import sync` here can grab that one via
    sys.path pollution and kill the whole unittest process."""
    import importlib.util
    for m in ("hbconfig", "backend", "pmmd", "md2pm"):
        sys.modules.pop(m, None)
    spec = importlib.util.spec_from_file_location(
        "hackmd_sync_under_test",
        os.path.join(REPO, "skills", "hackmd-sync", "sync.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

UUID = "12345678-1234-1234-1234-123456789abc"


class TestRewriteLinks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global S
        cls.tmp = Path(tempfile.mkdtemp(prefix="rc-test-hackmd-"))
        cfg = cls.tmp / "config.json"
        cfg.write_text(json.dumps({"obsidian": {"vault": str(cls.tmp)}}))
        cls._env = os.environ.get("RESEARCH_CARDS_CONFIG")
        os.environ["RESEARCH_CARDS_CONFIG"] = str(cfg)
        S = load_hackmd_sync()

    @classmethod
    def tearDownClass(cls):
        if cls._env is None:
            os.environ.pop("RESEARCH_CARDS_CONFIG", None)
        else:
            os.environ["RESEARCH_CARDS_CONFIG"] = cls._env

    def test_mirrored_wikilink_becomes_note_link(self):
        md = "見 [[Tokenizer 總覽]] 與 [[別卡|別名]]。"
        out = S.rewrite_links(md, {"Tokenizer 總覽": "nId123"}, {})
        self.assertIn("[Tokenizer 總覽](https://hackmd.io/nId123)", out)
        self.assertIn("別名", out)               # unmirrored → plain label
        self.assertNotIn("[[", out)

    def test_unmirrored_mention_plain_title_not_none_link(self):
        md = f"見 %%HEPTA-CARD:{UUID}%%"
        out = S.rewrite_links(md, {}, {UUID: {"note_id": None, "title": "未鏡像卡"}})
        self.assertIn("未鏡像卡", out)
        self.assertNotIn("hackmd.io/None", out)
        self.assertNotIn("](", out)

    def test_heptabase_urls_rewritten_or_dropped(self):
        md = (f"[別名A](https://app.heptabase.com/ws1/card/{UUID}) 與 "
              f"[別名B](https://app.heptabase.com/ws1/card/99999999-9999-4999-8999-999999999999)")
        out = S.rewrite_links(md, {}, {UUID: {"note_id": "nZ", "title": "A"}})
        self.assertIn("[別名A](https://hackmd.io/nZ)", out)
        self.assertNotIn("heptabase.com", out)
        self.assertIn("別名B", out)

    def test_mention_placeholder(self):
        md = f"參考 %%HEPTA-CARD:{UUID}%% 的做法"
        out = S.rewrite_links(md, {}, {UUID: {"note_id": "nX", "title": "那張卡"}})
        self.assertIn("[那張卡](https://hackmd.io/nX)", out)
        out2 = S.rewrite_links(md, {}, {})
        self.assertNotIn("%%HEPTA-CARD", out2)   # unknown mention drops cleanly


class TestSyncFlow(unittest.TestCase):
    """Drive sync() against a temp obsidian vault with hackmd-cli mocked."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rc-test-hackmd-flow-"))
        (self.tmp / "Overviews").mkdir()
        (self.tmp / "Overviews" / "A 卡.md").write_text(
            "---\nheptabase_id: aaaa\n---\n# A 卡\n\n內容一\n", encoding="utf-8")
        cfg = {"backend": "obsidian",
               "obsidian": {"vault": str(self.tmp),
                            "folders": {"overviews": "Overviews"}},
               "hackmd": {"collections": {"overviews": {"folder_id": "F1"}}}}
        cfg_path = self.tmp / "config.json"
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False))
        self._env = {k: os.environ.get(k) for k in
                     ("RESEARCH_CARDS_CONFIG", "HEPTABASE_CARDS_CONFIG")}
        os.environ["RESEARCH_CARDS_CONFIG"] = str(cfg_path)
        os.environ.pop("HEPTABASE_CARDS_CONFIG", None)
        global S
        S = load_hackmd_sync()
        S.STATE_PATH = str(self.tmp / "hackmd-state.json")
        self.calls, self.notes, self.nid_seq = [], {}, 0

        def fake_api(method, path, body=None, timeout=60):
            self.calls.append((method, path, body))
            if method == "GET" and path == "/notes":
                return [{"id": n, "lastChangedAt": v["lastChangedAt"],
                         "readPermission": v["readPermission"],
                         "title": v.get("title"),
                         "parentFolderId": v.get("folder"),
                         "content": v["content"]}
                        for n, v in self.notes.items()]
            if method == "GET" and path.startswith("/notes/"):
                nid = path.split("/")[-1]
                v = self.notes[nid]
                if getattr(self, "on_note_get", None):
                    self.on_note_get(nid)
                return {"id": nid, "lastChangedAt": v["lastChangedAt"],
                        "readPermission": v["readPermission"],
                        "writePermission": v.get("writePermission", "owner"),
                        "content": v["content"]}
            if method == "DELETE":
                nid = path.split("/")[-1]
                self.notes.pop(nid, None)
                return {}
            if method == "PATCH":
                nid = path.split("/")[-1]
                if "content" in (body or {}):
                    self.notes[nid]["content"] = body["content"]
                    self.notes[nid]["lastChangedAt"] += 1
                if "readPermission" in (body or {}):
                    self.notes[nid]["readPermission"] = body["readPermission"]
                return {}
            raise AssertionError((method, path))

        def fake_create(title, content, folder_id, cfg, cc=None):
            self.nid_seq += 1
            nid = f"note-{self.nid_seq}"
            # the real API silently ignores invalid permission values and
            # defaults to owner — simulate that so the declarative-permission
            # pass has drift to correct; record what create WOULD have sent
            # so per-collection wiring is assertable
            self.notes[nid] = {"content": content,
                               "lastChangedAt": 100 + self.nid_seq,
                               "readPermission": "owner",
                               "writePermission": "owner", "title": title,
                               "created_read": S.perm(cfg, "read_permission",
                                                      "owner", cc),
                               "folder": folder_id}
            return nid

        S.api = self._fake_api = fake_api
        S.note_create = self._fake_create = fake_create
        S.BASE_DIR = str(self.tmp / "hackmd-base")

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for m in ("hbconfig", "backend"):
            sys.modules.pop(m, None)

    def test_create_then_skip_then_conflict(self):
        rep = S.sync()
        self.assertEqual(len(rep["created"]), 1)
        # unchanged source + untouched remote → skip
        rep = S.sync()
        self.assertEqual(rep["skipped"], 1)
        self.assertFalse(rep["conflicts"])
        # remote edited (lastChangedAt moved) + source changed → conflict, no overwrite
        (self.tmp / "Overviews" / "A 卡.md").write_text(
            "---\nheptabase_id: aaaa\n---\n# A 卡\n\n內容二\n", encoding="utf-8")
        nid = next(iter(self.notes))
        before = self.notes[nid]["content"]
        self.notes[nid]["lastChangedAt"] += 500     # simulate a manual edit
        rep = S.sync()
        self.assertEqual(len(rep["conflicts"]), 1)
        self.assertFalse(rep["updated"])
        self.assertEqual(self.notes[nid]["content"], before)

    def test_declarative_read_permission_corrects_drift(self):
        # fixture config sets an explicit non-default so the pass has drift
        # to correct against the mocked API default (owner)
        import json as _j
        cfgp = self.tmp / "config.json"
        c = _j.loads(cfgp.read_text()); c["hackmd"]["read_permission"] = "signed_in"
        cfgp.write_text(_j.dumps(c, ensure_ascii=False))
        global S
        S = load_hackmd_sync(); S.STATE_PATH = str(self.tmp / "hackmd-state.json")
        S.api, S.note_create = self._fake_api, self._fake_create
        S.sync()
        nid = next(iter(self.notes))
        self.assertEqual(self.notes[nid]["readPermission"], "signed_in")

    def test_first_run_carries_interlinks(self):
        (self.tmp / "Overviews" / "B 卡.md").write_text(
            "---\nheptabase_id: bbbb\n---\n# B 卡\n\n見 [[A 卡]]\n", encoding="utf-8")
        rep = S.sync()
        self.assertEqual(len(rep["created"]), 2)
        b = next(v for v in self.notes.values() if v["title"] == "B 卡")
        self.assertIn("](https://hackmd.io/note-", b["content"])

    def test_source_change_updates(self):
        S.sync()
        (self.tmp / "Overviews" / "A 卡.md").write_text(
            "---\nheptabase_id: aaaa\n---\n# A 卡\n\n內容二\n", encoding="utf-8")
        rep = S.sync()
        self.assertEqual(len(rep["updated"]), 1)
        nid = next(iter(self.notes))
        self.assertIn("內容二", self.notes[nid]["content"])

    def test_dry_run_writes_nothing(self):
        rep = S.sync(dry=True)
        self.assertEqual(len(rep["created"]), 1)
        self.assertFalse(os.path.exists(S.STATE_PATH))
        self.assertFalse(self.notes)                 # nothing actually created

    def _reload_with_config(self, mutate):
        import json as _j
        cfgp = self.tmp / "config.json"
        c = _j.loads(cfgp.read_text()); mutate(c)
        cfgp.write_text(_j.dumps(c, ensure_ascii=False))
        global S
        S = load_hackmd_sync(); S.STATE_PATH = str(self.tmp / "hackmd-state.json")
        S.api, S.note_create = self._fake_api, self._fake_create
        S.BASE_DIR = str(self.tmp / "hackmd-base")

    def test_per_collection_permission_override(self):
        # global signed_in; the projects-like collection pins itself private
        (self.tmp / "Secret").mkdir()
        (self.tmp / "Secret" / "P 卡.md").write_text(
            "---\nheptabase_id: pppp\n---\n# P 卡\n\n機密\n", encoding="utf-8")

        def mutate(c):
            c["obsidian"]["folders"]["secret"] = "Secret"
            c["hackmd"]["read_permission"] = "signed_in"
            c["hackmd"]["collections"]["secret"] = {
                "folder_id": "F2", "read_permission": "owner"}
        self._reload_with_config(mutate)
        S.sync()
        by_title = {v["title"]: v for v in self.notes.values()}
        # create-time wiring: collection override reaches note_create
        self.assertEqual(by_title["A 卡"]["created_read"], "signed_in")
        self.assertEqual(by_title["P 卡"]["created_read"], "owner")
        # declarative pass: fake created both as owner → only the global-
        # default card drifts and is corrected; the pinned one stays owner
        self.assertEqual(by_title["A 卡"]["readPermission"], "signed_in")
        self.assertEqual(by_title["P 卡"]["readPermission"], "owner")

    def test_conflict_still_migrates_permission(self):
        S.sync()                                     # global default = owner
        nid = next(iter(self.notes))
        (self.tmp / "Overviews" / "A 卡.md").write_text(
            "---\nheptabase_id: aaaa\n---\n# A 卡\n\n內容二\n", encoding="utf-8")
        self.notes[nid]["lastChangedAt"] += 500      # remote manual edit
        self.notes[nid]["readPermission"] = "guest"  # and someone opened it up
        before = self.notes[nid]["content"]
        rep = S.sync()
        self.assertEqual(len(rep["conflicts"]), 1)
        self.assertEqual(self.notes[nid]["content"], before)   # content frozen
        self.assertEqual(self.notes[nid]["readPermission"], "owner")  # perm migrated

    def test_perm_collection_override_validated(self):
        cfg = {"hackmd": {"read_permission": "signed_in"}}
        self.assertEqual(S.perm(cfg, "read_permission", "owner",
                                {"read_permission": "owner"}), "owner")
        self.assertEqual(S.perm(cfg, "read_permission", "owner", {}), "signed_in")
        with self.assertRaises(SystemExit):
            S.perm(cfg, "read_permission", "owner", {"read_permission": "everyone"})

    # ── level 2: write-back ──────────────────────────────────────────────
    HEPTA_URL = ("https://app.heptabase.com/w/card/"
                 "99999999-9999-4999-8999-999999999999")

    def _wb_fixture(self, mutate_cfg=None):
        (self.tmp / "Overviews" / "W 卡.md").write_text(
            "---\nheptabase_id: wwww\n---\n段落一。\n\n"
            f"段落二含[舊連結]({self.HEPTA_URL})。\n", encoding="utf-8")
        def mutate(c):
            c["hackmd"]["write_back"] = True
            if mutate_cfg:
                mutate_cfg(c)
        self._reload_with_config(mutate)
        S.sync()                                 # forward pass + base snapshots
        nid = next(n for n, v in self.notes.items() if v["title"] == "W 卡")
        return nid

    def test_reverse_links(self):
        m = {"n1": {"card": "c1", "title": "目標卡"}}
        self.assertEqual(S.reverse_links("見 [目標卡](https://hackmd.io/n1)", m),
                         "見 [[目標卡]]")
        self.assertEqual(S.reverse_links("見 [別名](https://hackmd.io/n1)", m),
                         "見 [[目標卡|別名]]")
        foreign = "見 [外部](https://hackmd.io/zzz) 與 [站外](https://x.io/a)"
        self.assertEqual(S.reverse_links(foreign, m), foreign)

    def test_write_back_edited_paragraph(self):
        nid = self._wb_fixture()
        edited = self.notes[nid]["content"].replace("段落一。", "段落一（改）。")
        self.notes[nid]["content"] = edited
        self.notes[nid]["lastChangedAt"] += 500
        rep = S.sync()
        self.assertEqual(len(rep["written_back"]), 1)
        self.assertFalse(rep["conflicts"])
        body = (self.tmp / "Overviews" / "W 卡.md").read_text()
        self.assertIn("段落一（改）。", body)
        self.assertIn(self.HEPTA_URL, body)      # untouched paragraph intact
        self.assertEqual(self.notes[nid]["content"], edited)  # note not clobbered
        rep = S.sync()                           # converged
        self.assertFalse(rep["written_back"])
        self.assertFalse(rep["conflicts"])

    def test_write_back_three_way_conflict(self):
        nid = self._wb_fixture()
        self.notes[nid]["content"] = \
            self.notes[nid]["content"].replace("段落一。", "遠端改。")
        self.notes[nid]["lastChangedAt"] += 500
        p = self.tmp / "Overviews" / "W 卡.md"
        p.write_text(p.read_text().replace("段落一。", "本地改。"),
                     encoding="utf-8")
        rep = S.sync()
        self.assertFalse(rep["written_back"])
        self.assertEqual(len(rep["conflicts"]), 1)
        self.assertIn("真三方衝突", rep["conflicts"][0]["why"])
        self.assertIn("本地改。", p.read_text())          # vault untouched

    def test_write_back_gate_shared_writable(self):
        nid = self._wb_fixture(
            lambda c: c["hackmd"]["collections"]["overviews"].update(
                {"write_permission": "signed_in"}))
        self.notes[nid]["content"] = \
            self.notes[nid]["content"].replace("段落一。", "路人改。")
        self.notes[nid]["lastChangedAt"] += 500
        rep = S.sync()
        self.assertFalse(rep["written_back"])    # shared-writable → never back
        self.assertEqual(len(rep["conflicts"]), 1)
        self.assertNotIn("路人改。",
                         (self.tmp / "Overviews" / "W 卡.md").read_text())

    def test_write_back_round_trip_freeze(self):
        nid = self._wb_fixture()
        # an edit that renders differently after reversal ([[X]] of an
        # unmirrored title degrades to plain text) must freeze the card
        self.notes[nid]["content"] = self.notes[nid]["content"].replace(
            "段落一。", "段落一 [[不存在的卡]]。")
        self.notes[nid]["lastChangedAt"] += 500
        rep = S.sync()
        self.assertFalse(rep["written_back"])
        self.assertEqual(len(rep["conflicts"]), 1)
        self.assertIn("round-trip", rep["conflicts"][0]["why"])

    def test_write_back_gate_remote_write_permission(self):
        # config says owner, but the note was opened up ON hackmd.io —
        # the remote's actual writePermission is the authority
        nid = self._wb_fixture()
        self.notes[nid]["writePermission"] = "signed_in"
        self.notes[nid]["content"] = \
            self.notes[nid]["content"].replace("段落一。", "路人改。")
        self.notes[nid]["lastChangedAt"] += 500
        rep = S.sync()
        self.assertFalse(rep["written_back"])
        self.assertEqual(len(rep["conflicts"]), 1)
        self.assertIn("遠端實際寫權限非 owner", rep["conflicts"][0]["why"])
        self.assertNotIn("路人改。",
                         (self.tmp / "Overviews" / "W 卡.md").read_text())

    def test_write_back_degraded_paragraph_freezes(self):
        # editing the paragraph whose vault original holds an unmirrored
        # Heptabase URL (degraded to plain text on HackMD) must freeze
        nid = self._wb_fixture()
        self.notes[nid]["content"] = \
            self.notes[nid]["content"].replace("段落二含", "段落二（改）含")
        self.notes[nid]["lastChangedAt"] += 500
        rep = S.sync()
        self.assertFalse(rep["written_back"])
        self.assertEqual(len(rep["conflicts"]), 1)
        self.assertIn("已降級的連結", rep["conflicts"][0]["why"])
        self.assertIn(self.HEPTA_URL,
                      (self.tmp / "Overviews" / "W 卡.md").read_text())

    def test_write_back_concurrent_vault_edit(self):
        nid = self._wb_fixture()
        self.notes[nid]["content"] = \
            self.notes[nid]["content"].replace("段落一。", "遠端改。")
        self.notes[nid]["lastChangedAt"] += 500
        p = self.tmp / "Overviews" / "W 卡.md"
        def racy(_nid):   # vault edited between src read and save
            p.write_text(p.read_text().replace("段落一。", "並發改。"),
                         encoding="utf-8")
        self.on_note_get = racy
        rep = S.sync()
        self.on_note_get = None
        self.assertFalse(rep["written_back"])
        self.assertEqual(len(rep["conflicts"]), 1)
        self.assertIn("並發改。", p.read_text())   # concurrent edit survives

    def test_no_remote_index_defers_content_update(self):
        S.sync()
        (self.tmp / "Overviews" / "A 卡.md").write_text(
            "---\nheptabase_id: aaaa\n---\n# A 卡\n\n內容二\n", encoding="utf-8")
        real_api = S.api
        def flaky(method, path, body=None, timeout=60):
            if method == "GET" and path == "/notes":
                raise RuntimeError("HTTP Error 429")
            return real_api(method, path, body, timeout)
        S.api = flaky
        nid = next(iter(self.notes))
        before = self.notes[nid]["content"]
        rep = S.sync()
        S.api = real_api
        self.assertFalse(rep["updated"])
        self.assertEqual(self.notes[nid]["content"], before)  # not clobbered
        self.assertTrue(any("remote index 不可用" in e["err"]
                            for e in rep["errors"]))

    def test_state_key_migration_no_duplicates(self):
        S.sync()                                     # state keyed by uuid
        import json as _j
        st = _j.load(open(S.STATE_PATH))
        rec = st["cards"].pop("aaaa")
        st["cards"]["Overviews/A 卡"] = rec          # simulate old vault-id key
        _j.dump(st, open(S.STATE_PATH, "w"))
        rep = S.sync()
        self.assertFalse(rep["created"])             # migrated, not re-created
        st = _j.load(open(S.STATE_PATH))
        self.assertIn("aaaa", st["cards"])
        self.assertNotIn("Overviews/A 卡", st["cards"])

    def test_only_card_accepts_uuid(self):
        rep = S.sync(only_card="aaaa")
        self.assertEqual(len(rep["created"]), 1)

    def test_vanished_source_deletes_only_untouched_notes(self):
        (self.tmp / "Overviews" / "K 卡.md").write_text(
            "---\nheptabase_id: kkkk\n---\n留守\n", encoding="utf-8")
        S.sync()
        nid = next(n for n, v in self.notes.items() if v["title"] == "A 卡")
        os.remove(self.tmp / "Overviews" / "A 卡.md")   # source card gone
        rep = S.sync()
        self.assertEqual(rep["vanished"][0]["action"].split("（")[0], "deleted")
        self.assertNotIn(nid, self.notes)               # remote note deleted
        import json as _j
        st = _j.load(open(S.STATE_PATH))
        self.assertNotIn("aaaa", st["cards"])            # ledger cleaned

    def test_vanished_pass_fails_closed_on_empty_inventory(self):
        (self.tmp / "Overviews" / "B 卡.md").write_text(
            "---\nheptabase_id: bbbb\n---\nB\n", encoding="utf-8")
        S.sync()                                   # ledger has 2 cards
        n_before = set(self.notes)
        # simulate an unmounted vault: the managed folder suddenly empties
        os.remove(self.tmp / "Overviews" / "A 卡.md")
        os.remove(self.tmp / "Overviews" / "B 卡.md")
        rep = S.sync()                             # inventory 0 < 2/2
        self.assertFalse(rep["vanished"])          # pass skipped
        self.assertEqual(set(self.notes), n_before)   # nothing deleted
        self.assertTrue(any("vanished 檢查" in (e.get("err") or "")
                            for e in rep["errors"]))

    def test_vanished_source_keeps_edited_notes(self):
        (self.tmp / "Overviews" / "K 卡.md").write_text(
            "---\nheptabase_id: kkkk\n---\n留守\n", encoding="utf-8")
        S.sync()
        nid = next(n for n, v in self.notes.items() if v["title"] == "A 卡")
        self.notes[nid]["content"] = "有人在 HackMD 端改過"
        os.remove(self.tmp / "Overviews" / "A 卡.md")
        rep = S.sync()
        self.assertTrue(rep["vanished"][0]["action"].startswith("kept"))
        self.assertIn(nid, self.notes)                   # surfaced, not deleted

    def test_folder_of_supports_both_api_generations(self):
        self.assertEqual(S._folder_of({"parentFolderId": "F1"}), "F1")
        self.assertEqual(S._folder_of(
            {"folderPaths": [{"id": "F2", "name": "Papers",
                              "parentId": None}]}), "F2")
        self.assertIsNone(S._folder_of({"folderPaths": []}))
        self.assertIsNone(S._folder_of({}))

    def test_adoption_works_with_folderpaths_schema(self):
        # newer list schema: folderPaths instead of parentFolderId — the
        # regression that blinded adoption and duplicated 300 notes
        real_api = S.api
        def newer_api(method, path, body=None, timeout=60):
            out = real_api(method, path, body, timeout)
            if method == "GET" and path == "/notes":
                for r in out:
                    pf = r.pop("parentFolderId", None)
                    r["folderPaths"] = ([{"id": pf, "name": "?",
                                          "parentId": None}] if pf else [])
            return out
        S.api = newer_api
        S.sync()
        os.remove(S.STATE_PATH)
        nid = next(iter(self.notes))
        self.notes[nid]["content"] = S.PLACEHOLDER
        rep = S.sync()
        S.api = real_api
        self.assertEqual(len(rep["adopted"]), 1)
        self.assertFalse(rep["created"])
        self.assertEqual(len(self.notes), 1)

    def test_book_transform(self):
        md = ("開場說明。\n\n---\n\n## 主題階層\n\n"
              "- [A 卡](https://hackmd.io/n1)　說明文字拖尾\n"
              "    - [B 卡](https://hackmd.io/n2)\n"
              "- [兩連結](https://hackmd.io/n3) 與 [殿後](https://hackmd.io/n4)\n"
              "- [站外](https://x.io/a)\n")
        out = S.book_transform(md, "📚 目錄")
        self.assertTrue(out.startswith("📚 目錄\n===\n"))    # injected title
        self.assertIn("主題階層\n---", out)                  # ## → setext
        self.assertIn("- [A 卡](/n1)\n", out)               # description stripped
        self.assertNotIn("說明文字拖尾", out)
        self.assertIn("](/n2)", out)
        self.assertIn("](/n4)", out)                        # greedy keeps both links
        self.assertIn("https://x.io/a", out)                # foreign untouched
        self.assertIn("\n---\n", out)                       # hr preserved
        # existing H1 becomes the setext title — no double injection
        out2 = S.book_transform("# 我的書\n\n- x\n", "別名")
        self.assertTrue(out2.startswith("我的書\n===\n"))
        self.assertNotIn("別名", out2)

    def test_wikilink_by_filename_resolves(self):
        # card titled with '/' lives in a dash-named file; wikilinks use the
        # FILENAME form and must still become real note links
        (self.tmp / "Overviews" / "X-Y 卡.md").write_text(
            '---\nheptabase_id: xyxy\ntitle: "X/Y 卡"\n---\n內容\n',
            encoding="utf-8")
        (self.tmp / "Overviews" / "A 卡.md").write_text(
            "---\nheptabase_id: aaaa\n---\n# A 卡\n\n見 [[X-Y 卡]]\n",
            encoding="utf-8")
        S.sync()
        a = next(v for v in self.notes.values() if v["title"] == "A 卡")
        self.assertIn("[X-Y 卡](https://hackmd.io/note-", a["content"])
        self.assertNotIn("[[", a["content"])

    def test_book_index_card_renders_as_book(self):
        self._reload_with_config(
            lambda c: c["hackmd"].update({"book_index": "aaaa"}))
        S.sync()
        nid = next(iter(self.notes))
        self.assertTrue(self.notes[nid]["content"].startswith("A 卡\n===\n"))
        rep = S.sync()                              # stable digest → skip
        self.assertEqual(rep["skipped"], 1)

    def test_book_index_accepts_vault_id_and_never_writes_back(self):
        self._reload_with_config(
            lambda c: c["hackmd"].update({"book_index": "Overviews/A 卡",
                                          "write_back": True}))
        S.sync()
        nid = next(iter(self.notes))
        self.assertTrue(self.notes[nid]["content"].startswith("A 卡\n===\n"))
        before_vault = (self.tmp / "Overviews" / "A 卡.md").read_text()
        self.notes[nid]["content"] = \
            self.notes[nid]["content"].replace("內容一", "遠端改")
        self.notes[nid]["lastChangedAt"] += 500
        rep = S.sync()
        self.assertFalse(rep["written_back"])
        self.assertEqual(len(rep["conflicts"]), 1)
        self.assertIn("book 目錄卡不寫回", rep["conflicts"][0]["why"])
        self.assertEqual((self.tmp / "Overviews" / "A 卡.md").read_text(),
                         before_vault)

    def test_quota_streak_aborts_run(self):
        S._429_STREAK[0] = 0
        for _ in range(S._429_STREAK_LIMIT - 1):
            S._note_429(True)
        with self.assertRaises(S.QuotaExhausted):
            S._note_429(True)
        S._429_STREAK[0] = 0
        (self.tmp / "Overviews" / "B 卡.md").write_text(
            "---\nheptabase_id: bbbb\n---\nB 內容\n", encoding="utf-8")
        def broke_create(*a, **k):
            raise S.QuotaExhausted("連續 429")
        S.note_create = broke_create
        rep = S.sync()
        self.assertEqual(rep["aborted"], "連續 429")

    def test_adoption_reclaims_orphans_of_killed_run(self):
        S.sync()                       # a "killed" run: notes exist on HackMD…
        os.remove(S.STATE_PATH)        # …but the ledger was never written
        nid = next(iter(self.notes))   # killed in phase A → still placeholder
        self.notes[nid]["content"] = S.PLACEHOLDER
        rep = S.sync()
        self.assertEqual(len(rep["adopted"]), 1)
        self.assertFalse(rep["created"])
        self.assertEqual(len(self.notes), 1)      # no duplicate note
        self.assertFalse(rep["stray_duplicates"])
        rep = S.sync()                             # adopted card converges
        self.assertEqual(rep["skipped"], 1)

    def test_hand_made_same_title_note_never_adopted(self):
        # a REAL-content unclaimed note with the same title must not be
        # adopted (phase B would overwrite it) — new note created alongside,
        # hand-made one untouched and surfaced
        self.notes["hand"] = {"content": "我手寫的", "lastChangedAt": 7,
                              "readPermission": "owner",
                              "writePermission": "owner", "title": "A 卡",
                              "created_read": "owner", "folder": "F1"}
        rep = S.sync()
        self.assertEqual(len(rep["created"]), 1)
        self.assertFalse(rep["adopted"])
        self.assertEqual(self.notes["hand"]["content"], "我手寫的")
        self.assertEqual([d["note"] for d in rep["stray_duplicates"]], ["hand"])

    def test_state_lock_blocks_second_runner(self):
        fh = S.acquire_state_lock()
        try:
            with self.assertRaises(SystemExit):
                S.sync()
        finally:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_UN)
            fh.close()
        S.sync()                                   # lock released → runs fine

    def test_incremental_state_save_survives_abort(self):
        (self.tmp / "Overviews" / "B 卡.md").write_text(
            "---\nheptabase_id: bbbb\n---\nB 內容\n", encoding="utf-8")
        real_create = S.note_create
        calls = []
        def one_then_quota(*a, **k):
            if calls:
                raise S.QuotaExhausted("連續 429")
            calls.append(1)
            return real_create(*a, **k)
        S.note_create = one_then_quota
        rep = S.sync()
        self.assertTrue(rep["aborted"])
        import json as _j
        st = _j.load(open(S.STATE_PATH))           # ledger written mid-run
        self.assertEqual(len(st["cards"]), 1)

    def test_stray_duplicate_reported_not_deleted(self):
        S.sync()
        self.notes["note-dup"] = {"content": "x", "lastChangedAt": 1,
                                  "readPermission": "owner",
                                  "writePermission": "owner", "title": "A 卡",
                                  "created_read": "owner", "folder": "F1"}
        # fake list endpoint must expose folder for adoption/stray scan
        rep = S.sync()
        self.assertEqual([d["note"] for d in rep["stray_duplicates"]],
                         ["note-dup"])
        self.assertIn("note-dup", self.notes)      # surfaced, not deleted


if __name__ == "__main__":
    unittest.main()
