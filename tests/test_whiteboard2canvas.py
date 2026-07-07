"""whiteboard2canvas: All-Data backup -> JSON Canvas mirror on a temp vault."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..",
                      "skills", "overview-graph", "scripts", "whiteboard2canvas.py")

WB = "wb-1"
PM = json.dumps({"type": "doc", "content": [
    {"type": "paragraph", "attrs": {"id": "p1"},
     "content": [{"type": "text", "text": "浮動說明"}]}]})

ALL_DATA = {
    "whiteBoardList": [{"id": WB, "name": "測試板"}],
    "cardList": [
        {"id": "card-synced", "title": "My Paper", "isTrashed": False},
        {"id": "card-unsynced", "title": "外部卡", "isTrashed": False},
        {"id": "card-trashed", "title": "垃圾卡", "isTrashed": True},
    ],
    "cardInstances": [
        {"id": "inst-a", "whiteboardId": WB, "cardId": "card-synced",
         "x": 10.4, "y": -20.6, "width": 520, "height": 300.4,
         "color": "blue", "isFolded": False, "foldedHeight": -1},
        {"id": "inst-b", "whiteboardId": WB, "cardId": "card-unsynced",
         "x": 700, "y": 0, "width": 520, "height": 200,
         "color": "white", "isFolded": True, "foldedHeight": 44},
        {"id": "inst-trash", "whiteboardId": WB, "cardId": "card-trashed",
         "x": 0, "y": 900, "width": 100, "height": 100, "color": "white"},
        {"id": "inst-elsewhere", "whiteboardId": "wb-other",
         "cardId": "card-synced", "x": 0, "y": 0, "width": 1, "height": 1},
    ],
    "textElements": [{"id": "text-1", "whiteboardId": WB, "content": PM,
                      "x": 1, "y": 2, "width": 30, "height": 40}],
    "sections": [{"id": "sec-1", "whiteboardId": WB, "title": "分區",
                  "color": "green", "x": -5, "y": -5,
                  "width": 640, "height": 480}],
    "sectionObjectRelations": [],
    "connections": [
        {"id": "edge-1", "whiteboardId": WB, "beginId": "inst-a",
         "endId": "inst-b", "beginPos": "right", "endPos": "auto",
         "beginStyle": "none", "endStyle": "default",
         "color": "red",
         # 真實備份中 description 是 PM doc 字串，須轉純文字
         "description": json.dumps({"type": "doc", "content": [
             {"type": "paragraph", "attrs": {"id": "d1"},
              "content": [{"type": "text", "text": "承接"}]}]})},
        {"id": "edge-dangling", "whiteboardId": WB, "beginId": "inst-a",
         "endId": "mindmap-x", "beginPos": "auto", "endPos": "auto",
         "beginStyle": "none", "endStyle": "default", "color": "white",
         "description": ""},
    ],
}


class TestWhiteboard2Canvas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="hbcards-w2c-"))
        cls.vault = cls.tmp / "Vault"
        (cls.vault / ".hepta-sync").mkdir(parents=True)
        (cls.vault / ".hepta-sync" / "state.json").write_text(json.dumps(
            {"cards": {"card-synced": {"file": "My Paper",
                                       "collection": "papers"}},
             "files": {}, "titles": {}}))
        (cls.tmp / "All-Data.json").write_text(
            json.dumps(ALL_DATA, ensure_ascii=False))
        cfg = {"backend": "obsidian",
               "heptabase": {"workspace_id": "ws-123", "collections": {}},
               "obsidian": {"vault": str(cls.vault),
                            "folders": {"papers": "Study/Papers"},
                            "graph": {"mirror_whiteboards":
                                      {WB: "Maps/測試板.canvas"}}}}
        cls.cfg = cls.tmp / "config.json"
        cls.cfg.write_text(json.dumps(cfg, ensure_ascii=False))

    def run_script(self, *extra):
        env = dict(os.environ, HEPTABASE_CARDS_CONFIG=str(self.cfg))
        env.pop("RESEARCH_CARDS_CONFIG", None)
        r = subprocess.run(
            [sys.executable, SCRIPT, "--all-data", str(self.tmp / "All-Data.json"),
             *extra], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        return json.loads(r.stdout.splitlines()[-1])

    def test_1_mirror(self):
        rep = self.run_script()
        self.assertEqual(rep["written"][0]["nodes"], 4)   # 2 cards + text + group
        self.assertEqual(rep["written"][0]["edges"], 1)
        self.assertEqual(rep["skipped_trashed"], 1)
        self.assertEqual(rep["skipped_dangling_edges"], 1)
        self.assertEqual(rep["unsynced_cards"], ["外部卡"])

        cv = json.loads((self.vault / "Maps/測試板.canvas").read_text())
        self.assertEqual(cv["nodes"][0]["type"], "group")  # z-order：group 在下層
        by_id = {n["id"]: n for n in cv["nodes"]}
        a = by_id["inst-a"]
        self.assertEqual((a["type"], a["file"], a["color"], a["x"], a["height"]),
                         ("file", "Study/Papers/My Paper.md", "5", 10, 300))
        b = by_id["inst-b"]
        self.assertEqual(b["type"], "text")
        self.assertIn("外部卡", b["text"])
        self.assertIn("https://app.heptabase.com/ws-123/card/card-unsynced",
                      b["text"])
        self.assertEqual(b["height"], 44)          # folded -> foldedHeight
        self.assertNotIn("color", b)               # white -> omitted
        sec = by_id["sec-1"]
        self.assertEqual((sec["type"], sec["label"], sec["color"]),
                         ("group", "分區", "4"))
        self.assertEqual(by_id["text-1"]["text"], "浮動說明")
        self.assertNotIn("inst-elsewhere", by_id)

        e = cv["edges"][0]
        self.assertEqual((e["fromNode"], e["toNode"], e["fromSide"],
                          e["color"], e["label"]),
                         ("inst-a", "inst-b", "right", "1", "承接"))
        self.assertNotIn("toSide", e)              # auto -> omitted
        self.assertNotIn("fromEnd", e)             # beginStyle none = default
        self.assertNotIn("toEnd", e)               # endStyle default = arrow

    def test_2_deterministic(self):
        self.run_script()
        first = (self.vault / "Maps/測試板.canvas").read_bytes()
        self.run_script()
        self.assertEqual(first, (self.vault / "Maps/測試板.canvas").read_bytes())

    def test_3_dry_run_writes_nothing(self):
        out = self.vault / "Maps/測試板.canvas"
        if out.exists():
            out.unlink()
        rep = self.run_script("--dry-run")
        self.assertTrue(rep["written"][0]["dry_run"])
        self.assertFalse(out.exists())


class TestEdgeCases(unittest.TestCase):
    def test_placeholder_strips_token_not_line(self):
        sys.path.insert(0, os.path.dirname(SCRIPT))
        os.environ.setdefault("HEPTABASE_CARDS_CONFIG", "/nonexistent.json")
        import importlib
        w2c = importlib.import_module("whiteboard2canvas")
        rep = {"text_convert_errors": 0, "text_placeholders_stripped": 0}
        pm = json.dumps({"type": "doc", "content": [
            {"type": "paragraph", "attrs": {"id": "p"},
             "content": [{"type": "text",
                          "text": "前%%HEPTA-CARD:xyz%%後"}]}]})
        self.assertEqual(w2c.pm_to_text(pm, rep), "前後")
        self.assertEqual(rep["text_placeholders_stripped"], 1)

    def test_all_missing_whiteboards_exit_nonzero(self):
        tmp = Path(tempfile.mkdtemp(prefix="hbcards-w2c-miss-"))
        (tmp / "Vault").mkdir()
        (tmp / "All-Data.json").write_text(json.dumps(
            {"whiteBoardList": [], "cardList": []}))
        cfg = tmp / "config.json"
        cfg.write_text(json.dumps({
            "backend": "obsidian",
            "obsidian": {"vault": str(tmp / "Vault"),
                         "graph": {"mirror_whiteboards":
                                   {"nope": "Maps/x.canvas"}}}}))
        env = dict(os.environ, HEPTABASE_CARDS_CONFIG=str(cfg))
        env.pop("RESEARCH_CARDS_CONFIG", None)
        r = subprocess.run([sys.executable, SCRIPT,
                            "--all-data", str(tmp / "All-Data.json")],
                           env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not_in_backup", r.stdout)


if __name__ == "__main__":
    unittest.main()
