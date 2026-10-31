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

    def test_collects_picture_srcset_candidates(self):
        readme = """
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/header-dark.svg" />
  <source srcset="assets/wide.svg 2x, https://example.com/remote.svg 1x" />
  <img src="assets/header-light.svg" alt="Header" />
</picture>
"""
        self.assertEqual(
            {"assets/header-dark.svg", "assets/wide.svg", "assets/header-light.svg"},
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
[Fake reference]: missing-fenced-reference.md
[Fake reference]
<a href="missing-fenced.html">Fake HTML</a>
```

~~~html
<img src="missing-image.svg" />
~~~

Inline example: `[not a link](missing-inline.md)`.

[Real link](docs/real.md)
"""
        self.assertEqual({"docs/real.md"}, collect_local_references(readme))

    def test_collects_nested_bracket_labels_and_images(self):
        readme = r"""
[Read [the guide] carefully](docs/guide.md)
![Preview [dark mode]](assets/preview.svg)
[Escaped \[label\]](docs/escaped-label.md)
"""
        self.assertEqual(
            {
                "docs/guide.md",
                "assets/preview.svg",
                "docs/escaped-label.md",
            },
            collect_local_references(readme),
        )

    def test_collects_full_collapsed_and_shortcut_reference_links(self):
        readme = """
[Guide]: docs/guide.md "Guide title"
[Badge]: <assets/badge (blue).svg>
[guide text][Guide]
[Guide][]
[Guide]
![status][Badge]
[Missing reference][not-defined]
"""
        self.assertEqual(
            {"docs/guide.md", "assets/badge (blue).svg"},
            collect_local_references(readme),
        )

    def test_reference_labels_ignore_case_and_collapse_whitespace(self):
        readme = """
[API   Guide]: docs/api.md
[Read the API guide][ api guide ]
"""
        self.assertEqual({"docs/api.md"}, collect_local_references(readme))

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
