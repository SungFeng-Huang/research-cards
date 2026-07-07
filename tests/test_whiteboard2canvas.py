"""whiteboard2canvas: All-Data backup -> JSON Canvas mirror on a temp vault."""
import json
import os
import sqlite3
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

def _pm_with_mentions(*card_ids):
    return json.dumps({"type": "doc", "content": [
        {"type": "paragraph", "attrs": {"id": "m"},
         "content": [{"type": "card", "attrs": {"cardId": c}}
                     for c in card_ids]}]})


ALL_DATA = {
    "whiteBoardList": [{"id": WB, "name": "測試板"}],
    "cardList": [
        # mention 去重（跟 explicit connection 同 pair）＋板外 mention 忽略
        {"id": "card-synced", "title": "My Paper", "isTrashed": False,
         "content": _pm_with_mentions("card-unsynced", "card-c", "card-offboard")},
        {"id": "card-unsynced", "title": "外部卡", "isTrashed": False,
         "content": "{}"},
        {"id": "card-c", "title": "第三卡", "isTrashed": False,
         "content": _pm_with_mentions("card-synced")},   # 與 card-synced 互指
        {"id": "card-trashed", "title": "垃圾卡", "isTrashed": True,
         "content": "{}"},
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
        {"id": "inst-c", "whiteboardId": WB, "cardId": "card-c",
         "x": 100, "y": 500, "width": 300, "height": 120, "color": "white"},
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
        self.assertEqual(rep["written"][0]["nodes"], 5)   # 3 cards + text + group
        self.assertEqual(rep["written"][0]["edges"], 2)   # explicit + mention
        self.assertEqual(rep["mention_edges"], 1)
        self.assertEqual(rep["skipped_trashed"], 1)
        self.assertEqual(rep["skipped_dangling_edges"], 1)
        self.assertEqual(sorted(rep["unsynced_cards"]), ["外部卡", "第三卡"])

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

        mention = [e for e in cv["edges"] if e["id"].startswith("mention:")]
        self.assertEqual(len(mention), 1)
        m = mention[0]
        # 互相 mention → 單一雙箭頭邊；由 card id 小的一方代表
        self.assertEqual((m["fromNode"], m["toNode"], m["fromEnd"]),
                         ("inst-c", "inst-a", "arrow"))
        # card-synced ↔ card-unsynced 已有 explicit connection → 不重畫
        self.assertFalse(any({e2["fromNode"], e2["toNode"]} == {"inst-a", "inst-b"}
                             for e2 in mention))

        e = [e2 for e2 in cv["edges"] if not e2["id"].startswith("mention:")][0]
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


def build_live_db(path, all_data, drop_column=None):
    """Synthesize a hepta.db carrying the same fixture as ALL_DATA."""
    ddl = {
        "whiteboard": ("id, name, is_trashed", "whiteBoardList",
                       lambda w: (w["id"], w["name"], 0)),
        "card": ("id, title, content, is_trashed", "cardList",
                 lambda c: (c["id"], c["title"], c.get("content"),
                            int(c["isTrashed"]))),
        "card_instance": ("id, whiteboard_id, card_id, x, y, width, height,"
                          " color, is_folded, folded_height", "cardInstances",
                          lambda i: (i["id"], i["whiteboardId"], i["cardId"],
                                     i["x"], i["y"], i["width"], i["height"],
                                     i.get("color"), int(i.get("isFolded") or 0),
                                     i.get("foldedHeight", -1))),
        "text_element": ("id, whiteboard_id, content, x, y, width, height",
                         "textElements",
                         lambda t: (t["id"], t["whiteboardId"], t["content"],
                                    t["x"], t["y"], t["width"], t["height"])),
        "section": ("id, whiteboard_id, title, color, x, y, width, height",
                    "sections",
                    lambda x: (x["id"], x["whiteboardId"], x["title"],
                               x.get("color"), x["x"], x["y"],
                               x["width"], x["height"])),
        "connection": ("id, whiteboard_id, begin_id, end_id, begin_pos,"
                       " end_pos, begin_style, end_style, color, description",
                       "connections",
                       lambda c: (c["id"], c["whiteboardId"], c["beginId"],
                                  c["endId"], c["beginPos"], c["endPos"],
                                  c["beginStyle"], c["endStyle"],
                                  c.get("color"), c.get("description"))),
    }
    db = sqlite3.connect(path)
    for table, (cols, key, rowfn) in ddl.items():
        collist = cols.split(", ")
        if drop_column and drop_column[0] == table:
            collist = [c for c in collist if c != drop_column[1]]
        db.execute(f"CREATE TABLE {table} ({', '.join(collist)})")
        if drop_column and drop_column[0] == table:
            continue
        for item in all_data.get(key, []):
            db.execute(f"INSERT INTO {table} VALUES "
                       f"({','.join('?' * len(collist))})", rowfn(item))
    db.commit()
    db.close()


class TestLiveSource(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hbcards-w2c-live-"))
        self.vault = self.tmp / "Vault"
        (self.vault / ".hepta-sync").mkdir(parents=True)
        (self.vault / ".hepta-sync" / "state.json").write_text(json.dumps(
            {"cards": {"card-synced": {"file": "My Paper",
                                       "collection": "papers"}}}))
        (self.tmp / "All-Data.json").write_text(
            json.dumps(ALL_DATA, ensure_ascii=False))
        build_live_db(self.tmp / "hepta.db", ALL_DATA)
        cfg = {"backend": "obsidian",
               "heptabase": {"workspace_id": "ws-123", "collections": {}},
               "obsidian": {"vault": str(self.vault),
                            "folders": {"papers": "Study/Papers"},
                            "graph": {"mirror_whiteboards":
                                      {WB: "Maps/測試板.canvas"}}}}
        self.cfg = self.tmp / "config.json"
        self.cfg.write_text(json.dumps(cfg, ensure_ascii=False))

    def run_script(self, *extra, expect_ok=True):
        env = dict(os.environ, HEPTABASE_CARDS_CONFIG=str(self.cfg))
        env.pop("RESEARCH_CARDS_CONFIG", None)
        r = subprocess.run([sys.executable, SCRIPT, *extra], env=env,
                           capture_output=True, text=True)
        if expect_ok:
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
        return r

    def test_live_equals_backup(self):
        self.run_script("--live-db", str(self.tmp / "hepta.db"))
        live = (self.vault / "Maps/測試板.canvas").read_bytes()
        self.run_script("--all-data", str(self.tmp / "All-Data.json"))
        self.assertEqual(live, (self.vault / "Maps/測試板.canvas").read_bytes())

    def test_schema_drift_fails_loudly_when_forced(self):
        build_live_db(self.tmp / "drift.db", ALL_DATA,
                      drop_column=("card_instance", "folded_height"))
        r = self.run_script("--live-db", str(self.tmp / "drift.db"),
                            expect_ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("schema", r.stderr)

    def _wire_default_sources(self, app_dir):
        cfg = json.loads(self.cfg.read_text())
        cfg["heptabase"]["app_data_dir"] = str(app_dir)
        cfg["heptabase"]["backup_dir"] = str(self.tmp)
        self.cfg.write_text(json.dumps(cfg, ensure_ascii=False))

    def test_wal_mode_with_open_writer(self):
        app = self.tmp / "app-wal"
        app.mkdir()
        build_live_db(app / "hepta.db", ALL_DATA)
        writer = sqlite3.connect(app / "hepta.db")
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("BEGIN")
        writer.execute(
            "INSERT INTO card VALUES ('uncommitted', 'x', '{}', 0)")
        try:
            self._wire_default_sources(app)
            r = self.run_script()
            rep = json.loads(r.stdout.splitlines()[-1])
            self.assertTrue(rep["source"].startswith("live:"))
            self.assertEqual(rep["written"][0]["nodes"], 5)
        finally:
            writer.rollback()
            writer.close()

    def test_default_mode_schema_drift_exits_nonzero(self):
        app = self.tmp / "app-drift"
        app.mkdir()
        build_live_db(app / "hepta.db", ALL_DATA,
                      drop_column=("section", "color"))
        self._wire_default_sources(app)  # 備份同時可用——仍必須大聲失敗
        r = self.run_script(expect_ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("schema", r.stderr)

    def test_default_mode_falls_back_when_live_absent(self):
        self._wire_default_sources(self.tmp / "no-such-dir")
        r = self.run_script()
        rep = json.loads(r.stdout.splitlines()[-1])
        self.assertTrue(rep["source"].endswith("All-Data.json"))
        self.assertEqual(rep["written"][0]["nodes"], 5)


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

    def _run_fixture(self, all_data, cfg_extra=None):
        tmp = Path(tempfile.mkdtemp(prefix="hbcards-w2c-var-"))
        vault = tmp / "Vault"
        (vault / ".hepta-sync").mkdir(parents=True)
        (vault / ".hepta-sync/state.json").write_text(json.dumps(
            {"cards": {"card-synced": {"file": "My Paper",
                                       "collection": "papers"}}}))
        (tmp / "All-Data.json").write_text(json.dumps(all_data, ensure_ascii=False))
        graph = {"mirror_whiteboards": {WB: "Maps/x.canvas"}}
        graph.update(cfg_extra or {})
        cfg = tmp / "config.json"
        cfg.write_text(json.dumps({
            "backend": "obsidian",
            "heptabase": {"workspace_id": "w", "collections": {}},
            "obsidian": {"vault": str(vault), "folders": {},
                         "graph": graph}}))
        env = dict(os.environ, HEPTABASE_CARDS_CONFIG=str(cfg))
        env.pop("RESEARCH_CARDS_CONFIG", None)
        r = subprocess.run([sys.executable, SCRIPT,
                            "--all-data", str(tmp / "All-Data.json")],
                           env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-400:]
        return json.loads((vault / "Maps/x.canvas").read_text())

    def test_mention_toggle_off(self):
        cv = self._run_fixture(ALL_DATA, {"mirror_mention_edges": False})
        self.assertEqual([e["id"] for e in cv["edges"]], ["edge-1"])

    def test_mention_all_pairs_for_multi_instance_card(self):
        import copy
        data = copy.deepcopy(ALL_DATA)
        data["cardInstances"].append(
            {"id": "inst-c2", "whiteboardId": WB, "cardId": "card-c",
             "x": 0, "y": 0, "width": 10, "height": 10, "color": "white"})
        cv = self._run_fixture(data)
        m = sorted(e["id"] for e in cv["edges"] if e["id"].startswith("mention:"))
        self.assertEqual(m, ["mention:inst-c2:inst-a", "mention:inst-c:inst-a"])

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
