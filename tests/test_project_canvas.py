"""project_canvas pure layout: node/edge topology, colors, ordering,
mirrored-vs-text degradation. No card I/O."""
import importlib.util
import os
import sys
import unittest

REPO = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
for p in ("_shared", "project-card-merge", "card-rewrite"):
    sys.path.insert(0, os.path.join(REPO, "skills", p))

spec = importlib.util.spec_from_file_location(
    "project_canvas_under_test",
    os.path.join(REPO, "skills", "project-card-log", "project_canvas.py"))
PC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PC)

E = "aaaaaaaa-0000-0000-0000-000000000001"
C1 = "aaaaaaaa-0000-0000-0000-000000000002"
L1 = "aaaaaaaa-0000-0000-0000-00000000000a"
L2 = "aaaaaaaa-0000-0000-0000-00000000000b"


class TestLogOrigin(unittest.TestCase):
    def test_env_field_mac(self):
        self.assertEqual(PC.log_origin(
            "# P｜主題（2026-07-21）\n**專案**：[[card:x]]　**環境**：Mac"
            "（local）　**代碼**：repo@abc1234"), "mac")

    def test_env_field_cluster_host(self):
        self.assertEqual(PC.log_origin(
            "# t\n**環境**：user-gpu-cluster-01.example.com　**代碼**：r@1"),
            "cluster")

    def test_retro_split_mac(self):
        self.assertEqual(PC.log_origin(
            "Low-Latency 軸卡｜Table 5 查證（2026-07-19）\n"
            "（Low-Latency 軸卡 的 log 卡／回溯拆分；母卡：[[card:e]]。"
            "原段：📥 Mac 補充 2026-07-19b）"), "mac")

    def test_retro_split_cluster(self):
        self.assertEqual(PC.log_origin(
            "X 的 log 卡（回溯拆分；原段：📥 cluster 進度 2026-07-12）"),
            "cluster")

    def test_env_beats_retro_line(self):
        # both present → the explicit 環境 field wins
        self.assertEqual(PC.log_origin(
            "**環境**：Mac\n…（原段：📥 cluster 補充 2026-07-01）"), "mac")

    def test_quoted_pattern_deep_in_body_ignored(self):
        body = "# t\n" + "正文" * PC.ORIGIN_SCAN_CHARS + \
               "\n提到 📥 cluster 補充 只是引用"
        self.assertIsNone(PC.log_origin(body))

    def test_no_signal_none(self):
        self.assertIsNone(PC.log_origin("# 普通卡\n沒有任何來源標記"))
        self.assertIsNone(PC.log_origin(""))
        self.assertIsNone(PC.log_origin(None))

    def test_empty_env_value_falls_through(self):
        # 環境 field present but empty → fall to the retro line
        self.assertEqual(PC.log_origin(
            "**環境**：\n（原段：📥 Mac 補充 2026-07-19a）"), "mac")

    def test_prose_word_boundary_not_a_field(self):
        # 環境 embedded in a longer word is prose, not the header field
        self.assertIsNone(PC.log_origin("# t\n這段討論執行環境：Mac 上的行為"))

    def test_quoted_inbox_block_without_retro_anchor(self):
        # 📥 cluster 補充 quoted in prose lacks the 原段 anchor → no origin
        self.assertIsNone(PC.log_origin("# t\n本文引用 📥 cluster 補充 的段落"))

    def test_machine_hostname_is_not_mac(self):
        self.assertEqual(PC.log_origin("# t\n**環境**：machine-01　**代碼**：r@1"),
                         "cluster")

    def test_empty_env_before_bold_next_field(self):
        # value must stop at the next bold field: **環境**： **代碼**：…
        # is an EMPTY value (→ retro fallback), not value="**代碼**：…"
        self.assertEqual(PC.log_origin(
            "**環境**： **代碼**：repo@1\n（原段：📥 Mac 補充 2026-07-20a）"),
            "mac")

    def test_strip_frontmatter(self):
        md = "---\nheptabase_id: x\ntags: [a]\n---\n# 標題\n**環境**：Mac"
        self.assertEqual(PC.log_origin(PC._strip_frontmatter(md)), "mac")
        self.assertEqual(PC._strip_frontmatter("# 無 frontmatter"),
                         "# 無 frontmatter")


