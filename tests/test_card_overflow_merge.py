"""project-card-merge continuation-chain support (CARD-OVERFLOW.md merge side).

Pure-logic tests: every card/CLI touchpoint is monkeypatched — no Heptabase,
no config, no network. Covers the chain walk (cycle guard), child payload
stripping, sentinel round-trip, H2 packing (node conservation!), and
finalize_chain's plan/single/spill paths incl. the children-before-entry
write order that makes a crash lose nothing.
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "skills", "project-card-merge"))
# Isolate from any real user config (append_card.load_cfg -> {} -> defaults).
os.environ["RESEARCH_CARDS_CONFIG"] = "/nonexistent/research-cards-test.json"
os.environ.pop("HEPTABASE_CARDS_CONFIG", None)
import merge_lib as M  # noqa: E402


# ---- PM fixture builders ------------------------------------------------------
def h(level, text):
    return {"type": "heading", "attrs": {"id": None, "level": level},
            "content": [{"type": "text", "text": text}]}


def p(text):
    return {"type": "paragraph", "attrs": {"id": None},
            "content": [{"type": "text", "text": text}]}


def hr():
    return {"type": "horizontal_rule", "attrs": {"id": None}}


def sentinel(child_id):
    return M._cont_nodes(child_id)  # [hr, sentinel-paragraph]


def backref(entry_id):
    return {"type": "paragraph", "attrs": {"id": None}, "content": [
        {"type": "text", "text": "（X 的續卡 1／append 溢位；母卡："},
        {"type": "card", "attrs": {"cardId": entry_id}},
        {"type": "text", "text": "。整併請用 project-card-merge。）"}]}


E = "aaaaaaaa-0000-0000-0000-000000000001"
C1 = "aaaaaaaa-0000-0000-0000-000000000002"
C2 = "aaaaaaaa-0000-0000-0000-000000000003"


class TestContinuationParse(unittest.TestCase):
    def test_none_without_sentinel(self):
        doc = {"content": [h(1, "T"), p("body"), hr()]}
        self.assertIsNone(M._continuation_from_doc(doc))

    def test_finds_last_sentinel(self):
        doc = {"content": [p("x")] + sentinel(C1) + [p("y")] + sentinel(C2)}
        self.assertEqual(M._continuation_from_doc(doc), C2)

    def test_roundtrip_with_append_side_regex(self):
        # PM sentinel we write must also be recoverable by append_card's
        # text-level parser once rendered (`[[card:<id>]]` form).
        md = f"▶ **{M.AC.LINK_MARK}**：[[card:{C1}]]"
        self.assertEqual(M.AC.parse_continuation(md), C1)
        doc = {"content": sentinel(C1)}
        self.assertEqual(M._continuation_from_doc(doc), C1)

    def test_positional_selection_matches_append_side(self):
        # A card mention BEFORE the marker must be ignored; the FIRST card
        # after the marker wins — same semantics as parse_continuation.
        para = {"type": "paragraph", "attrs": {"id": None}, "content": [
            {"type": "card", "attrs": {"cardId": C2}},          # decoy before
            {"type": "text", "text": "▶ "},
            {"type": "text", "marks": [{"type": "strong"}], "text": M.AC.LINK_MARK},
            {"type": "text", "text": "："},
            {"type": "card", "attrs": {"cardId": C1}},          # the real link
            {"type": "card", "attrs": {"cardId": C2}},          # trailing decoy
        ]}
        self.assertEqual(M._continuation_from_doc({"content": [para]}), C1)
        md = f"[[card:{C2}]] ▶ **{M.AC.LINK_MARK}**：[[card:{C1}]] [[card:{C2}]]"
        self.assertEqual(M.AC.parse_continuation(md), C1)


class TestChainWalk(unittest.TestCase):
    def _patch_cards(self, mapping):
        self._orig = M.L.read_card
        M.L.read_card = lambda cid: ("md5", copy.deepcopy(mapping[cid]))

    def tearDown(self):
        if hasattr(self, "_orig"):
            M.L.read_card = self._orig

    def test_cycle_raises(self):
        self._patch_cards({
            E: {"content": [h(1, "T"), p("a")] + sentinel(C1)},
            C1: {"content": [h(1, "T · 續 1"), backref(E), p("b")] + sentinel(C2)},
            C2: {"content": [h(1, "T · 續 2"), backref(E), p("c")] + sentinel(E)},  # cycle!
        })
        with self.assertRaises(RuntimeError):
            M.chain(E)

    def test_self_loop_raises(self):
        self._patch_cards({E: {"content": [p("a")] + sentinel(E)}})
        with self.assertRaises(RuntimeError):
            M.chain(E)

    def test_unreadable_child_raises(self):
        mapping = {E: {"content": [p("a")] + sentinel(C1)}}
        self._orig = M.L.read_card

        def rc(cid):
            if cid not in mapping:
                raise IOError("gone")
            return "md5", copy.deepcopy(mapping[cid])
        M.L.read_card = rc
        with self.assertRaises(RuntimeError):
            M.chain(E)

    def test_walk_ok(self):
        self._patch_cards({
            E: {"content": [h(1, "T"), p("a")] + sentinel(C1)},
            C1: {"content": [h(1, "T · 續 1"), backref(E), p("b")] + sentinel(C2)},
            C2: {"content": [h(1, "T · 續 2"), backref(E), p("c")]},
        })
        self.assertEqual(M.chain(E), [E, C1, C2])

    def test_single_card_chain(self):
        self._patch_cards({E: {"content": [h(1, "T"), p("a")]}})
        self.assertEqual(M.chain(E), [E])


class TestChildPayload(unittest.TestCase):
    def test_strips_header_backref_and_links(self):
        doc = {"content": [h(1, "T · 續 1"), backref(E), p("real content"),
                           h(2, "📥 cluster 補充"), p("more")] + sentinel(C2)}
        got = M.child_payload(doc, E)
        texts = [M.L._txt(n) for n in got]
        self.assertEqual(len(got), 3)
        self.assertIn("real content", texts[0])
        self.assertNotIn(M.AC.LINK_MARK, " ".join(texts))

    def test_keeps_unrelated_hr(self):
        content = [p("a"), hr(), p("b")] + sentinel(C1)
        got = M.strip_continuation_nodes(content)
        self.assertEqual([n["type"] for n in got],
                         ["paragraph", "horizontal_rule", "paragraph"])

    def test_strips_only_one_backref(self):
        # User content that ALSO mentions the 母卡 must survive.
        user_para = backref(E)  # same shape as an auto back-ref, but it's content
        doc = {"content": [h(1, "T · 續 1"), backref(E), user_para, p("tail")]}
        got = M.child_payload(doc, E)
        self.assertEqual(len(got), 2)
        self.assertTrue(M._is_backref_para(got[0], E))   # the second one kept


class TestSplitH2(unittest.TestCase):
    def _sections(self, sizes):
        """One H2 section per size, padded to ~that many json chars."""
        out = []
        for i, s in enumerate(sizes):
            out.append(h(2, f"S{i}"))
            out.append(p("x" * max(1, s - M._node_size(h(2, f"S{i}")) - 120)))
        return out

    def test_conserves_every_node_in_order(self):
        content = self._sections([500, 500, 500, 500])
        segs = M.split_h2(content, budget=1200)
        flat = [n for seg in segs for n in seg]
        self.assertEqual(flat, content)          # nothing lost, order kept
        self.assertGreater(len(segs), 1)

    def test_breaks_only_at_h2(self):
        content = [p("preamble")] + self._sections([600, 600, 600])
        segs = M.split_h2(content, budget=1400)
        for seg in segs[1:]:
            self.assertEqual(seg[0]["type"], "heading")
            self.assertEqual(seg[0]["attrs"]["level"], 2)

    def test_oversize_single_section_isolated(self):
        content = self._sections([300, 5000, 300])
        segs = M.split_h2(content, budget=1000)
        big = max(segs, key=lambda s: sum(M._node_size(n) for n in s))
        self.assertEqual(M.L._txt(big[0]), "S1")  # giant section = own segment


class TestFinalizeChain(unittest.TestCase):
    def setUp(self):
        self._saved = []
        self._created = []
        self._orig = (M.L.read_card, M.L.save_card, M.L.colorize,
                      M.L._shrink_card_figures, M.AC.cap_threshold,
                      M.AC.load_cfg, M._create_child, M.L.OBS)
        M.L.read_card = lambda cid: ("md5", {"content": [p("old")]})
        M.L.save_card = lambda cid, md5, doc: self._saved.append((cid, doc))
        M.L.colorize = lambda nodes, rules: nodes
        M.L._shrink_card_figures = lambda content, **kw: None
        M.AC.load_cfg = lambda: {}
        M.L.OBS = None

        def fake_create(entry_id, entry_title, n, body, tag):
            cid = f"child-{n}"
            self._created.append((cid, body))
            return cid
        M._create_child = fake_create

    def tearDown(self):
        (M.L.read_card, M.L.save_card, M.L.colorize,
         M.L._shrink_card_figures, M.AC.cap_threshold,
         M.AC.load_cfg, M._create_child, M.L.OBS) = self._orig

    def _content(self, n_sections=4, size=600):
        out = [h(1, "Proj X")]
        for i in range(n_sections):
            out += [h(2, f"S{i}"), p("x" * size)]
        return out

    def test_under_threshold_single_save(self):
        M.AC.cap_threshold = lambda cfg: (100000, 80000)
        got = M.finalize_chain(E, "md5", self._content(2, 200), [])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][0], E)
        self.assertEqual(len(self._saved), 1)      # entry only
        self.assertEqual(self._created, [])

    def test_dry_run_writes_nothing(self):
        M.AC.cap_threshold = lambda cfg: (3000, 2000)
        plan = M.finalize_chain(E, "md5", self._content(4, 600), [], dry_run=True)
        self.assertGreater(len(plan), 1)
        self.assertEqual(self._saved, [])
        self.assertEqual(self._created, [])

    def test_spill_children_before_entry_and_linked(self):
        M.AC.cap_threshold = lambda cfg: (3000, 2000)
        got = M.finalize_chain(E, "md5", self._content(4, 600), [])
        self.assertGreater(len(got), 1)
        # children were created before the single entry save
        self.assertTrue(self._created)
        self.assertEqual(len(self._saved), 1)
        entry_cid, entry_doc = self._saved[0]
        self.assertEqual(entry_cid, E)
        # entry tail links to child-1
        self.assertEqual(M._continuation_from_doc(entry_doc), "child-1")
        # children were created tail-first and every non-tail child links onward
        order = [c for c, _ in self._created]
        self.assertEqual(order, sorted(order, reverse=True))
        bodies = dict(self._created)
        n = len(bodies)
        for i in range(1, n):                      # child-1 … child-(n-1) link on
            nxt = M._continuation_from_doc({"content": bodies[f"child-{i}"]})
            self.assertEqual(nxt, f"child-{i + 1}")
        tail = M._continuation_from_doc({"content": bodies[f"child-{n}"]})
        self.assertIsNone(tail)
        # every child opens with the auto-header (H1 · 續 N + 母卡 back-ref)
        for cid, body in self._created:
            self.assertEqual(body[0]["attrs"]["level"], 1)
            self.assertIn("· 續", M.L._txt(body[0]))
            self.assertTrue(M._is_backref_para(body[1], E))

    def test_node_conservation_across_spill(self):
        M.AC.cap_threshold = lambda cfg: (3000, 2000)
        content = self._content(4, 600)
        M.finalize_chain(E, "md5", copy.deepcopy(content), [])
        _, entry_doc = self._saved[0]
        rebuilt = M.strip_continuation_nodes(entry_doc["content"])
        for _, body in sorted(self._created):
            rebuilt += M.child_payload({"content": body}, E)
        self.assertEqual([M.L._txt(n) for n in rebuilt],
                         [M.L._txt(n) for n in content])

    def test_giant_section_rejected_before_any_write(self):
        # One H2 bigger than the CAP: must raise pre-write even though the
        # content splits into multiple segments (the old guard only caught
        # the single-segment case).
        M.AC.cap_threshold = lambda cfg: (3000, 2000)
        content = [h(1, "Proj X"), h(2, "S0"), p("x" * 300),
                   h(2, "GIANT"), p("y" * 5000), h(2, "S2"), p("z" * 300)]
        with self.assertRaises(ValueError):
            M.finalize_chain(E, "md5", content, [])
        self.assertEqual(self._saved, [])
        self.assertEqual(self._created, [])

    def test_planned_sizes_include_header_and_sentinel(self):
        M.AC.cap_threshold = lambda cfg: (30000, 2000)
        content = self._content(3, 900)
        plan = M.finalize_chain(E, "md5", content, [], dry_run=True)
        # each planned size must exceed the raw section size (header/sentinel in)
        raw = [M._node_size(n) for n in content]
        self.assertTrue(all(s > 900 for _, s in plan))
        self.assertGreater(len(plan), 1)

    def test_obsidian_no_cap_no_spill(self):
        M.AC.cap_threshold = lambda cfg: (3000, 2000)
        M.L.OBS = object()                       # truthy → no cap semantics
        got = M.finalize_chain(E, "md5", self._content(4, 600), [])
        self.assertEqual(len(got), 1)
        self.assertEqual(len(self._saved), 1)
        self.assertEqual(self._created, [])


class TestRound2Fixes(unittest.TestCase):
    """Verify-pass round 2: nested visibility, split marker, md5 lock,
    writer CHAIN_MAX, scan second-read protection."""

    def test_nested_image_extracted_and_visible(self):
        img = {"type": "image", "attrs": {"id": None, "src": "data:image/png;base64,xyz"}}
        bullet = {"type": "bullet_list_item",
                  "attrs": {"id": None, "folded": False, "format": None},
                  "content": [p("with figure"), img]}
        doc = {"content": [h(1, "T"), bullet]}
        self.assertEqual(len(M.L.extract_images(doc)), 1)      # recursive
        self.assertIn("[IMAGE", M.L._txt(bullet))              # visible in dumps

    def test_unknown_leaf_node_visible(self):
        weird = {"type": "whiteboard_embed", "attrs": {"id": "w1"}}
        self.assertEqual(M.L._txt(weird), "[whiteboard_embed]")

    def test_marker_split_across_text_nodes(self):
        mark = M.AC.LINK_MARK
        para = {"type": "paragraph", "attrs": {"id": None}, "content": [
            {"type": "text", "text": "▶ " + mark[:3]},
            {"type": "text", "marks": [{"type": "strong"}], "text": mark[3:]},
            {"type": "text", "text": "："},
            {"type": "card", "attrs": {"cardId": C1}},
        ]}
        self.assertEqual(M._continuation_from_doc({"content": [para]}), C1)

    def test_scan_second_read_failure_becomes_chain_error(self):
        mapping = {E: {"content": [h(1, "T"), p("a")] + sentinel(C1)},
                   C1: {"content": [h(1, "T · 續 1"), backref(E), p("b")]}}
        calls = {"n": 0}
        orig = (M.L.read_card, M.L.extract_images, M.find_orphans,
                M._require_project_feature)

        def rc(cid):
            if cid == C1:
                calls["n"] += 1
                if calls["n"] > 1:          # first read (chain walk) ok, second dies
                    raise OSError("gone mid-scan")
            return "md5", copy.deepcopy(mapping[cid])
        M.L.read_card = rc
        M.L.extract_images = lambda doc: []
        M.find_orphans = lambda *a, **kw: []
        M._require_project_feature = lambda: None
        try:
            s = M.scan(E)
            self.assertTrue(s["chain_error"])
            self.assertTrue(s["needs_merge"])
        finally:
            (M.L.read_card, M.L.extract_images, M.find_orphans,
             M._require_project_feature) = orig


class TestMd5AndChainMax(unittest.TestCase):
    def setUp(self):
        self._saved, self._created = [], []
        self._orig = (M.L.read_card, M.L.save_card, M.L.colorize,
                      M.L._shrink_card_figures, M.AC.cap_threshold,
                      M.AC.load_cfg, M._create_child, M.L.OBS, M.AC.CHAIN_MAX)
        M.L.read_card = lambda cid: ("md5", {"content": [p("old")]})
        M.L.save_card = lambda cid, md5, doc: self._saved.append((cid, md5))
        M.L.colorize = lambda nodes, rules: nodes
        M.L._shrink_card_figures = lambda content, **kw: None
        M.AC.load_cfg = lambda: {}
        M.L.OBS = None
        M._create_child = lambda e, t, n, b, tag: self._created.append(n) or f"child-{n}"

    def tearDown(self):
        (M.L.read_card, M.L.save_card, M.L.colorize,
         M.L._shrink_card_figures, M.AC.cap_threshold,
         M.AC.load_cfg, M._create_child, M.L.OBS, M.AC.CHAIN_MAX) = self._orig

    def _content(self, n_sections, size=600):
        out = [h(1, "Proj X")]
        for i in range(n_sections):
            out += [h(2, f"S{i}"), p("x" * size)]
        return out

    def test_stale_md5_rejected_single_path(self):
        M.AC.cap_threshold = lambda cfg: (100000, 80000)
        with self.assertRaises(RuntimeError):
            M.finalize_chain(E, "STALE", self._content(2, 100), [])
        self.assertEqual(self._saved, [])

    def test_stale_md5_rejected_before_children(self):
        M.AC.cap_threshold = lambda cfg: (3000, 2000)
        with self.assertRaises(RuntimeError):
            M.finalize_chain(E, "STALE", self._content(4, 600), [])
        self.assertEqual(self._created, [])       # no orphans from a stale merge
        self.assertEqual(self._saved, [])

    def test_writer_respects_chain_max(self):
        M.AC.cap_threshold = lambda cfg: (3000, 2000)
        M.AC.CHAIN_MAX = 3
        with self.assertRaises(ValueError):
            M.finalize_chain(E, "md5", self._content(6, 900), [])
        self.assertEqual(self._created, [])


class TestRound3Fixes(unittest.TestCase):
    """Verify-pass round 3: chain-wide md5 lock, estimator, nested shrink."""

    def test_cleanup_skips_child_with_changed_md5(self):
        orig = (M.L.read_card, M._sp.run, M.AC.load_cfg)
        trashed = []
        M.L.read_card = lambda cid: ("NEW-MD5", {"content": []})
        M.AC.load_cfg = lambda: {}

        class R:
            returncode = 0
        def fake_run(args, **kw):
            if "trash" in args:
                trashed.append(args[-1])
            return R()
        M._sp.run = fake_run
        try:
            M.cleanup_children([C1], md5s={C1: "OLD-MD5"})   # changed → skip
            self.assertEqual(trashed, [])
            M.cleanup_children([C1], md5s={C1: "NEW-MD5"})   # unchanged → trash
            self.assertEqual(trashed, [C1])
        finally:
            M.L.read_card, M._sp.run, M.AC.load_cfg = orig

    def test_chain_dumps_one_read_same_version(self):
        # each card is read EXACTLY once; md5 and dump come from that same read
        # (a version bump between reads must be impossible by construction)
        orig = M.L.read_card
        counter = {"n": 0}

        def rc(cid):
            counter["n"] += 1
            v = counter["n"]
            return f"md5-v{v}", {"content": [h(1, f"T v{v}"), p(f"body v{v}")]}
        M.L.read_card = rc
        try:
            out = M.chain_dumps(E)
            self.assertEqual(counter["n"], 1)              # ONE read total
            cid, md5v, dump = out[0]
            self.assertEqual(md5v, "md5-v1")
            self.assertIn("body v1", dump)                 # dump = same version
        finally:
            M.L.read_card = orig

    def test_cleanup_no_baseline_fails_closed(self):
        orig = (M.L.read_card, M._sp.run, M.AC.load_cfg)
        trashed, reads = [], []
        M.L.read_card = lambda cid: reads.append(cid) or ("m", {"content": []})
        M.AC.load_cfg = lambda: {}

        class R:
            returncode = 0
        def fake_run(args, **kw):
            if "trash" in args:
                trashed.append(args[-1])
            return R()
        M._sp.run = fake_run
        try:
            M.cleanup_children([C1], md5s={})   # baseline missing → never trash
            self.assertEqual(trashed, [])
            M.cleanup_children([C1], md5s=None)  # explicit opt-out → old behavior
            self.assertEqual(trashed, [C1])
        finally:
            M.L.read_card, M._sp.run, M.AC.load_cfg = orig

    def test_scan_survives_entry_reread_oserror(self):
        orig = (M.L.read_card, M.L.extract_images, M.find_orphans,
                M._require_project_feature)
        calls = {"n": 0}
        doc = {"content": [h(1, "T"), p("a")] + sentinel(C1)}

        def rc(cid):
            calls["n"] += 1
            if calls["n"] == 1:
                return "md5", copy.deepcopy(doc)   # scan's own first read
            raise OSError("entry gone inside chain()")
        M.L.read_card = rc
        M.L.extract_images = lambda d: []
        M.find_orphans = lambda *a, **kw: []
        M._require_project_feature = lambda: None
        try:
            s = M.scan(E)                          # must NOT crash
            self.assertTrue(s["chain_error"])
            self.assertTrue(s["needs_merge"])
        finally:
            (M.L.read_card, M.L.extract_images, M.find_orphans,
             M._require_project_feature) = orig

    def test_est_stored_len_upper_bounds_real_stored_sizes(self):
        # est is MEASURED via md2pm ×1.1. Assert against empirically observed
        # post-save stored sizes (2026-07-08, real Heptabase saves):
        cases = [
            ("**x**" * 2000, 82166),                      # bold pathology
            (("*x* " * 1125).rstrip(), 87967),            # spaced italic (round-4 反例)
            (("平常的敘述文字，實驗紀錄的一句話。\n" * 155).rstrip(), 3212),
        ]
        for md, stored in cases:
            self.assertGreaterEqual(M.AC.est_stored_len(md), stored)

    def test_est_stored_len_no_false_overflow_on_normal_logs(self):
        # 155-line bold experiment log stores ~30k — must stay FAR below an
        # 80k threshold (round-4 found the heuristic falsely rejecting these)
        log = ("**step 1234** loss=0.123 **val** wer=5.6\n" * 155).rstrip()
        self.assertLess(M.AC.est_stored_len(log), 60000)
        self.assertFalse(M.AC.would_overflow(20000, M.AC.est_stored_len(log), 80000))

    def test_est_stored_len_fallback_still_high(self):
        # parser rejection (unknown anchor) falls back to the high heuristic
        md = "content with bad anchor ^zzzzzzzz\n" + "**x**" * 2000
        self.assertGreater(M.AC.est_stored_len(md), 100000)

    def test_shrink_reaches_nested_images(self):
        orig = M.L.shrink_data_url
        seen = []
        M.L.shrink_data_url = lambda src, **kw: seen.append(src) or src
        img = {"type": "image", "attrs": {"id": None, "src": "data:image/png;base64,abc"}}
        nested = {"type": "bullet_list_item",
                  "attrs": {"id": None, "folded": False, "format": None},
                  "content": [p("cap"), img]}
        try:
            M.L._shrink_card_figures([h(1, "T"), nested], steps=((720, 60),))
            self.assertEqual(len(seen), 1)
        finally:
            M.L.shrink_data_url = orig


class TestScanSemantics(unittest.TestCase):
    def setUp(self):
        self._orig = (M.L.read_card, M.L.extract_images, M.find_orphans,
                      M._require_project_feature)
        M.L.extract_images = lambda doc: []
        M.find_orphans = lambda *a, **kw: []
        M._require_project_feature = lambda: None

    def tearDown(self):
        (M.L.read_card, M.L.extract_images, M.find_orphans,
         M._require_project_feature) = self._orig

    def _cards(self, mapping):
        M.L.read_card = lambda cid: ("md5", copy.deepcopy(mapping[cid]))

    def test_clean_chain_is_consolidated(self):
        self._cards({
            E: {"content": [h(1, "T"), h(2, "方法"), p("a")] + sentinel(C1)},
            C1: {"content": [h(1, "T · 續 1"), backref(E), h(2, "實驗"), p("b")]},
        })
        s = M.scan(E)
        self.assertEqual(len(s["chain"]), 2)
        self.assertIsNone(s["chain_error"])
        self.assertFalse(s["needs_merge"])       # chain alone ≠ todo

    def test_chain_error_flags_merge(self):
        self._cards({E: {"content": [h(1, "T"), p("a")] + sentinel(E)}})
        s = M.scan(E)
        self.assertTrue(s["chain_error"])
        self.assertTrue(s["needs_merge"])

    def test_marker_on_child_flags_merge(self):
        self._cards({
            E: {"content": [h(1, "T"), h(2, "方法"), p("a")] + sentinel(C1)},
            C1: {"content": [h(1, "T · 續 1"), backref(E),
                             h(2, "📥 cluster 補充 2026-07-08"), p("b")]},
        })
        self.assertTrue(M.scan(E)["needs_merge"])


LOG1 = "aaaaaaaa-0000-0000-0000-00000000000a"


def loglink_sealed(log_id, date, summary, mark="📎"):
    return {"type": "paragraph", "attrs": {"id": None}, "content": [
        {"type": "text", "text": f"{mark} {date}　"},
        {"type": "card", "attrs": {"cardId": log_id}},
        {"type": "text", "text": f"　{summary}"}]}


class TestLogTimeline(TestScanSemantics):
    def test_loglink_of_both_shapes(self):
        sealed = M.loglink_of(loglink_sealed(LOG1, "2026-07-21", "一句摘要"))
        self.assertEqual(sealed, {"log": LOG1, "date": "2026-07-21",
                                  "summary": "一句摘要", "done": False})
        literal = M.loglink_of(p(f"📎 2026-07-21　[[card:{LOG1}]]　文字形摘要"))
        self.assertEqual(literal["log"], LOG1)
        self.assertEqual(literal["summary"], "文字形摘要")
        done = M.loglink_of(loglink_sealed(LOG1, "2026-07-20", "已蒸餾", "📗"))
        self.assertTrue(done["done"])
        self.assertIsNone(M.loglink_of(p("內文提到 📎 但不是時間線")))

    def test_scan_pending_log_flags_merge_done_does_not(self):
        # pending 📎 on the tail → needs_merge
        self._cards({
            E: {"content": [h(1, "T"), p("body"),
                            loglink_sealed(LOG1, "2026-07-21", "s")]}})
        s = M.scan(E)
        self.assertEqual(len(s["pending_logs"]), 1)
        self.assertTrue(s["needs_merge"])
        # only 📗 (already distilled) → record, not a todo
        self._cards({
            E: {"content": [h(1, "T"), p("body"),
                            h(2, "📜 log 時間線"),
                            loglink_sealed(LOG1, "2026-07-20", "s", "📗")]}})
        s = M.scan(E)
        self.assertEqual(len(s["done_logs"]), 1)
        self.assertFalse(s["pending_logs"])
        self.assertFalse(s["needs_merge"])

    def test_timeline_section_builds_sorted_done_nodes(self):
        nodes = M.timeline_section([
            {"log": LOG1, "date": "2026-07-21", "summary": "後"},
            {"log": E, "date": "2026-07-18", "summary": "先"}])
        self.assertEqual(nodes[0]["type"], "heading")
        self.assertIn("📜", nodes[0]["content"][0]["text"])
        # date-ascending, each line has a REAL card node + 📗 mark
        self.assertEqual(nodes[1]["content"][1]["attrs"]["cardId"], E)
        self.assertTrue(nodes[1]["content"][0]["text"].startswith("📗"))
        self.assertEqual(nodes[2]["content"][1]["attrs"]["cardId"], LOG1)


if __name__ == "__main__":
    unittest.main()
