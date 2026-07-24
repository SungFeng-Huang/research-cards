"""Lifecycle and append-safety contract for story graph proposals."""
import copy
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "skills" / "project-card-canvas"
spec = importlib.util.spec_from_file_location("story_graph_under_test",
                                              HERE / "story_graph.py")
SG = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SG)


def graph():
    return {
        "nodes": [
            {"id": "history", "kind": "finding", "label": "已知",
             "text": "不可改", "sources": ["11111111"]},
            {"id": "hole", "kind": "open", "label": "開放洞",
             "text": "待查", "sources": ["22222222"],
             "semantic": "open_hole",
             "lifecycle": {"state": "open", "revision": 0}},
        ],
        "edges": [{"from": "history", "to": "hole", "label": "留下"}],
        "coverage_ignore": ["方法"],
    }


class TestLifecycleMigration(unittest.TestCase):
    def test_marks_all_legacy_open_nodes_by_semantics(self):
        g = {"nodes": [
            {"id": "a", "kind": "open", "label": "進行中"},
            {"id": "b", "kind": "open", "label": "開放洞"},
            {"id": "c", "kind": "open", "label": "下一步"},
            {"id": "d", "kind": "open", "label": "待捕"},
        ], "edges": []}
        out, changed = SG.migrate(g)
        self.assertEqual(changed, ["a", "b", "c", "d"])
        self.assertEqual([n["semantic"] for n in out["nodes"]],
                         ["open_thread", "open_hole",
                          "next_step", "pending_capture"])
        self.assertNotIn("semantic", g["nodes"][0])  # pure migration


class TestRevisionGuard(unittest.TestCase):
    def test_allows_lifecycle_resolution_and_tail_append(self):
        before = graph()
        after = copy.deepcopy(before)
        after["nodes"][1].update({
            "kind": "finding", "label": "洞已關閉", "text": "驗證完成",
            "sources": ["22222222", "33333333"],
            "lifecycle": {"state": "resolved", "revision": 1},
        })
        after["nodes"].append(
            {"id": "next", "kind": "open", "label": "下一步",
             "semantic": "next_step",
             "lifecycle": {"state": "open", "revision": 0}})
        after["edges"].append(
            {"from": "hole", "to": "next", "label": "接著"})
        rep = SG.validate_revision(before, after)
        self.assertEqual(rep["changed_lifecycle_nodes"], ["hole"])
        self.assertEqual(rep["appended_nodes"], ["next"])

    def test_rejects_change_to_unmarked_history(self):
        before = graph()
        after = copy.deepcopy(before)
        after["nodes"][0]["text"] = "偷偷改"
        with self.assertRaisesRegex(ValueError, "未標 lifecycle"):
            SG.validate_revision(before, after)

    def test_rejects_semantic_change_or_source_removal(self):
        before = graph()
        for mutate in (
            lambda n: n.update(
                semantic="open_thread",
                lifecycle={"state": "active", "revision": 1}),
            lambda n: n.update(
                sources=[],
                lifecycle={"state": "active", "revision": 1}),
        ):
            after = copy.deepcopy(before)
            mutate(after["nodes"][1])
            with self.assertRaises(ValueError):
                SG.validate_revision(before, after)

    def test_rejects_edge_or_node_rewrite_and_closed_reopen(self):
        before = graph()
        variants = []
        edge = copy.deepcopy(before)
        edge["edges"][0]["label"] = "改邊"
        variants.append(edge)
        order = copy.deepcopy(before)
        order["nodes"].reverse()
        variants.append(order)
        closed = copy.deepcopy(before)
        closed["nodes"][1]["kind"] = "finding"
        closed["nodes"][1]["lifecycle"] = {
            "state": "resolved", "revision": 1}
        reopened = copy.deepcopy(closed)
        reopened["nodes"][1]["kind"] = "open"
        reopened["nodes"][1]["lifecycle"] = {
            "state": "open", "revision": 2}
        with self.assertRaisesRegex(ValueError, "已結案"):
            SG.validate_revision(closed, reopened)
        for after in variants:
            with self.assertRaises(ValueError):
                SG.validate_revision(before, after)

    def test_top_level_lists_are_append_only(self):
        before = graph()
        after = copy.deepcopy(before)
        after["coverage_ignore"].append("參考")
        SG.validate_revision(before, after)
        after["coverage_ignore"][0] = "偷換"
        with self.assertRaises(ValueError):
            SG.validate_revision(before, after)


if __name__ == "__main__":
    unittest.main()