class TestBuildCanvas(unittest.TestCase):
    def build(self, entries, mapping=None, chain=None, **kw):
        mapping = mapping or {}
        return PC.build_canvas(E, "專案", chain or [E], entries,
                               lambda cid: mapping.get(cid), **kw)

    def test_topology_newest_first_edges_point_up(self):
        c = self.build([
            {"log": L1, "date": "2026-07-18", "summary": "舊", "done": True},
            {"log": L2, "date": "2026-07-21", "summary": "新", "done": False}],
            mapping={E: "Projects/專案.md"})
        nodes = {n["id"]: n for n in c["nodes"]}
        n_new, n_old = nodes[PC._nid(L2)], nodes[PC._nid(L1)]
        self.assertLess(n_new["y"], n_old["y"])          # newest on top
        self.assertEqual(n_new["color"], PC.COLOR_PENDING)   # 📎 orange
        self.assertEqual(n_old["color"], PC.COLOR_DONE)      # 📗 green
        # edges: old→new, newest→entry (time flows upward)
        e = {(x["fromNode"], x["toNode"]) for x in c["edges"]}
        self.assertIn((PC._nid(L1), PC._nid(L2)), e)
        self.assertIn((PC._nid(L2), PC._nid(E)), e)

    def test_same_date_ordered_by_append_position(self):
        # timeline lines append in time order → later input position =
        # newer → sits HIGHER (smaller y). The old log-uuid tiebreak was
        # random; L1's uuid sorts before L2's, so this catches a regression
        # in either uuid direction via the reversed pair below.
        c = self.build([
            {"log": L2, "date": "2026-07-19", "summary": "早上", "done": False},
            {"log": L1, "date": "2026-07-19", "summary": "下午", "done": False}])
        nodes = {n["id"]: n for n in c["nodes"]}
        self.assertLess(nodes[PC._nid(L1)]["y"], nodes[PC._nid(L2)]["y"])
        # explicit seq (from a caller) beats input position
        c = self.build([
            {"log": L2, "date": "2026-07-19", "summary": "晚", "done": False,
             "seq": 9},
            {"log": L1, "date": "2026-07-19", "summary": "早", "done": False,
             "seq": 1}])
        nodes = {n["id"]: n for n in c["nodes"]}
        self.assertLess(nodes[PC._nid(L2)]["y"], nodes[PC._nid(L1)]["y"])

    def test_origin_mode_colors_by_machine(self):
        c = self.build([
            {"log": L1, "date": "2026-07-18", "summary": "mac 邊",
             "done": True, "origin": "mac"},
            {"log": L2, "date": "2026-07-21", "summary": "cluster 邊",
             "done": False, "origin": "cluster"}],
            color_by="origin")
        nodes = {n["id"]: n for n in c["nodes"]}
        self.assertEqual(nodes[PC._nid(L1)]["color"], PC.COLOR_MAC)
        self.assertEqual(nodes[PC._nid(L2)]["color"], PC.COLOR_CLUSTER)
        # entry keeps its purple in both modes
        self.assertEqual(nodes[PC._nid(E)]["color"], PC.COLOR_ENTRY)

    def test_origin_mode_unknown_is_uncolored(self):
        c = self.build([{"log": L1, "date": "2026-07-20",
                         "summary": "s", "done": False, "origin": None}],
                       color_by="origin")
        n = next(x for x in c["nodes"] if x["id"] == PC._nid(L1))
        self.assertNotIn("color", n)                     # gray default
        # …and the 📎 mark keeps the distillation state readable
        self.assertIn("📎", n["text"])

    def test_state_mode_unchanged_by_origin_field(self):
        c = self.build([{"log": L1, "date": "2026-07-20",
                         "summary": "s", "done": True, "origin": "cluster"}])
        n = next(x for x in c["nodes"] if x["id"] == PC._nid(L1))
        self.assertEqual(n["color"], PC.COLOR_DONE)      # origin ignored

    def test_resolve_color_by_precedence(self):
        cfg_o = {"heptabase": {"collections": {"projects":
                                               {"canvas_color_by": "origin"}}}}
        self.assertEqual(PC.resolve_color_by({}, None), "state")
        self.assertEqual(PC.resolve_color_by(cfg_o, None), "origin")
        self.assertEqual(PC.resolve_color_by(cfg_o, "state"), "state")  # CLI wins
        bad = {"heptabase": {"collections": {"projects":
                                             {"canvas_color_by": "<state-or-origin>"}}}}
        self.assertEqual(PC.resolve_color_by(bad, None), "state")

    def test_mirrored_becomes_file_node_else_text(self):
        c = self.build([{"log": L1, "date": "2026-07-20",
                         "summary": "s", "done": False}],
                       mapping={L1: "Projects/log.md"})
        n = next(x for x in c["nodes"] if x["id"] == PC._nid(L1))
        self.assertEqual(n["type"], "file")
        c2 = self.build([{"log": L1, "date": "2026-07-20",
                          "summary": "未鏡像摘要", "done": False}])
        n2 = next(x for x in c2["nodes"] if x["id"] == PC._nid(L1))
        self.assertEqual(n2["type"], "text")
        self.assertIn("未鏡像摘要", n2["text"])

    def test_chain_children_sit_beside_entry(self):
        c = self.build([], chain=[E, C1])
        child = next(x for x in c["nodes"] if x["id"] == PC._nid(C1, "chain"))
        self.assertEqual(child["y"], 0)
        self.assertGreater(child["x"], PC.NODE_W)

    def test_deterministic_ids(self):
        a = self.build([{"log": L1, "date": "2026-07-20", "summary": "s",
                         "done": False}])
        b = self.build([{"log": L1, "date": "2026-07-20", "summary": "s",
                         "done": False}])
        self.assertEqual([n["id"] for n in a["nodes"]],
                         [n["id"] for n in b["nodes"]])


