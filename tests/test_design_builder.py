import base64
import io
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
    def create_site_fixture(self, site):
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
        (generated / "projects.json").write_text(json.dumps(projects), encoding="utf-8")
        (generated / "blogs.json").write_text(json.dumps(posts), encoding="utf-8")

        image_paths = [
            public / "saad-portrait.png",
            public / "case-studies" / "mill-ledger" / "home-thumbnail.png",
            public / "case-studies" / "ucp-noticeboard" / "home-thumbnail.png",
        ]
        for index, image_path in enumerate(image_paths):
            image_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (32, 24), (40 + index * 30, 80, 120)).save(image_path)
        return generated, public

    def run_builder(self, site, output):
        return subprocess.run(
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

    def assert_svg_accessibility(self, svg_path):
        svg_namespace = "{http://www.w3.org/2000/svg}"
        xlink_href = "{http://www.w3.org/1999/xlink}href"
        root = ET.parse(svg_path).getroot()
        self.assertEqual(f"{svg_namespace}svg", root.tag)

        title = root.find(f"{svg_namespace}title")
        self.assertIsNotNone(title, f"{svg_path.name} has no SVG title")
        title_text = (title.text or "").strip() if title is not None else ""
        self.assertTrue(title_text, f"{svg_path.name} has an empty SVG title")

        aria_label = root.attrib.get("aria-label", "").strip()
        self.assertTrue(aria_label, f"{svg_path.name} has no accessible label")
        self.assertEqual(
            " ".join(title_text.split()),
            " ".join(aria_label.split()),
            f"{svg_path.name} title and label differ",
        )
        self.assertEqual(
            "img",
            root.attrib.get("role"),
            f"{svg_path.name} is not exposed as an image",
        )

        images = root.findall(f".//{svg_namespace}image")
        for image in images:
            href = image.attrib.get("href") or image.attrib.get(xlink_href)
            self.assertTrue(
                href,
                f"{svg_path.name} contains an image without a source",
            )
            if not href:
                continue

            header, separator, payload = href.partition(",")
            self.assertTrue(
                separator,
                f"{svg_path.name} contains a malformed image data URI",
            )
            self.assertTrue(
                header.startswith("data:image/"),
                f"{svg_path.name} contains a non-embedded image",
            )
            self.assertTrue(
                header.endswith(";base64"),
                f"{svg_path.name} contains a non-base64 image URI",
            )
            if (
                not separator
                or not header.startswith("data:image/")
                or not header.endswith(";base64")
            ):
                continue

            decoded = base64.b64decode(payload, validate=True)
            self.assertGreater(
                len(decoded),
                0,
                f"{svg_path.name} contains an empty embedded image",
            )
            with Image.open(io.BytesIO(decoded)) as embedded:
                self.assertEqual(
                    header[5:].split(";", 1)[0],
                    f"image/{embedded.format.lower()}",
                    f"{svg_path.name} image MIME type does not match its data",
                )
                embedded.verify()

        return len(images)

    def test_generates_valid_light_and_dark_assets_in_requested_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temp_root = Path(temporary_directory)
            site = temp_root / "fixture-site"
            self.create_site_fixture(site)

            output = temp_root / "artwork-preview"
            result = self.run_builder(site, output)

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

            embedded_image_count = 0
            for svg_path in svg_files:
                with self.subTest(svg=svg_path.name):
                    embedded_image_count += self.assert_svg_accessibility(svg_path)
            self.assertGreater(
                embedded_image_count,
                0,
                "Expected generated artwork to contain embedded images",
            )

    def test_rejects_missing_required_project_before_writing_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temp_root = Path(temporary_directory)
            site = temp_root / "fixture-site"
            generated, _ = self.create_site_fixture(site)
            projects_path = generated / "projects.json"
            projects = json.loads(projects_path.read_text(encoding="utf-8"))
            projects = [project for project in projects if project["slug"] != "mill-ledger"]
            projects_path.write_text(json.dumps(projects), encoding="utf-8")

            output = temp_root / "artwork-preview"
            result = self.run_builder(site, output)

            self.assertEqual(2, result.returncode)
            self.assertIn("Missing required project slug: mill-ledger", result.stderr)
            self.assertFalse(output.exists())

    def test_rejects_missing_project_field_before_writing_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temp_root = Path(temporary_directory)
            site = temp_root / "fixture-site"
            generated, _ = self.create_site_fixture(site)
            projects_path = generated / "projects.json"
            projects = json.loads(projects_path.read_text(encoding="utf-8"))
            projects[0].pop("summary")
            projects_path.write_text(json.dumps(projects), encoding="utf-8")

            output = temp_root / "artwork-preview"
            result = self.run_builder(site, output)

            self.assertEqual(2, result.returncode)
            self.assertIn(
                "Project 'mill-ledger' must contain a non-empty 'summary' string",
                result.stderr,
            )
            self.assertFalse(output.exists())

    def test_rejects_missing_image_before_writing_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temp_root = Path(temporary_directory)
            site = temp_root / "fixture-site"
            _, public = self.create_site_fixture(site)
            (public / "saad-portrait.png").unlink()

            output = temp_root / "artwork-preview"
            result = self.run_builder(site, output)

            self.assertEqual(2, result.returncode)
            self.assertIn("Missing portrait image", result.stderr)
            self.assertFalse(output.exists())

    def test_rejects_blog_cover_path_outside_public_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temp_root = Path(temporary_directory)
            site = temp_root / "fixture-site"
            generated, _ = self.create_site_fixture(site)
            posts_path = generated / "blogs.json"
            posts = json.loads(posts_path.read_text(encoding="utf-8"))
            posts[0]["cover"] = {"src": "/../../outside.png"}
            posts_path.write_text(json.dumps(posts), encoding="utf-8")

            output = temp_root / "artwork-preview"
            result = self.run_builder(site, output)

            self.assertEqual(2, result.returncode)
            self.assertIn("must resolve inside the site's public directory", result.stderr)
            self.assertFalse(output.exists())

    def test_rejects_output_directory_inside_supplied_site(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temp_root = Path(temporary_directory)
            site = temp_root / "fixture-site"
            self.create_site_fixture(site)

            output = site / "artwork-preview"
            result = self.run_builder(site, output)

            self.assertEqual(2, result.returncode)
            self.assertIn("--output must be outside --site", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
