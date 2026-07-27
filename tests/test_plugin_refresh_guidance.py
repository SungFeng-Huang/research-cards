from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
DIRECT_REFRESH = "codex plugin add research-cards@my-plugins"
READMES = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "README.zh-TW.md",
    REPO_ROOT / "README.ja.md",
    REPO_ROOT / "README.ko.md",
]


class PluginRefreshGuidanceTests(unittest.TestCase):
    def test_all_languages_use_add_only_refresh(self) -> None:
        for path in READMES:
            content = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertGreaterEqual(
                    content.count(DIRECT_REFRESH),
                    3,
                    "Install and troubleshooting guidance must use direct add.",
                )
                self.assertNotIn(
                    "codex plugin remove",
                    content,
                    "Published guidance must not reintroduce pre-removal.",
                )


if __name__ == "__main__":
    unittest.main()
