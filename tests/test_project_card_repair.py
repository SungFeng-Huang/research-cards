"""project-card-repair: the 專案： backref generalisation in append_card, and
repair.py's seal-routing. No live card I/O — rewrite_lib read/save are
monkeypatched; config is a throwaway obsidian mock (repair_card never reads it,
it only guards module import)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
for sub in ("_shared", "card-rewrite", "project-card-log", "project-card-repair"):
    sys.path.insert(0, os.path.join(REPO, "skills", sub))

UUID = "12345678-1234-1234-1234-123456789abc"


def _para(*content):
    return {"type": "paragraph", "attrs": {"id": None}, "content": list(content)}


def _t(s, **marks):
    n = {"type": "text", "text": s}
    if marks:
        n["marks"] = [{"type": k} for k in marks]
    return n


def _card(cid):
    return {"type": "card", "attrs": {"cardId": cid}}


def _mock_config():
    tmp = Path(tempfile.mkdtemp(prefix="rc-test-pcr-"))
    cfg = tmp / "config.json"
    cfg.write_text(json.dumps({"backend": "obsidian",
                               "obsidian": {"vault": str(tmp)}}))
    prev = os.environ.get("RESEARCH_CARDS_CONFIG")
    os.environ["RESEARCH_CARDS_CONFIG"] = str(cfg)
    for m in ("append_card", "rewrite_lib", "hbconfig", "repair"):
        sys.modules.pop(m, None)
    return prev


def _restore_config(prev):
    if prev is None:
        os.environ.pop("RESEARCH_CARDS_CONFIG", None)
    else:
        os.environ["RESEARCH_CARDS_CONFIG"] = prev


class TestBackrefGeneralisation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = _mock_config()
        global AC
        import append_card as AC

    @classmethod
    def tearDownClass(cls):
        _restore_config(cls._env)

    def test_default_marks_ignore_projectref(self):
        # default (母卡： only) must NOT seal a 專案： header — keeps the
        # chain-walk caller in repair_chain.py behaving exactly as before
        n = _para(_t(f"專案：[[card:{UUID}]]　環境：OCI"))
        self.assertEqual(AC.seal_backref_paragraphs([n]), 0)
        self.assertFalse(any(c["type"] == "card" for c in n["content"]))

    def test_projectref_seals_with_marks(self):
        n = _para(_t(f"專案：[[card:{UUID}]]　環境：OCI"))
        got = AC.seal_backref_paragraphs(
            [n], marks=(AC.BACKREF_MARK, AC.PROJECTREF_MARK))
        self.assertEqual(got, 1)
        kinds = [c["type"] for c in n["content"]]
        self.assertEqual(kinds, ["text", "card", "text"])
        self.assertTrue(n["content"][0]["text"].endswith("："))
        self.assertEqual(n["content"][1]["attrs"]["cardId"], UUID)
        self.assertIn("環境", n["content"][2]["text"])

    def test_default_backref_still_works(self):
        n = _para(_t(f"（軸卡 的續卡 2；母卡：[[card:{UUID}]]。）"))
        self.assertEqual(AC.seal_backref_paragraphs([n]), 1)  # 母卡： default

    def test_idempotent_when_card_node_present(self):
        n = _para(_t("專案："), _card(UUID), _t("　環境：OCI"))
        self.assertEqual(AC.seal_backref_paragraphs(
            [n], marks=(AC.BACKREF_MARK, AC.PROJECTREF_MARK)), 0)

    def test_prose_quoting_never_sealed(self):
        # no header mark before the literal → never rewritten
        n = _para(_t(f"參見 [[card:{UUID}]] 一節"))
        self.assertEqual(AC.seal_backref_paragraphs(
            [n], marks=(AC.BACKREF_MARK, AC.PROJECTREF_MARK)), 0)


class TestInlineCardLiterals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = _mock_config()
        global AC
        import append_card as AC

    @classmethod
    def tearDownClass(cls):
        _restore_config(cls._env)

    def test_recursive_multiple_links_preserve_prose_and_marks(self):
        other = "99999999-9999-4999-8999-999999999999"
        paragraph = _para(_t(
            f"承接 [[card:{UUID}]]，也比較 [[card:{other}]]。",
            strong=True))
        nodes = [{"type": "bullet_list_item", "content": [paragraph]}]
        self.assertEqual(
            AC.seal_inline_card_literals(nodes, card_exists=lambda _: True),
            2)
        kids = paragraph["content"]
        self.assertEqual([n["type"] for n in kids],
                         ["text", "card", "text", "card", "text"])
        self.assertEqual(kids[0]["marks"], [{"type": "strong"}])
        self.assertEqual(kids[-1]["marks"], [{"type": "strong"}])

    def test_skips_inline_code_and_code_blocks(self):
        inline = _para(_t(f"範例 [[card:{UUID}]]", code=True))
        block = {"type": "code_block", "content": [
            _t(f"[[card:{UUID}]]")]}
        self.assertEqual(
            AC.seal_inline_card_literals(
                [inline, block], card_exists=lambda _: True),
            0)
        self.assertEqual(inline["content"][0]["type"], "text")
        self.assertEqual(block["content"][0]["type"], "text")

    def test_unreadable_target_stays_literal_and_is_reported(self):
        missing = set()
        paragraph = _para(_t(f"見 [[card:{UUID}]]"))
        self.assertEqual(
            AC.seal_inline_card_literals(
                [paragraph], card_exists=lambda _: False, missing=missing),
            0)
        self.assertEqual(missing, {UUID})
        self.assertIn("[[card:", paragraph["content"][0]["text"])

    def test_idempotent_after_conversion(self):
        paragraph = _para(_t(f"見 [[card:{UUID}]]"))
        self.assertEqual(
            AC.seal_inline_card_literals(
                [paragraph], card_exists=lambda _: True),
            1)
        self.assertEqual(
            AC.seal_inline_card_literals(
                [paragraph], card_exists=lambda _: True),
            0)


class TestRepairRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = _mock_config()
        global repair
        import repair

    @classmethod
    def tearDownClass(cls):
        _restore_config(cls._env)

    def _patch(self, doc):
        saved = {}

        def fake_read(cid):
            return "md5-x", json.loads(json.dumps(doc))

        def fake_save(cid, md5, d):
            saved["cid"] = cid
            saved["doc"] = d

        repair.L.read_card = fake_read
        repair.L.save_card = fake_save
        return saved

    def test_repair_card_seals_projectref_and_saves(self):
        doc = {"type": "doc", "content": [
            _para(_t(f"專案：[[card:{UUID}]]　環境：OCI"))]}
        saved = self._patch(doc)
        r = repair.repair_card("log-1")
        self.assertEqual(r["sealed"], 1)
        self.assertEqual(r["by_kind"].get("backref"), 1)
        self.assertEqual(saved.get("cid"), "log-1")
        kinds = [c["type"] for c in saved["doc"]["content"][0]["content"]]
        self.assertIn("card", kinds)

    def test_repair_card_seals_loglink(self):
        doc = {"type": "doc", "content": [
            _para(_t(f"📎 2026-07-21　[[card:{UUID}]]　摘要"))]}
        self._patch(doc)
        r = repair.repair_card("proj-1")
        self.assertEqual(r["by_kind"].get("loglink"), 1)

    def test_dry_run_does_not_save(self):
        doc = {"type": "doc", "content": [
            _para(_t(f"專案：[[card:{UUID}]]　環境：OCI"))]}
        saved = self._patch(doc)
        r = repair.repair_card("log-2", dry_run=True)
        self.assertEqual(r["sealed"], 1)
        self.assertNotIn("cid", saved)   # dry-run must not save

    def test_sentinel_left_by_default(self):
        doc = {"type": "doc", "content": [
            _para(_t(f"▶ 續卡（本卡已達容量上限）：[[card:{UUID}]]"))]}
        saved = self._patch(doc)
        r = repair.repair_card("entry-1")
        self.assertEqual(r["sealed"], 0)          # sentinel untouched
        self.assertNotIn("cid", saved)

    def test_sentinel_sealed_when_opted_in(self):
        doc = {"type": "doc", "content": [
            _para(_t(f"▶ 續卡（本卡已達容量上限）：[[card:{UUID}]]"))]}
        self._patch(doc)
        r = repair.repair_card("entry-2", include_sentinel=True)
        self.assertEqual(r["by_kind"].get("sentinel"), 1)

    def test_noop_on_plain_card(self):
        doc = {"type": "doc", "content": [_para(_t("just prose, no link"))]}
        saved = self._patch(doc)
        r = repair.repair_card("paper-1")
        self.assertEqual(r["sealed"], 0)
        self.assertNotIn("cid", saved)

    def test_inline_mode_seals_readable_prose_links(self):
        doc = {"type": "doc", "content": [
            _para(_t(f"前情見 [[card:{UUID}]]。"))]}
        saved = self._patch(doc)
        with patch.object(repair, "_card_exists", return_value=True):
            r = repair.repair_card("log-3", include_inline=True)
        self.assertEqual(r["by_kind"].get("inline"), 1)
        self.assertEqual(r["missing_inline_targets"], [])
        self.assertEqual(
            [n["type"] for n in saved["doc"]["content"][0]["content"]],
            ["text", "card", "text"])

    def test_inline_mode_reports_unreadable_target_without_save(self):
        doc = {"type": "doc", "content": [
            _para(_t(f"前情見 [[card:{UUID}]]。"))]}
        saved = self._patch(doc)
        with patch.object(repair, "_card_exists", return_value=False):
            r = repair.repair_card("log-4", include_inline=True)
        self.assertEqual(r["sealed"], 0)
        self.assertEqual(r["missing_inline_targets"], [UUID])
        self.assertNotIn("cid", saved)

    def test_live_snapshot_excludes_trashed_and_paginates(self):
        pages = {
            0: {"results": [{"id": "live-a"}], "total": 2},
            1: {"results": [{"id": "live-b"}], "total": 2},
        }

        def fake_cli(*args):
            self.assertEqual(args[:2], ("card", "list"))
            return pages[int(args[args.index("--offset") + 1])]

        repair._LIVE_CARD_IDS = None
        with patch.object(repair, "_cli", side_effect=fake_cli):
            self.assertTrue(repair._card_exists("live-b"))
            self.assertFalse(repair._card_exists("trashed-c"))
        self.assertEqual(repair._LIVE_CARD_IDS, {"live-a", "live-b"})


class TestScanResolve(unittest.TestCase):
    """scan_target_ids must never silently drop a collection — the progress
    tag is optional in config, and dropping it hides the log→project back-refs
    this skill exists to fix (codex review P1, 2026-07-23)."""

    @classmethod
    def setUpClass(cls):
        cls._env = _mock_config()
        global repair
        import repair

    @classmethod
    def tearDownClass(cls):
        _restore_config(cls._env)

    def _patch_cli(self, tags=None, cards_by_tag=None):
        cards_by_tag = cards_by_tag or {}

        def fake_cli(*args):
            if args[:2] == ("tag", "list"):
                return {"tags": tags or []}
            if args[:2] == ("tag", "cards"):
                return {"cards": cards_by_tag.get(args[2], [])}
            return {}

        repair._cli = fake_cli

    def _hb_id(self, tag_ids=None, tag_names=None):
        tag_ids = tag_ids or {}
        tag_names = tag_names or {}

        def hb_id(*p):
            if len(p) >= 3 and p[0] == "collections":
                if p[-1] == "tag_id":
                    return tag_ids.get(p[1])
                if p[-1] == "tag_name":
                    return tag_names.get(p[1])
            return None

        repair.hbconfig.hb_id = hb_id

    def test_tag_id_path_no_tag_list(self):
        self._hb_id(tag_ids={"projects": "TP", "progress": "TG"})
        self._patch_cli(cards_by_tag={"TP": [{"id": "p1", "title": "P"}],
                                      "TG": [{"id": "g1", "title": "G"}]})
        ids, warns = repair.scan_target_ids()
        self.assertEqual(sorted(i for i, _ in ids), ["g1", "p1"])
        self.assertEqual(warns, [])

    def test_progress_resolved_by_name_when_tag_id_unset(self):
        # progress has NO tag_id and NO tag_name → falls back to default name
        self._hb_id(tag_ids={"projects": "TP"})
        self._patch_cli(tags=[{"id": "TG", "name": "project/progress"}],
                        cards_by_tag={"TP": [{"id": "p1", "title": "P"}],
                                      "TG": [{"id": "g1", "title": "G"}]})
        ids, warns = repair.scan_target_ids()
        self.assertIn("g1", [i for i, _ in ids])   # log card NOT dropped
        self.assertEqual(warns, [])
        targets, _ = repair.scan_targets()
        modes = {cid: inline for cid, _, inline in targets}
        self.assertFalse(modes["p1"])
        self.assertTrue(modes["g1"])

    def test_unresolved_collection_warns_not_silent(self):
        self._hb_id()                       # nothing configured
        self._patch_cli(tags=[], cards_by_tag={})   # names not found either
        ids, warns = repair.scan_target_ids()
        self.assertEqual(ids, [])
        self.assertEqual(len(warns), 2)     # both collections warn — never silent


if __name__ == "__main__":
    unittest.main()
