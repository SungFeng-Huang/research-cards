"""append_card spill metadata: project tag + entry-pointer relation.

Pure-logic tests — every CLI touchpoint (append_card.sh) is monkeypatched;
no Heptabase, no bridge, no network. Covers find_relation_pid, the
set_project_relation flow on both transports (hb / heptabase), hb create()'s
tag-add graceful degradation (old client without the verb), and
append_or_spill's tagged/related wiring on the spill path.
"""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "skills", "project-card-log"))
# Isolate from any real user config (append_card.load_cfg -> {} -> defaults).
os.environ["RESEARCH_CARDS_CONFIG"] = "/nonexistent/research-cards-test.json"
os.environ.pop("HEPTABASE_CARDS_CONFIG", None)
import append_card as A  # noqa: E402

ENTRY = "f359e76c-0000-4000-8000-000000000001"
CHILD = "f2597587-0000-4000-8000-000000000002"
PID = "cca63a2e-0000-4000-8000-000000000003"

PROPS_WITH_RELATION = json.dumps({"cardId": CHILD, "tags": [
    {"tagId": "T1", "tagName": "project", "properties": [
        {"id": "PID-S", "name": "Status", "type": "select", "value": None},
        {"id": PID, "name": "project", "type": "relation", "value": []}]}]})

PROPS_NO_RELATION = json.dumps({"cardId": CHILD, "tags": [
    {"tagId": "T1", "tagName": "project", "properties": [
        {"id": "PID-S", "name": "Status", "type": "select", "value": None}]}]})


def cp(rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


class ShRecorder:
    """Dispatch fake CLI responses by an args-prefix key; record every call."""
    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, args, timeout=60):
        self.calls.append(list(args))
        joined = " ".join(args)
        for key, resp in self.table.items():
            if joined.startswith(key):
                return resp(args) if callable(resp) else resp
        return cp(1, "", f"no fake for: {joined}")

    def verb_calls(self, key):
        return [c for c in self.calls if " ".join(c).startswith(key)]


class TestSetProjectRelation(unittest.TestCase):
    def test_hb_sets_relation(self):
        rec = ShRecorder({"hb props": cp(0, PROPS_WITH_RELATION),
                          "hb set-prop": cp(0, "{}")})
        with mock.patch.object(A, "sh", rec):
            t = A.Transport("hb", {})
            self.assertTrue(t.set_project_relation(CHILD, ENTRY))
        (setp,) = rec.verb_calls("hb set-prop")
        self.assertEqual(setp[2], CHILD)
        self.assertEqual(setp[setp.index("--pid") + 1], PID)
        # set-property wants a plain ID array — not the {id,type} shape reads give
        self.assertEqual(setp[setp.index("--json") + 1], json.dumps([ENTRY]))

    def test_heptabase_sets_relation(self):
        rec = ShRecorder({"heptabase card properties": cp(0, PROPS_WITH_RELATION),
                          "heptabase card set-property": cp(0, "{}")})
        with mock.patch.object(A, "sh", rec):
            t = A.Transport("heptabase", {})
            self.assertTrue(t.set_project_relation(CHILD, ENTRY))
        (setp,) = rec.verb_calls("heptabase card set-property")
        self.assertEqual(setp[3], CHILD)
        self.assertEqual(setp[setp.index("--property-id") + 1], PID)
        self.assertEqual(setp[setp.index("--json-value") + 1], json.dumps([ENTRY]))

    def test_schema_without_relation_skips_quietly(self):
        rec = ShRecorder({"hb props": cp(0, PROPS_NO_RELATION)})
        with mock.patch.object(A, "sh", rec):
            t = A.Transport("hb", {})
            self.assertFalse(t.set_project_relation(CHILD, ENTRY))
        self.assertEqual(rec.verb_calls("hb set-prop"), [])   # never attempted

    def test_props_failure_is_best_effort_false(self):
        rec = ShRecorder({"hb props": cp(1, "", "bridge down")})
        with mock.patch.object(A, "sh", rec):
            t = A.Transport("hb", {})
            self.assertFalse(t.set_project_relation(CHILD, ENTRY))

    def test_obsidian_out_of_scope(self):
        t = A.Transport.__new__(A.Transport)
        t.kind, t.cfg, t.tag, t._obe = "obsidian", {}, "project", None
        self.assertFalse(t.set_project_relation(CHILD, ENTRY))


