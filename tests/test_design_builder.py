import base64
import importlib.util
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
BUILDER_SPEC = importlib.util.spec_from_file_location("profile_design_builder", BUILDER)
if BUILDER_SPEC is None or BUILDER_SPEC.loader is None:
    raise RuntimeError("Could not load the profile artwork builder for palette tests")
DESIGN_BUILDER = importlib.util.module_from_spec(BUILDER_SPEC)
BUILDER_SPEC.loader.exec_module(DESIGN_BUILDER)


def contrast_ratio(first, second):
    def luminance(color):
        if len(color) != 7 or not color.startswith("#"):
            raise ValueError(f"Expected a six-digit hex color, got {color!r}")
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92 if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return sum(
            channel * weight
            for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722))
        )

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def composite_color(foreground, background, opacity):
    """Composite an SVG foreground color over a background color."""
    channels = [
        round(
            int(foreground[index:index + 2], 16) * opacity
            + int(background[index:index + 2], 16) * (1 - opacity)
        )
        for index in (1, 3, 5)
    ]
    return "#" + "".join(f"{channel:02x}" for channel in channels)


class DesignPaletteAccessibilityTests(unittest.TestCase):
    def test_text_color_combinations_meet_wcag_aa(self):
        # Cover readable text on the canvas, cards, project panels and buttons.
        text_pairs = (
            ("ink", "bg"),
            ("muted", "bg"),
            ("accent", "bg"),
            ("ink", "card"),
            ("muted", "card"),
            ("accent", "card"),
            ("ink", "soft"),
            ("muted", "soft"),
            ("note", "soft"),
            ("ink", "warm"),
            ("muted", "warm"),
            ("note", "warm"),
            ("buttonText", "button"),
            ("heroText", "hero"),
        )

        for theme_name, palette in DESIGN_BUILDER.THEMES.items():
            for foreground_key, background_key in text_pairs:
                with self.subTest(
                    theme=theme_name,
                    foreground=foreground_key,
                    background=background_key,
                ):
                    ratio = contrast_ratio(
                        palette[foreground_key],
                        palette[background_key],
                    )
                    self.assertGreaterEqual(
                        ratio,
                        4.5,
                        f"{theme_name}: {foreground_key} on {background_key} "
                        f"has a contrast ratio of {ratio:.2f}:1 (requires 4.5:1)",
                    )


class DesignBuilderIntegrationTests(unittest.TestCase):
    def assert_profile_header_text_contrast(self, svg_path):
        root = ET.parse(svg_path).getroot()
        scrim = root.find(".//*[@id='profile-text-scrim']")
        name = root.find(".//*[@id='profile-name']")
        role = root.find(".//*[@id='profile-role']")

        self.assertIsNotNone(scrim, f"{svg_path.name} has no portrait text scrim")
        self.assertIsNotNone(name, f"{svg_path.name} has no profile name")
        self.assertIsNotNone(role, f"{svg_path.name} has no profile role")
        if scrim is None or name is None or role is None:
            return

        self.assertEqual(DESIGN_BUILDER.PROFILE_TEXT_SCRIM_COLOR, scrim.attrib.get("fill"))
        opacity = float(scrim.attrib.get("fill-opacity", "0"))
        self.assertAlmostEqual(DESIGN_BUILDER.PROFILE_TEXT_SCRIM_OPACITY, opacity)
        self.assertEqual(DESIGN_BUILDER.PROFILE_TEXT_COLOR, name.attrib.get("fill"))
        self.assertEqual(DESIGN_BUILDER.PROFILE_TEXT_COLOR, role.attrib.get("fill"))

        elements = list(root)
        self.assertLess(elements.index(scrim), elements.index(name))
        self.assertLess(elements.index(name), elements.index(role))

        # White is the brightest possible portrait pixel, so compositing the
        # scrim over white checks the worst-case contrast for any source photo.
        worst_case_background = composite_color(
            DESIGN_BUILDER.PROFILE_TEXT_SCRIM_COLOR,
            "#ffffff",
            opacity,
        )
        ratio = contrast_ratio(DESIGN_BUILDER.PROFILE_TEXT_COLOR, worst_case_background)
        self.assertGreaterEqual(
            ratio,
            4.5,
            f"{svg_path.name} portrait text has only {ratio:.2f}:1 contrast",
        )

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

            for theme in ("light", "dark"):
                with self.subTest(profile_header_theme=theme):
                    self.assert_profile_header_text_contrast(
                        output / f"header-{theme}.svg"
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