class TestHeadText(unittest.TestCase):
    """Mirror-first with CLI fallback. merge_lib is stubbed via sys.modules
    (head_text imports it lazily)."""
    def setUp(self):
        import tempfile
        import types
        self.tmp = tempfile.mkdtemp(prefix="canvas-headtext-")
        self.cfg = {"backend": "both", "obsidian": {"vault": self.tmp}}
        self.fake_M = types.SimpleNamespace(
            L=types.SimpleNamespace(
                # realistic PM text: _txt strips bold marks, fields are
                # 　-separated — "環境" sits after whitespace, no asterisks
                read_card=lambda cid: (None, {"content": [
                    {"type": "paragraph",
                     "content": [{"type": "text",
                                  "text": "CLI 讀到 專案：x　環境：Mac　代碼：r@1"}]}]}),
                _txt=lambda n: "".join(c.get("text", "")
                                       for c in n.get("content", []))))
        self._orig = sys.modules.get("merge_lib")
        sys.modules["merge_lib"] = self.fake_M

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self._orig is not None:
            sys.modules["merge_lib"] = self._orig
        else:
            sys.modules.pop("merge_lib", None)

    def test_mirror_read_with_frontmatter_stripped(self):
        os.makedirs(os.path.join(self.tmp, "Projects"), exist_ok=True)
        with open(os.path.join(self.tmp, "Projects", "log.md"), "w",
                  encoding="utf-8") as f:
            f.write("---\nheptabase_id: x\n---\n# t\n**環境**：cluster-host-1")
        out = PC.head_text(L1, self.cfg, lambda cid: "Projects/log.md")
        self.assertNotIn("heptabase_id", out)
        self.assertEqual(PC.log_origin(out), "cluster")

    def test_missing_mirror_falls_back_to_cli(self):
        out = PC.head_text(L1, self.cfg, lambda cid: "Projects/gone.md")
        self.assertIn("CLI 讀到", out)
        self.assertEqual(PC.log_origin(out), "mac")

    def test_unmirrored_goes_straight_to_cli(self):
        out = PC.head_text(L1, self.cfg, lambda cid: None)
        self.assertIn("CLI 讀到", out)

    def test_everything_failing_returns_empty(self):
        self.fake_M.L.read_card = lambda cid: (_ for _ in ()).throw(
            RuntimeError("down"))
        out = PC.head_text(L1, self.cfg, lambda cid: "Projects/gone.md")
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