class TestHbCreateTagAdd(unittest.TestCase):
    def _create(self, tag_add_resp):
        rec = ShRecorder({"hb create": cp(0, json.dumps({"id": CHILD})),
                          "hb tag-add": tag_add_resp})
        with mock.patch.object(A, "sh", rec):
            t = A.Transport("hb", {})
            cid, tagged = t.create("t · 續 1", "# t · 續 1\n\nbody")
        return cid, tagged, rec

    def test_new_client_tags(self):
        cid, tagged, rec = self._create(cp(0, "{}"))
        self.assertEqual(cid, CHILD)
        self.assertTrue(tagged)
        (ta,) = rec.verb_calls("hb tag-add")
        self.assertEqual(ta[2:], [CHILD, "project"])

    def test_old_client_degrades_gracefully(self):
        # argparse "invalid choice: 'tag-add'" → rc 2 → untagged, no crash
        cid, tagged, _ = self._create(cp(2, "", "invalid choice: 'tag-add'"))
        self.assertEqual(cid, CHILD)
        self.assertFalse(tagged)

    def test_tag_add_raise_never_orphans_the_child(self):
        # a raising tag-add (timeout / spawn failure) must still return the id
        # — the caller has yet to write the tail→child link
        def boom(args):
            raise subprocess.TimeoutExpired(args, 60)
        cid, tagged, _ = self._create(boom)
        self.assertEqual(cid, CHILD)
        self.assertFalse(tagged)

    def test_tag_override_reaches_tag_add(self):
        # log-as-card passes its own tag (default "<projects tag>/progress")
        rec = ShRecorder({"hb create": cp(0, json.dumps({"id": CHILD})),
                          "hb tag-add": cp(0, "{}")})
        with mock.patch.object(A, "sh", rec):
            t = A.Transport("hb", {})
            _, tagged = t.create("log", "# log\n\nbody",
                                 tag=A.log_tag_name({}))
        self.assertTrue(tagged)
        (ta,) = rec.verb_calls("hb tag-add")
        self.assertEqual(ta[2:], [CHILD, "project/progress"])


class TestLogRelationTagScope(unittest.TestCase):
    def test_relation_looked_up_in_log_tags_schema(self):
        # once the log tag carries its own relation property, log cards get
        # the entry pointer with no code change
        log_props = json.dumps({"cardId": CHILD, "tags": [
            {"tagId": "T2", "tagName": "project/progress", "properties": [
                {"id": PID, "name": "project", "type": "relation",
                 "value": []}]}]})
        rec = ShRecorder({"hb props": cp(0, log_props),
                          "hb set-prop": cp(0, "{}")})
        with mock.patch.object(A, "sh", rec):
            t = A.Transport("hb", {})
            self.assertTrue(t.set_project_relation(
                CHILD, ENTRY, tag="project/progress"))
        (setp,) = rec.verb_calls("hb set-prop")
        self.assertEqual(setp[setp.index("--pid") + 1], PID)

    def test_schema_less_log_tag_skips_quietly(self):
        # out-of-the-box: project/progress has no properties → quiet False
        log_props = json.dumps({"cardId": CHILD, "tags": [
            {"tagId": "T2", "tagName": "project/progress",
             "properties": []}]})
        rec = ShRecorder({"hb props": cp(0, log_props)})
        with mock.patch.object(A, "sh", rec):
            t = A.Transport("hb", {})
            self.assertFalse(t.set_project_relation(
                CHILD, ENTRY, tag="project/progress"))
        self.assertEqual(rec.verb_calls("hb set-prop"), [])


class StubTransport:
    """Just enough surface for append_or_spill's spill path."""
    kind, cfg, tag = "heptabase", {}, "project"

    def __init__(self, tagged=True, relation_ok=True):
        self._tagged = tagged
        self._relation_ok = relation_ok
        self.relation_calls = []

    def read(self, cid):
        return ""                       # no sentinel → chain is [entry]

    def size(self, cid):
        return 79999                    # +any content clears the 80k threshold

    def title(self, cid):
        return "P"

    def create(self, title, body):
        return CHILD, self._tagged

    def _append_cmd(self, cid, md, no_queue):
        return cp(0, "")

    def seal_continuation(self, tail, child, entry=None):
        return True

    def set_project_relation(self, cid, eid):
        self.relation_calls.append((cid, eid))
        return self._relation_ok


class TestSpillWiring(unittest.TestCase):
    def test_spill_sets_relation_back_to_entry(self):
        t = StubTransport()
        rep = A.append_or_spill(t, ENTRY, "new content")
        self.assertTrue(rep["overflowed"])
        self.assertEqual(rep["child"], CHILD)
        self.assertTrue(rep["tagged"])
        self.assertTrue(rep["related"])
        self.assertEqual(t.relation_calls, [(CHILD, ENTRY)])

    def test_untagged_short_circuits_relation(self):
        t = StubTransport(tagged=False)
        rep = A.append_or_spill(t, ENTRY, "new content")
        self.assertFalse(rep["tagged"])
        self.assertFalse(rep["related"])
        self.assertEqual(t.relation_calls, [])          # skipped entirely
        self.assertIn("未上 tag", rep["note"])

    def test_relation_failure_never_fails_spill(self):
        t = StubTransport(relation_ok=False)
        rep = A.append_or_spill(t, ENTRY, "new content")
        self.assertTrue(rep["tagged"])
        self.assertFalse(rep["related"])
        self.assertEqual(rep["child"], CHILD)           # spill still landed


if __name__ == "__main__":
    unittest.main()
