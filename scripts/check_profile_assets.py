#!/usr/bin/env python3
"""Check that local files referenced by the profile README exist."""

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\((<[^>]+>|[^)\s]+)(?:\s+[^)]*)?\)")


class LocalReferenceParser(HTMLParser):
    """Collect local href/src paths from HTML embedded in README.md."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paths: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name not in {"href", "src"} or not value:
                continue

            path = _local_path(value)
            if path:
                self.paths.append(path)


def _local_path(destination: str) -> str | None:
    """Return a decoded local path, ignoring URLs and fragment-only links."""
    destination = destination.strip()
    if destination.startswith("<") and destination.endswith(">"):
        destination = destination[1:-1]

    parsed = urlsplit(destination)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    return unquote(parsed.path)


def collect_local_references(readme_text: str) -> set[str]:
    """Collect local paths from HTML attributes and Markdown inline links/images."""
    parser = LocalReferenceParser()
    parser.feed(readme_text)
    references = set(parser.paths)

    for match in MARKDOWN_LINK_RE.finditer(readme_text):
        path = _local_path(match.group(1))
        if path:
            references.add(path)

    return references


def find_missing_references(root: Path, references: set[str]) -> list[str]:
    """Return missing paths and paths that resolve outside the repository root."""
    root = root.resolve()
    missing: list[str] = []
    for reference in sorted(references):
        candidate = (root / reference.lstrip("/")).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            missing.append(f"{reference} (path escapes repository)")
            continue

        if not candidate.exists():
            missing.append(reference)
    return missing


def main() -> int:
    if not README.is_file():
        print(f"README not found: {README}")
        return 2

    references = collect_local_references(README.read_text(encoding="utf-8"))
    missing = find_missing_references(ROOT, references)

    if missing:
        print("Missing or unsafe local README references:")
        for reference in missing:
            print(f"  - {reference}")
        return 1

    print(f"Checked {len(references)} unique local README references; all exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
