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


class TestBuildCanvas(unittest.TestCase):
    def build(self, entries, mapping=None, chain=None):
        mapping = mapping or {}
        return PC.build_canvas(E, "專案", chain or [E], entries,
                               lambda cid: mapping.get(cid))

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


if __name__ == "__main__":
    unittest.main()
