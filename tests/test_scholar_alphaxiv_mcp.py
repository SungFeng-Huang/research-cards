"""alphaXiv content transport: Codex MCP-first with bounded HTTP fallback."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "skills", "scholar-inbox-clip"))

import run


class TestScholarAlphaXivMcp(unittest.TestCase):
    def setUp(self):
        self.orig_transport = os.environ.get("SCHOLAR_CLIP_ALPHAXIV_TRANSPORT")
        self.orig_mcp = run._fetch_alphaxiv_mcp
        self.orig_http = run._fetch_alphaxiv_http
        self.orig_disabled = run._ALPHAXIV_MCP_DISABLED
        os.environ["SCHOLAR_CLIP_ALPHAXIV_TRANSPORT"] = "mcp"
        run._ALPHAXIV_MCP_DISABLED = None

    def tearDown(self):
        run._fetch_alphaxiv_mcp = self.orig_mcp
        run._fetch_alphaxiv_http = self.orig_http
        run._ALPHAXIV_MCP_DISABLED = self.orig_disabled
        if self.orig_transport is None:
            os.environ.pop("SCHOLAR_CLIP_ALPHAXIV_TRANSPORT", None)
        else:
            os.environ["SCHOLAR_CLIP_ALPHAXIV_TRANSPORT"] = self.orig_transport

    def test_mcp_text_and_report_detection(self):
        result = {"content": [{"type": "text", "text":
                  "## Research Report: Paper\n\nThis report provides a detailed analysis."}]}
        text = run._mcp_text(result)
        self.assertTrue(run._looks_like_ai_report(text))
        self.assertFalse(run._looks_like_ai_report("Paper title\nAbstract raw text"))

    def test_mcp_is_primary(self):
        run._fetch_alphaxiv_mcp = lambda paper_id: ("mcp report", True)
        run._fetch_alphaxiv_http = lambda paper_id: self.fail("HTTP 不應被呼叫")
        self.assertEqual(run.fetch_alphaxiv("2507.09318"), ("mcp report", True))

    def test_one_mcp_failure_disables_it_for_the_run(self):
        calls = {"mcp": 0, "http": 0}

        def bad_mcp(paper_id):
            calls["mcp"] += 1
            raise RuntimeError("OAuth unavailable")

        def good_http(paper_id):
            calls["http"] += 1
            return "raw fallback", False

        run._fetch_alphaxiv_mcp = bad_mcp
        run._fetch_alphaxiv_http = good_http
        self.assertEqual(run.fetch_alphaxiv("2507.09318"),
                         ("raw fallback", False))
        self.assertEqual(run.fetch_alphaxiv("2507.09319"),
                         ("raw fallback", False))
        self.assertEqual(calls, {"mcp": 1, "http": 2})

    def test_mcp_error_payload_is_rejected(self):
        with self.assertRaises(RuntimeError):
            run._mcp_text({"isError": True, "content": []})
        with self.assertRaises(RuntimeError):
            run._mcp_text({"content": [{"type": "image", "data": "..."}]})

    def test_codex_binary_is_resolved_for_minimal_path_runs(self):
        if run.CODEX_BIN == "codex":
            self.skipTest("Codex CLI is not installed in this test environment")
        self.assertTrue(os.path.isabs(run.CODEX_BIN), run.CODEX_BIN)
        self.assertTrue(os.access(run.CODEX_BIN, os.X_OK), run.CODEX_BIN)


if __name__ == "__main__":
    unittest.main()
