import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_profile_assets import collect_local_references, find_missing_references


class ProfileAssetCheckerTests(unittest.TestCase):
    def test_collects_html_and_markdown_local_references(self):
        readme = """
[Guide](docs/guide.md "Read the guide")
![Diagram](assets/my%20diagram.svg)
[Space path](<docs/guide with spaces.md>)
<a href="./M.%20Saad%20Nazir.pdf">Résumé</a>
<a href="https://example.com">External HTML</a>
[External Markdown](https://example.com)
[Section](#about)
"""
        self.assertEqual(
            {
                "docs/guide.md",
                "assets/my diagram.svg",
                "docs/guide with spaces.md",
                "./M. Saad Nazir.pdf",
            },
            collect_local_references(readme),
        )

    def test_collects_destinations_with_balanced_and_escaped_parentheses(self):
        readme = r"""
[Chart](assets/chart_(v2).svg)
![Escaped chart](assets/chart_\(v3\).svg)
[Spaced chart](<assets/chart (final).svg>)
"""
        self.assertEqual(
            {
                "assets/chart_(v2).svg",
                "assets/chart_(v3).svg",
                "assets/chart (final).svg",
            },
            collect_local_references(readme),
        )

    def test_ignores_fenced_and_inline_code_examples(self):
        readme = """
```markdown
[Fake link](missing-fenced.md)
<a href="missing-fenced.html">Fake HTML</a>
```

~~~html
<img src="missing-image.svg" />
~~~

Inline example: `[not a link](missing-inline.md)`.

[Real link](docs/real.md)
"""
        self.assertEqual({"docs/real.md"}, collect_local_references(readme))

    def test_reports_missing_and_escaping_paths_but_accepts_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "assets").mkdir()
            (root / "assets" / "logo.svg").write_text("svg", encoding="utf-8")

            self.assertEqual(
                ["../outside.md (path escapes repository)", "missing.md"],
                find_missing_references(
                    root,
                    {"assets/logo.svg", "missing.md", "../outside.md"},
                ),
            )

    def test_root_relative_path_is_resolved_inside_repository(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "logo.svg").write_text("svg", encoding="utf-8")
            self.assertEqual([], find_missing_references(root, {"/logo.svg"}))


if __name__ == "__main__":
    unittest.main()
