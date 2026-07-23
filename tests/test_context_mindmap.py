"""context_mindmap (EXPERIMENTAL) pure logic: section split, leaf/question
extraction, citation graph, topological build order, tree assembly with
incremental (--limit) id stability. No card I/O."""
import importlib.util
import os
import sys
import unittest

REPO = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
for p in ("_shared", "project-card-merge", "card-rewrite",
          "project-card-canvas"):
    sys.path.insert(0, os.path.join(REPO, "skills", p))

spec = importlib.util.spec_from_file_location(
    "context_mindmap_under_test",
    os.path.join(REPO, "skills", "project-card-canvas", "context_mindmap.py"))
CM = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CM)
PCV = CM.PCV

E = "aaaaaaaa-0000-0000-0000-000000000001"
L1 = "aaaaaaaa-0000-0000-0000-00000000000a"   # earliest (cites nothing)
L2 = "aaaaaaaa-0000-0000-0000-00000000000b"   # cites L1
L3 = "aaaaaaaa-0000-0000-0000-00000000000c"   # cites L1 + L2


def h(level, text):
    return {"type": "heading", "attrs": {"level": level},
            "content": [{"type": "text", "text": text}]}


def p(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def txt(n):
    return "".join(c.get("text", "") for c in n.get("content", [])
                   if isinstance(c, dict))


class TestExtraction(unittest.TestCase):
    def test_split_sections_by_h2(self):
        secs = CM.split_sections(
            [p("header"), h(2, "前情提要"), p("a"), p("b"),
             h(2, "做了什麼"), p("c"), h(3, "小節"), p("d")], txt)
        self.assertEqual([txt(n) for n in secs["_header"]], ["header"])
        self.assertEqual([txt(n) for n in secs["前情提要"]], ["a", "b"])
        # H3 stays inside the enclosing H2 section
        self.assertEqual(len(secs["做了什麼"]), 3)

    def test_section_named_fuzzy(self):
        secs = {"_header": [], "⚖️ 待裁決／下一步": [p("x")]}
        self.assertEqual(len(CM.section_named(secs, "待裁決")), 1)
        self.assertIsNone(CM.section_named(secs, "結果"))

    def test_leaf_text_trims_and_marks_tables(self):
        nodes = [p("第一段"), {"type": "table", "content": []}, p("第二段")]
        t = CM.leaf_text(nodes, txt)
        self.assertIn("第一段", t)
        self.assertIn("（表格：開卡看）", t)
        long = CM.leaf_text([p("字" * 500)], txt)
        self.assertLessEqual(len(long), CM.LEAF_CHARS + 1)
        self.assertTrue(long.endswith("…"))

    def test_question_of(self):
        pre = [p("專案一句話：…"), p("這次要回答：分界軸是什麼？")]
        self.assertTrue(CM.question_of(pre, txt).startswith("這次要回答"))
        self.assertEqual(CM.question_of([p("沒有問題句")], txt), "")

    def test_citations_in_set_ordered_deduped(self):
        pre = [p(f"至上次為止 [[card:{L1}]] 與 [[card:{L2}]] 再引 [[card:{L1}]]"),
               p(f"外部卡 [[card:{'b'*8}-1111-2222-3333-444444444444]] 忽略"),
               p(f"自引 [[card:{L3}]] 忽略")]
        self.assertEqual(
            CM.citations_of(pre, txt, {L1, L2, L3}, L3), [L1, L2])

    def test_citations_from_real_card_nodes_any_id_shape(self):
        # PM card-mention nodes are the primary source — including local
        # Folder/Name ids the [[card:uuid]] regex can never see
        local = "Projects/上一輪 log"
        pre = [{"type": "paragraph", "content": [
            {"type": "text", "text": "承接 "},
            {"type": "card", "attrs": {"cardId": local}},
            {"type": "text", "text": f" 與 [[card:{L1}]]"}]}]
        self.assertEqual(
            CM.citations_of(pre, txt, {local, L1, L3}, L3), [local, L1])

    def test_section_named_anchored_not_fuzzy(self):
        secs = CM.split_sections(
            [h(2, "附錄：前情提要範例"), p("誘餌"),
             h(2, "前情提要"), p("正身")], txt)
        nodes = CM.section_named(secs, "前情提要")
        self.assertEqual([txt(n) for n in nodes], ["正身"])

    def test_table_marker_survives_long_text(self):
        nodes = [p("長" * 500), {"type": "table", "content": []}]
        t = CM.leaf_text(nodes, txt)
        self.assertIn(CM.TABLE_MARK, t)
        self.assertLessEqual(len(t), CM.LEAF_CHARS + 2)


LOGS = [{"log": L1, "date": "2026-07-19", "seq": 5},
        {"log": L2, "date": "2026-07-19", "seq": 1},
        {"log": L3, "date": "2026-07-20", "seq": 0}]


class TestTopoOrder(unittest.TestCase):
    def test_cited_before_citer_regardless_of_seq(self):
        # L1 has the LARGEST seq but cites nothing → must come first
        order = CM.topo_order(LOGS, {L2: [L1], L3: [L1, L2]})
        self.assertEqual(order, [L1, L2, L3])

    def test_tie_break_by_date_then_seq(self):
        order = CM.topo_order(LOGS, {})
        self.assertEqual(order, [L2, L1, L3])   # same date: seq 1 < 5

    def test_cycle_degrades_deterministically(self):
        order = CM.topo_order(LOGS, {L1: [L2], L2: [L1], L3: [L2]})
        self.assertEqual(len(order), 3)
        self.assertEqual(set(order), {L1, L2, L3})


def decomp_fixture():
    return {
        L1: {"title": "根", "question": "這次要回答：Q1",
             "sections": [("🔬 做了什麼", None, "d1"),
                          ("💡 這代表什麼", "4", "m1")],
             "cites": []},
        L2: {"title": "承一", "question": "這次要回答：Q2",
             "sections": [("⚖️ 待裁決／下一步", "1", "p2")],
             "cites": [L1]},
        L3: {"title": "承二", "question": "",
             "sections": [], "cites": [L1, L2]},
    }


class TestBuildMindmap(unittest.TestCase):
    def build(self, limit=None, mapping=None):
        mapping = mapping or {}
        return CM.build_mindmap(E, "軸卡", LOGS, decomp_fixture(),
                                lambda cid: mapping.get(cid), limit=limit)

    def test_limit_one_is_root_plus_earliest_subtree(self):
        c, order = self.build(limit=1)
        self.assertEqual(order, [L1])
        ids = {n["id"] for n in c["nodes"]}
        self.assertIn(PCV._nid(E, "mm-root"), ids)
        self.assertIn(PCV._nid(L1, "mm-hub"), ids)
        self.assertNotIn(PCV._nid(L2, "mm-hub"), ids)
        # ❓ + 🔬 + 💡 leaves (+ root + legend)
        self.assertEqual(len(c["nodes"]), 6)

    def test_ids_stable_as_map_expands(self):
        c1, _ = self.build(limit=1)
        c3, _ = self.build()
        ids1 = {n["id"] for n in c1["nodes"]}
        ids3 = {n["id"] for n in c3["nodes"]}
        self.assertTrue(ids1 <= ids3)        # expansion only ADDS nodes

    def test_parent_is_latest_citation_secondary_labeled(self):
        c, _ = self.build()
        hub = lambda cid: PCV._nid(cid, "mm-hub")  # noqa: E731
        pairs = {(e["fromNode"], e["toNode"]): e for e in c["edges"]}
        self.assertIn((hub(L2), hub(L3)), pairs)         # parent = L2 (latest)
        sec = pairs.get((hub(L1), hub(L3)))
        self.assertIsNotNone(sec)                        # secondary edge L1→L3
        self.assertEqual(sec.get("label"), "也承接")
        # L1 hangs off the root
        self.assertIn((PCV._nid(E, "mm-root"), hub(L1)), pairs)

    def test_v2_horizontal_spine_leaves_below(self):
        c, order = self.build()
        by = {n["id"]: n for n in c["nodes"]}
        hubs = [by[PCV._nid(cid, "mm-hub")] for cid in order]
        self.assertEqual({h["y"] for h in hubs}, {0})      # one lane
        self.assertEqual([h["x"] for h in hubs],
                         sorted(h["x"] for h in hubs))     # left→right
        leaf = by[PCV._nid(L1, "mm-leaf0")]
        hub = by[PCV._nid(L1, "mm-hub")]
        self.assertGreater(leaf["y"], hub["y"] + hub["height"])  # below
        self.assertLess(abs(leaf["x"] - hub["x"]), 60)     # same column

    def test_second_forest_root_flies_over_the_lane(self):
        decomp = decomp_fixture()
        decomp[L2]["cites"] = []          # two roots: L1 and L2
        c, _ = CM.build_mindmap(E, "軸卡", LOGS, decomp, lambda cid: None)
        sides = {(e["fromNode"], e["toNode"]): (e["fromSide"], e["toSide"])
                 for e in c["edges"]}
        r = PCV._nid(E, "mm-root")
        hub = lambda cid: PCV._nid(cid, "mm-hub")  # noqa: E731
        # topo order (tie by date,seq) seats L2 first → it gets the
        # lateral edge; L1 (second root) flies over the lane
        self.assertEqual(sides[(r, hub(L2))], ("right", "left"))
        self.assertEqual(sides[(r, hub(L1))], ("top", "top"))

    def test_glossary_node_only_when_terms(self):
        self.assertIsNone(CM.glossary_node(E, [], 0))
        n = CM.glossary_node(E, ["st1＝最細串流檔", "CMOS＝人耳對比評分"], -260)
        self.assertEqual(n["id"], PCV._nid(E, "mm-glossary"))
        self.assertIn("st1＝最細串流檔", n["text"])
        self.assertLess(n["y"] + n["height"], 0)

    def test_leaf_colors_and_hub_color(self):
        c, _ = self.build(limit=1)
        by_id = {n["id"]: n for n in c["nodes"]}
        self.assertEqual(by_id[PCV._nid(L1, "mm-hub")]["color"], CM.COLOR_HUB)
        texts = {n.get("text", ""): n for n in c["nodes"]}
        q = next(n for t, n in texts.items() if t.startswith("**❓"))
        self.assertEqual(q["color"], "2")
        m = next(n for t, n in texts.items() if t.startswith("**💡"))
        self.assertEqual(m["color"], "4")
        d = next(n for t, n in texts.items() if t.startswith("**🔬"))
        self.assertNotIn("color", d)

    def test_no_vertical_overlap_within_column(self):
        c, _ = self.build()
        from collections import defaultdict
        cols = defaultdict(list)
        for n in c["nodes"]:
            cols[n["x"]].append((n["y"], n["y"] + n["height"]))
        for spans in cols.values():
            spans.sort()
            for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
                self.assertLessEqual(a1, b0)

    def test_cycle_members_stay_attached_and_subset_holds(self):
        # L1↔L2 cite each other. The cycle-breaker seats the (date, seq)
        # oldest first — L2 (seq 1) — and the dropped back-edge must vanish
        # from the TREE too: root→L2→L1, nothing detaches.
        decomp = decomp_fixture()
        decomp[L1]["cites"] = [L2]
        decomp[L2]["cites"] = [L1]
        c_full, order = CM.build_mindmap(E, "軸卡", LOGS, decomp,
                                         lambda cid: None)
        self.assertEqual(order[0], L2)
        hubs = {n["id"] for n in c_full["nodes"]}
        for cid in order:
            self.assertIn(PCV._nid(cid, "mm-hub"), hubs)
        c_1, o1 = CM.build_mindmap(E, "軸卡", LOGS, decomp,
                                   lambda cid: None, limit=1)
        self.assertEqual(o1, [L2])
        self.assertTrue({n["id"] for n in c_1["nodes"]}
                        <= {n["id"] for n in c_full["nodes"]})
        pairs = {(e["fromNode"], e["toNode"]) for e in c_full["edges"]}
        self.assertIn((PCV._nid(E, "mm-root"), PCV._nid(L2, "mm-hub")), pairs)
        self.assertIn((PCV._nid(L2, "mm-hub"), PCV._nid(L1, "mm-hub")), pairs)

    def test_secondary_edge_ids_unique_same_prefix(self):
        # L1/L2 share their first 8 uuid chars — two secondary edges from
        # the same citer must still get distinct edge ids
        L4 = "aaaaaaaa-0000-0000-0000-00000000000d"
        logs = LOGS + [{"log": L4, "date": "2026-07-21", "seq": 9}]
        decomp = decomp_fixture()
        decomp[L4] = {"title": "四", "question": "",
                      "sections": [], "cites": [L1, L2, L3]}
        c, _ = CM.build_mindmap(E, "軸卡", logs, decomp, lambda cid: None)
        ids = [e["id"] for e in c["edges"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            len([e for e in c["edges"] if e.get("label") == "也承接"]), 3)

    def test_secondary_edge_ids_unambiguous_for_variable_length_ids(self):
        # local ids are variable-length: citer "P/c" citing "P/ab" and citer
        # "P/bc" citing "P/a" must not concatenate into the same salt
        a, ab, bc, c = "P/a", "P/ab", "P/bc", "P/c"
        logs = [{"log": x, "date": "2026-07-19", "seq": i}
                for i, x in enumerate([a, ab, bc, c])]
        decomp = {
            a: {"title": "a", "question": "", "sections": [], "cites": []},
            ab: {"title": "ab", "question": "", "sections": [], "cites": []},
            bc: {"title": "bc", "question": "", "sections": [],
                 "cites": [ab, a]},           # parent ab, secondary a
            c: {"title": "c", "question": "", "sections": [],
                "cites": [bc, ab]},           # parent bc, secondary ab
        }
        cv, _ = CM.build_mindmap(E, "軸卡", logs, decomp, lambda cid: None)
        ids = [e["id"] for e in cv["edges"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_deep_linear_chain_no_recursion_error(self):
        n = 1500
        ids = [f"cccccccc-0000-0000-0000-{i:012d}" for i in range(n)]
        logs = [{"log": cid, "date": "2026-07-19", "seq": i}
                for i, cid in enumerate(ids)]
        decomp = {cid: {"title": f"n{i}", "question": "",
                        "sections": [],
                        "cites": [ids[i - 1]] if i else []}
                  for i, cid in enumerate(ids)}
        c, order = CM.build_mindmap(E, "軸卡", logs, decomp,
                                    lambda cid: None)
        self.assertEqual(len(order), n)
        self.assertEqual(
            len([x for x in c["nodes"] if x.get("color") == CM.COLOR_HUB]), n)

    def test_root_degrades_to_text_without_mirror(self):
        c, _ = self.build(limit=1)
        root = next(n for n in c["nodes"] if n["id"] == PCV._nid(E, "mm-root"))
        self.assertEqual(root["type"], "text")
        c2, _ = CM.build_mindmap(E, "軸卡", LOGS, decomp_fixture(),
                                 lambda cid: {E: "Projects/軸卡.md"}.get(cid),
                                 limit=1)
        root2 = next(n for n in c2["nodes"] if n["id"] == PCV._nid(E, "mm-root"))
        self.assertEqual(root2["type"], "file")


class TestChainMode(unittest.TestCase):
    def sections(self):
        return CM.chain_sections(
            [h(1, "卡標題"), p("header back-ref（第一個 H2 前，應丟棄）"),
             h(2, "現狀（一眼掌握）"), p("現狀內文"),
             h(2, "實驗統整(一)"), p("引言"),
             h(3, "E0 baseline"), p("e0 內文"),
             h(3, "E1 sweep"), p("e1 內文"),
             h(2, "📜 log 時間線"), p("📗 …"),
             h(2, "下一步 / 計畫"), p("todo")], txt)

    def test_chain_sections_structure_and_skips(self):
        secs = self.sections()
        self.assertEqual([s[0] for s in secs],
                         ["現狀（一眼掌握）", "實驗統整(一)", "下一步 / 計畫"])
        h2, lead, subs = secs[1]
        self.assertEqual([txt(n) for n in lead], ["引言"])
        self.assertEqual([t for t, _ in subs], ["E0 baseline", "E1 sweep"])
        # header content before the first H2 dropped
        self.assertEqual([txt(n) for n in secs[0][1]], ["現狀內文"])

    def test_section_color_roles(self):
        self.assertEqual(CM.section_color("現狀（一眼掌握）"), "4")
        self.assertEqual(CM.section_color("Findings / 設計理路"), "4")
        self.assertEqual(CM.section_color("實驗統整(七)"), "3")
        self.assertEqual(CM.section_color("方法(Method)"), "5")
        self.assertEqual(CM.section_color("🔍 研究漏洞與發想"), "1")
        self.assertEqual(CM.section_color("下一步 / 計畫"), "1")
        self.assertIsNone(CM.section_color("其他雜項"))

    def test_numbering_prefixes_normalized_digit_safe(self):
        self.assertEqual(CM.section_color("1. 現狀"), "4")
        self.assertEqual(CM.section_color("01 方法"), "5")
        self.assertEqual(CM.section_color("（一）實驗統整"), "3")
        # digit-safe: a meaningful leading digit is NOT a numbering prefix
        self.assertEqual(CM._norm_heading("3D 視覺化"), "3D 視覺化")
        # numbered timeline heading still skipped by chain_sections
        secs = CM.chain_sections(
            [h(2, "📜 1. log 時間線"), p("x"), h(2, "現狀"), p("y")], txt)
        self.assertEqual([s[0] for s in secs], ["現狀"])

    def build(self, mapping=None):
        per_card = [(E, "", self.sections()),
                    (L1, "續1", CM.chain_sections(
                        [h(1, "卡 · 續 1"), p("back-ref"),
                         h(2, "實驗統整(二)"), h(3, "E2"), p("e2")], txt))]
        return CM.build_chainmap(E, "軸卡", per_card,
                                 lambda cid: (mapping or {}).get(cid),
                                 txt_of=txt)

    def test_chainmap_topology(self):
        c = self.build()
        root_id = PCV._nid(E, "mm-root")
        hubs = [n for n in c["nodes"] if n["x"] == 0]
        self.assertEqual(len(hubs), 4)               # 3 (entry) + 1 (續1)
        pairs = {(e["fromNode"], e["toNode"]) for e in c["edges"]}
        for hub in hubs:
            self.assertIn((root_id, hub["id"]), pairs)
        cont_hub = next(n for n in hubs if "〔續1〕" in n["text"])
        self.assertIn("實驗統整(二)", cont_hub["text"])
        leaves = [n for n in c["nodes"] if n["x"] > 0]
        self.assertEqual(len(leaves), 3)             # E0, E1, E2

    def test_hub_without_subs_carries_excerpt_no_leaf(self):
        c = self.build()
        hub = next(n for n in c["nodes"] if "現狀（一眼掌握）" in n.get("text", ""))
        self.assertIn("現狀內文", hub["text"])
        self.assertEqual(hub["height"], CM.LEAF_H)   # compact, no leaves

    def test_ids_deterministic_and_unique_with_dup_titles(self):
        per_card = [(E, "", CM.chain_sections(
            [h(2, "實驗"), h(3, "同名"), p("a"), h(3, "同名"), p("b"),
             h(2, "實驗"), h(3, "同名"), p("c")], txt))]
        c1 = CM.build_chainmap(E, "軸卡", per_card, lambda cid: None,
                               txt_of=txt)
        c2 = CM.build_chainmap(E, "軸卡", per_card, lambda cid: None,
                               txt_of=txt)
        ids1 = sorted(n["id"] for n in c1["nodes"])
        self.assertEqual(ids1, sorted(n["id"] for n in c2["nodes"]))
        self.assertEqual(len(ids1), len(set(ids1)))  # dup titles → unique ids

    def test_no_vertical_overlap_in_columns(self):
        c = self.build()
        from collections import defaultdict
        cols = defaultdict(list)
        for n in c["nodes"]:
            cols[n["x"]].append((n["y"], n["y"] + n["height"]))
        for spans in cols.values():
            spans.sort()
            for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
                self.assertLessEqual(a1, b0)

    def test_consecutive_leafless_hubs_do_not_overlap(self):
        # leafless hubs render at LEAF_H — a run of them (🔍/下一步/發想/
        # 待補 tails) used to overflow their SEC_HUB_H slots
        per_card = [(E, "", CM.chain_sections(
            [h(2, "🔍 研究漏洞與發想"), p("a"),
             h(2, "下一步 / 計畫"), p("b"),
             h(2, "發想 / 未探索"), p("c"),
             h(2, "待補 / 仍待確認"), p("d")], txt))]
        c = CM.build_chainmap(E, "軸卡", per_card, lambda cid: None,
                              txt_of=txt)
        spans = sorted((n["y"], n["y"] + n["height"])
                       for n in c["nodes"] if n["x"] == 0)
        for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
            self.assertLessEqual(a1, b0)


class TestStoryMode(unittest.TestCase):
    def graph(self):
        nodes = [
            {"id": "idea", "kind": "idea", "label": "想法", "text": "t"},
            {"id": "exp", "kind": "experiment", "label": "實驗", "text": "t",
             "anchor": "統整(一)", "date": "07-01"},
            {"id": "res", "kind": "result", "label": "結果", "text": "t"},
            {"id": "pivot", "kind": "pivot", "label": "轉向", "text": "t"},
            {"id": "find", "kind": "finding", "label": "發現", "text": "t"},
        ]
        edges = [
            {"from": "idea", "to": "exp", "label": "所以"},
            {"from": "exp", "to": "res"},
            {"from": "res", "to": "pivot", "label": "撞牆"},
            {"from": "res", "to": "find"},        # branch
            {"from": "pivot", "to": "find"},      # merge (diamond)
        ]
        return nodes, edges

    def test_layers_longest_path_diamond(self):
        nodes, edges = self.graph()
        layer = CM.story_layers(nodes, edges)
        self.assertEqual([layer[i] for i in
                          ("idea", "exp", "res", "pivot", "find")],
                         [0, 1, 2, 3, 4])      # find takes the LONGEST path

    def test_cycle_stall_force_places_deterministically(self):
        nodes = [{"id": "a"}, {"id": "b"}]
        layer = CM.story_layers(nodes, [{"from": "a", "to": "b"},
                                        {"from": "b", "to": "a"}])
        self.assertEqual(layer, {"a": 0, "b": 1})   # input order wins

    def test_build_root_sources_colors_labels(self):
        nodes, edges = self.graph()
        c, order = CM.build_storymap(E, "軸卡", nodes, edges,
                                     lambda cid: None)
        self.assertEqual(order, [n["id"] for n in nodes])
        by_id = {n["id"]: n for n in c["nodes"]}
        root_id = PCV._nid(E, "mm-root")
        pairs = {(e["fromNode"], e["toNode"]): e for e in c["edges"]}
        # only the true source hangs off the root
        sid = PCV._nid(E, "mm-story:idea")
        self.assertIn((root_id, sid), pairs)
        self.assertEqual(sum(1 for f, t in pairs if f == root_id), 1)
        # kinds → colors/icons; labels pass through
        self.assertEqual(by_id[sid]["color"], "2")
        self.assertIn("💡", by_id[sid]["text"])
        exp_node = by_id[PCV._nid(E, "mm-story:exp")]
        self.assertEqual(exp_node["color"], "3")
        self.assertIn("〔統整(一)〕", exp_node["text"])
        self.assertIn("07-01", exp_node["text"])
        self.assertEqual(
            pairs[(sid, PCV._nid(E, "mm-story:exp"))].get("label"), "所以")
        # result kind is uncolored
        self.assertNotIn("color", by_id[PCV._nid(E, "mm-story:res")])

    def test_limit_prefix_is_node_id_subset(self):
        nodes, edges = self.graph()
        c2, o2 = CM.build_storymap(E, "軸卡", nodes, edges,
                                   lambda cid: None, limit=2)
        c5, _ = CM.build_storymap(E, "軸卡", nodes, edges, lambda cid: None)
        self.assertEqual(o2, ["idea", "exp"])
        self.assertTrue({n["id"] for n in c2["nodes"]}
                        <= {n["id"] for n in c5["nodes"]})

    def test_no_overlap_and_unique_edge_ids(self):
        nodes, edges = self.graph()
        c, _ = CM.build_storymap(E, "軸卡", nodes, edges, lambda cid: None)
        from collections import defaultdict
        cols = defaultdict(list)
        for n in c["nodes"]:
            cols[n["x"]].append((n["y"], n["y"] + n["height"]))
        for spans in cols.values():
            spans.sort()
            for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
                self.assertLessEqual(a1, b0)
        ids = [e["id"] for e in c["edges"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_parallel_edges_get_distinct_ids(self):
        nodes = [{"id": "a", "kind": "idea", "label": "a", "text": ""},
                 {"id": "b", "kind": "result", "label": "b", "text": ""}]
        edges = [{"from": "a", "to": "b", "label": "所以"},
                 {"from": "a", "to": "b", "label": "但是"}]
        c, _ = CM.build_storymap(E, "軸卡", nodes, edges, lambda cid: None)
        ids = [e["id"] for e in c["edges"]]
        self.assertEqual(len(ids), len(set(ids)))
        labels = {e.get("label") for e in c["edges"] if e.get("label")}
        self.assertEqual(labels, {"所以", "但是"})

    def test_cycle_component_stays_attached_to_root(self):
        # pure cycle a↔b has no in-degree-0 node — the root must still
        # reach it (via the force-seated layer-0 node)
        nodes = [{"id": "a", "kind": "idea", "label": "a", "text": ""},
                 {"id": "b", "kind": "result", "label": "b", "text": ""}]
        edges = [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]
        c, _ = CM.build_storymap(E, "軸卡", nodes, edges, lambda cid: None)
        pairs = {(e["fromNode"], e["toNode"]) for e in c["edges"]}
        self.assertIn((PCV._nid(E, "mm-root"), PCV._nid(E, "mm-story:a")),
                      pairs)

    def test_flow_tracking_straight_chain_stays_one_lane(self):
        nodes = [{"id": f"n{i}", "kind": "result", "label": str(i),
                  "text": ""} for i in range(5)]
        edges = [{"from": f"n{i}", "to": f"n{i+1}"} for i in range(4)]
        c, _ = CM.build_storymap(E, "軸卡", nodes, edges, lambda cid: None)
        ys = {n["y"] for n in c["nodes"]
              if n["id"] not in (PCV._nid(E, "mm-root"),
                                 PCV._nid(E, "mm-legend"))}
        self.assertEqual(len(ys), 1)              # a chain is a straight lane

    def test_flow_tracking_branches_fan_around_parent(self):
        nodes = [{"id": "p", "kind": "idea", "label": "p", "text": ""},
                 {"id": "c1", "kind": "result", "label": "c1", "text": ""},
                 {"id": "c2", "kind": "result", "label": "c2", "text": ""}]
        edges = [{"from": "p", "to": "c1"}, {"from": "p", "to": "c2"}]
        c, _ = CM.build_storymap(E, "軸卡", nodes, edges, lambda cid: None)
        by = {n["id"]: n for n in c["nodes"]}
        y_p = by[PCV._nid(E, "mm-story:p")]["y"]
        y1 = by[PCV._nid(E, "mm-story:c1")]["y"]
        y2 = by[PCV._nid(E, "mm-story:c2")]["y"]
        self.assertEqual(y1, y_p)                 # first child on the lane
        self.assertGreaterEqual(y2, y1 + CM.STORY_H + CM.VGAP)  # fans down

    def test_long_edges_take_the_bottom_bypass(self):
        nodes, edges = self.graph()
        c, _ = CM.build_storymap(E, "軸卡", nodes, edges, lambda cid: None)
        sides = {}
        hub = lambda s: PCV._nid(E, f"mm-story:{s}")  # noqa: E731
        for e in c["edges"]:
            sides[(e["fromNode"], e["toNode"])] = (e["fromSide"], e["toSide"])
        # res(L2)→find(L4) spans 2 layers → bypass; adjacent stays lateral
        self.assertEqual(sides[(hub("res"), hub("find"))],
                         ("bottom", "bottom"))
        self.assertEqual(sides[(hub("idea"), hub("exp"))], ("right", "left"))

    def test_layout_normalized_to_top_zero(self):
        nodes, edges = self.graph()
        c, _ = CM.build_storymap(E, "軸卡", nodes, edges, lambda cid: None)
        tops = [n["y"] for n in c["nodes"]
                if n["id"] not in (PCV._nid(E, "mm-root"),
                                   PCV._nid(E, "mm-legend"))]
        self.assertEqual(min(tops), 0)

    def test_legend_present_above_graph_in_all_modes(self):
        lid = PCV._nid(E, "mm-legend")
        # story
        nodes, edges = self.graph()
        c, _ = CM.build_storymap(E, "軸卡", nodes, edges, lambda cid: None)
        leg = next(n for n in c["nodes"] if n["id"] == lid)
        self.assertLess(leg["y"] + leg["height"], 0)     # fully above content
        self.assertIn("🟨 🧪 實驗", leg["text"])
        self.assertNotIn("color", leg)
        # logs
        c2, _ = CM.build_mindmap(E, "軸卡", LOGS, decomp_fixture(),
                                 lambda cid: None)
        leg2 = next(n for n in c2["nodes"] if n["id"] == lid)
        self.assertIn("🟦 log 卡（hub）", leg2["text"])
        # chain
        per_card = [(E, "", CM.chain_sections([h(2, "現狀"), p("x")], txt))]
        c3 = CM.build_chainmap(E, "軸卡", per_card, lambda cid: None,
                               txt_of=txt)
        leg3 = next(n for n in c3["nodes"] if n["id"] == lid)
        self.assertIn("🟨 實驗統整", leg3["text"])

    def staged_graph(self):
        nodes = [
            {"id": "a1", "kind": "idea", "label": "a1", "text": "",
             "stage": "第1幕"},
            {"id": "a2", "kind": "result", "label": "a2", "text": ""},
            {"id": "b1", "kind": "pivot", "label": "b1", "text": "",
             "stage": "第2幕"},
            {"id": "b2", "kind": "finding", "label": "b2", "text": ""},
        ]
        edges = [{"from": "a1", "to": "a2"},
                 {"from": "a2", "to": "b1", "label": "換幕"},
                 {"from": "b1", "to": "b2"}]
        return nodes, edges

    def test_stage_inheritance_only_boundaries_annotated(self):
        nodes, _ = self.staged_graph()
        stage_of, order = CM.story_stages(nodes)
        self.assertEqual(order, ["第1幕", "第2幕"])
        self.assertEqual(stage_of["a2"], "第1幕")     # inherited
        self.assertEqual(stage_of["b2"], "第2幕")

    def test_rows_wrap_x_restarts_and_offset_down(self):
        nodes, edges = self.staged_graph()
        c, _ = CM.build_storymap(E, "軸卡", nodes, edges, lambda cid: None)
        by = {n["id"]: n for n in c["nodes"]}
        sid = lambda s: PCV._nid(E, f"mm-story:{s}")  # noqa: E731
        # row 2 wraps: b1 back at x=0 despite following a2 in the narrative
        self.assertEqual(by[sid("b1")]["x"], 0)
        self.assertGreater(by[sid("b1")]["y"],
                           by[sid("a2")]["y"] + CM.STORY_H)
        # stage headers present at the left column, above their rows
        h1 = by[PCV._nid(E, "mm-stage:第1幕")]
        h2 = by[PCV._nid(E, "mm-stage:第2幕")]
        self.assertEqual(h1["x"], -(CM.STORY_W + CM.STORY_HGAP))
        self.assertLess(h1["y"], by[sid("a1")]["y"])
        self.assertLess(h2["y"], by[sid("b1")]["y"])
        self.assertIn("第2幕", h2["text"])

    def test_cross_stage_edge_flows_down(self):
        nodes, edges = self.staged_graph()
        c, _ = CM.build_storymap(E, "軸卡", nodes, edges, lambda cid: None)
        sid = lambda s: PCV._nid(E, f"mm-story:{s}")  # noqa: E731
        sides = {(e["fromNode"], e["toNode"]): (e["fromSide"], e["toSide"])
                 for e in c["edges"]}
        self.assertEqual(sides[(sid("a2"), sid("b1"))], ("bottom", "top"))
        self.assertEqual(sides[(sid("a1"), sid("a2"))], ("right", "left"))
        # root connects ONLY the first row's sources (b1 is a continuation)
        pairs = set(sides)
        self.assertIn((PCV._nid(E, "mm-root"), sid("a1")), pairs)
        self.assertNotIn((PCV._nid(E, "mm-root"), sid("b1")), pairs)

    def test_unstaged_graph_stays_single_row(self):
        nodes, edges = self.graph()
        c, _ = CM.build_storymap(E, "軸卡", nodes, edges, lambda cid: None)
        self.assertFalse([n for n in c["nodes"]
                          if "mm-stage" in str(n.get("text", ""))
                          or n["id"] == PCV._nid(E, "mm-stage:")])
        # x still spans multiple layers (no wrap)
        xs = {n["x"] for n in c["nodes"]}
        self.assertGreater(len(xs), 3)

    def test_graph_validation(self):
        import tempfile
        import os as _os
        bad1 = {"nodes": [{"id": "a"}, {"id": "a"}], "edges": []}
        bad2 = {"nodes": [{"id": "a"}], "edges": [{"from": "a", "to": "x"}]}
        for bad in (bad1, bad2):
            fd, p = tempfile.mkstemp(suffix=".json")
            with _os.fdopen(fd, "w") as f:
                json.dump(bad, f)
            try:
                with self.assertRaises(ValueError):
                    CM.load_story_graph(p)
            finally:
                _os.unlink(p)

    def test_long_edge_label_warns_but_never_truncates(self):
        import tempfile
        import os as _os
        g = {"nodes": [{"id": "a"}, {"id": "b"}],
             "edges": [{"from": "a", "to": "b",
                        "label": "這個連接詞實在有夠長會被節點蓋掉"},
                       {"from": "b", "to": "a", "label": "所以"}]}
        fd, p = tempfile.mkstemp(suffix=".json")
        with _os.fdopen(fd, "w") as f:
            json.dump(g, f, ensure_ascii=False)
        try:
            nodes, edges, warns, meta = CM.load_story_graph(p)
        finally:
            _os.unlink(p)
        self.assertEqual(len(warns), 1)
        self.assertIn("label 過長", warns[0])
        # the label itself is untouched (author owns the words)
        self.assertEqual(edges[0]["label"], "這個連接詞實在有夠長會被節點蓋掉")
        # display-unit math: CJK doubles, latin singles
        self.assertEqual(CM._disp_units("追 frontier"), 11)
        self.assertEqual(CM._disp_units("換場地再判"), 10)


class TestStoryCoverage(unittest.TestCase):
    LOGS_TL = [{"log": L1, "date": "2026-07-19", "summary": "已入圖"},
               {"log": L2, "date": "2026-07-22", "summary": "新 log 未入圖"}]
    SECS = [(E, ["現狀（一眼掌握）", "實驗統整(一)：sweep",
                 "實驗統整(八)：新段", "方法(Method)"])]

    def graph_nodes(self):
        return [{"id": "a", "anchor": "現狀", "sources": [L1]},
                {"id": "b", "anchor": "實驗統整(一)"}]

    def test_uncovered_logs_by_sources(self):
        cov = CM.story_coverage(self.graph_nodes(), self.LOGS_TL, self.SECS)
        self.assertEqual([u["log"] for u in cov["uncovered_logs"]], [L2[:8]])
        self.assertIn("新 log 未入圖", cov["uncovered_logs"][0]["summary"])

    def test_source_prefix_counts_as_covered(self):
        x1 = "11111111-0000-4000-8000-000000000001"
        x2 = "22222222-0000-4000-8000-000000000002"
        tl = [{"log": x1, "date": "", "summary": ""},
              {"log": x2, "date": "", "summary": ""}]
        nodes = [{"id": "a", "sources": [x2[:12]]}]     # unambiguous prefix
        cov = CM.story_coverage(nodes, tl, [])
        self.assertEqual([u["log"] for u in cov["uncovered_logs"]], [x1[:8]])
        # a too-short prefix (<8) is ignored, never a wildcard
        nodes = [{"id": "a", "sources": ["1111"]}]
        cov = CM.story_coverage(nodes, tl, [])
        self.assertEqual(len(cov["uncovered_logs"]), 2)

    def test_uncovered_sections_and_ignore(self):
        cov = CM.story_coverage(self.graph_nodes(), [], self.SECS)
        titles = [u["section"] for u in cov["uncovered_sections"]]
        self.assertIn("實驗統整(八)：新段", titles)   # merge 後新長的段
        self.assertIn("方法(Method)", titles)
        self.assertNotIn("現狀（一眼掌握）", titles)   # anchor 蓋掉
        cov2 = CM.story_coverage(self.graph_nodes(), [], self.SECS,
                                 ignore=["方法"])
        titles2 = [u["section"] for u in cov2["uncovered_sections"]]
        self.assertNotIn("方法(Method)", titles2)
        self.assertIn("實驗統整(八)：新段", titles2)   # ignore 不誤傷

    def test_ambiguous_prefix_and_zero_hit_source_warn(self):
        tl = [{"log": L1, "date": "", "summary": ""},
              {"log": L2, "date": "", "summary": ""}]
        # L1/L2 share their first 12 chars → ambiguous prefix
        nodes = [{"id": "a", "sources": [L1[:12],
                                         "99999999-dead-beef-0000-000000000000"]}]
        cov = CM.story_coverage(nodes, tl, [])
        self.assertEqual(cov["uncovered_logs"], [])     # both claimed anyway
        warns = "\n".join(cov["source_warnings"])
        self.assertIn("命中 2 張", warns)
        self.assertIn("沒命中任何", warns)

    def test_multi_part_anchor_covers_several_sections(self):
        nodes = [{"id": "a", "anchor": "🔍 研究漏洞・下一步・發想"}]
        secs = [(E, ["🔍 研究漏洞與發想", "下一步 / 計畫", "發想 / 未探索",
                     "待補 / 仍待確認"])]
        cov = CM.story_coverage(nodes, [], secs)
        titles = [u["section"] for u in cov["uncovered_sections"]]
        self.assertEqual(titles, ["待補 / 仍待確認"])

    def test_audit_node_only_when_dirty(self):
        self.assertIsNone(CM.audit_node(
            E, {"uncovered_logs": [], "uncovered_sections": []}, 0))
        n = CM.audit_node(E, {
            "uncovered_logs": [{"log": "12345678", "date": "2026-07-22",
                                "summary": "新 log 未入圖"}],
            "uncovered_sections": [{"card": "abcdefab",
                                    "section": "實驗統整(八)：新段"}]}, -260)
        self.assertEqual(n["color"], "1")
        self.assertEqual(n["id"], PCV._nid(E, "mm-audit"))
        self.assertLess(n["y"] + n["height"], 0)      # above the content
        self.assertIn("07-22 新 log 未入圖", n["text"])
        self.assertIn("實驗統整(八)", n["text"])
        self.assertIn("重渲染即消失", n["text"])

    def test_audit_node_truncates_long_lists(self):
        logs = [{"log": f"{i:08d}", "date": "2026-07-22",
                 "summary": f"log{i}"} for i in range(12)]
        n = CM.audit_node(E, {"uncovered_logs": logs,
                              "uncovered_sections": []}, 0)
        self.assertIn("…等共 12 張", n["text"])
        self.assertLessEqual(n["text"].count("・"), 8)


import json  # noqa: E402  (used by TestStoryMode.test_graph_validation)
import tempfile  # noqa: E402


class TestModeDetectAndResolve(unittest.TestCase):
    """A bare re-run EXTENDS the existing canvas in its own mode instead
    of resetting to logs — detect_existing_mode / resolve_render_mode."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cm-mode-")
        self.canvas = os.path.join(self.tmp, "軸卡·脈絡心智圖.canvas")
        self.graph = os.path.join(self.tmp, "軸卡·脈絡心智圖.graph.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_legend(self, mode):
        leg = CM.legend_node(E, mode, 0)
        json.dump({"nodes": [leg], "edges": []},
                  open(self.canvas, "w"), ensure_ascii=False)

    def test_none_when_no_canvas(self):
        self.assertIsNone(CM.detect_existing_mode(self.canvas, E))

    def test_legend_is_authoritative_over_stale_graph(self):
        # story→chain/logs switch leaves .graph.json behind; the LEGEND
        # (rewritten each render) is the source of truth, so a lingering
        # graph must NOT drag detection back to story
        self._write_legend("logs")
        json.dump({"nodes": []}, open(self.graph, "w"))
        self.assertEqual(CM.detect_existing_mode(self.canvas, E), "logs")

    def test_legend_signatures_per_mode(self):
        for mode in ("logs", "chain", "story"):
            self._write_legend(mode)          # no graph.json sibling
            self.assertEqual(
                CM.detect_existing_mode(self.canvas, E), mode,
                f"{mode} legend misread")

    def test_foreign_canvas_is_none(self):
        json.dump({"nodes": [{"id": "x", "type": "text", "text": "手排的"}],
                   "edges": []}, open(self.canvas, "w"))
        self.assertIsNone(CM.detect_existing_mode(self.canvas, E))

    def test_resolve_explicit_mode_wins(self):
        self._write_legend("chain")
        self.assertEqual(
            CM.resolve_render_mode(E, "logs", None, self.canvas, self.graph),
            ("logs", None, False))

    def test_resolve_graph_implies_story(self):
        self.assertEqual(
            CM.resolve_render_mode(E, None, "g.json", self.canvas, self.graph),
            ("story", "g.json", False))

    def test_resolve_extends_detected_mode(self):
        self._write_legend("chain")
        self.assertEqual(
            CM.resolve_render_mode(E, None, None, self.canvas, self.graph),
            ("chain", None, True))

    def test_resolve_story_auto_adopts_graph(self):
        self._write_legend("story")
        json.dump({"nodes": []}, open(self.graph, "w"))
        mode, graph, ext = CM.resolve_render_mode(
            E, None, None, self.canvas, self.graph)
        self.assertEqual((mode, ext), ("story", True))
        self.assertEqual(graph, self.graph)

    def test_resolve_story_without_graph_raises(self):
        self._write_legend("story")           # story legend, graph.json gone
        with self.assertRaises(ValueError):
            CM.resolve_render_mode(E, None, None, self.canvas, self.graph)

    def test_resolve_switched_away_from_story_extends_new_mode(self):
        # P1 regression: build story (graph.json exists) → switch to chain
        # (legend now chain, graph.json lingers) → bare re-run must extend
        # CHAIN, not snap back to story on the stale graph
        self._write_legend("chain")
        json.dump({"nodes": []}, open(self.graph, "w"))
        self.assertEqual(
            CM.resolve_render_mode(E, None, None, self.canvas, self.graph),
            ("chain", None, True))

    def test_resolve_fresh_is_logs(self):
        self.assertEqual(
            CM.resolve_render_mode(E, None, None, self.canvas, self.graph),
            ("logs", None, False))


if __name__ == "__main__":
    unittest.main()
