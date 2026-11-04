import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "design" / "build.py"


class DesignBuilderIntegrationTests(unittest.TestCase):
    def test_generates_valid_light_and_dark_assets_in_requested_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temp_root = Path(temporary_directory)
            site = temp_root / "fixture-site"
            generated = site / "src" / "generated"
            public = site / "public"
            generated.mkdir(parents=True)

            projects = [
                {
                    "slug": "mill-ledger",
                    "category": "PRODUCT ENGINEERING",
                    "client": "Fixture client",
                    "title": "MillLedger",
                    "summary": "Offline accounting for daily mill transactions.",
                    "stack": ["Electron", "React", "TypeScript", "SQLite"],
                    "inProgress": False,
                    "draft": False,
                },
                {
                    "slug": "ucp-noticeboard",
                    "category": "CAMPUS SOFTWARE",
                    "client": "Fixture university",
                    "title": "UCP Noticeboard",
                    "summary": "A searchable feed of campus announcements.",
                    "stack": ["React", "TypeScript", "ASP.NET Core"],
                    "inProgress": False,
                    "draft": False,
                },
            ]
            posts = [
                {
                    "date": "2026-01-02",
                    "category": "ENGINEERING",
                    "readingTime": 4,
                    "title": "Fixture article",
                    "summary": "A synthetic article used to verify generated artwork.",
                }
            ]
            (generated / "projects.json").write_text(
                json.dumps(projects), encoding="utf-8"
            )
            (generated / "blogs.json").write_text(
                json.dumps(posts), encoding="utf-8"
            )

            image_paths = [
                public / "saad-portrait.png",
                public / "case-studies" / "mill-ledger" / "home-thumbnail.png",
                public / "case-studies" / "ucp-noticeboard" / "home-thumbnail.png",
            ]
            for index, image_path in enumerate(image_paths):
                image_path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (32, 24), (40 + index * 30, 80, 120)).save(
                    image_path
                )

            output = temp_root / "artwork-preview"
            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILDER),
                    "--site",
                    str(site),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, msg=result.stderr or result.stdout)
            svg_files = sorted(output.glob("*.svg"))
            self.assertEqual(80, len(svg_files), msg=result.stdout)
            self.assertIn("Wrote 40 light and 40 dark images", result.stdout)

            required_assets = (
                "header",
                "stats",
                "card-mill-ledger",
                "card-ucp-noticeboard",
                "blog-1",
                "header-mobile",
                "stats-mobile",
                "card-mill-ledger-mobile",
                "blog-1-mobile",
            )
            for theme in ("light", "dark"):
                for name in required_assets:
                    self.assertTrue(
                        (output / f"{name}-{theme}.svg").is_file(),
                        f"Missing {name}-{theme}.svg",
                    )

            for svg_path in svg_files:
                with self.subTest(svg=svg_path.name):
                    root = ET.parse(svg_path).getroot()
                    self.assertEqual(
                        "{http://www.w3.org/2000/svg}svg",
                        root.tag,
                    )


if __name__ == "__main__":
    unittest.main()
