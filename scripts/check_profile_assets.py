#!/usr/bin/env python3
"""Check that local files referenced by the profile README exist."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class LocalReferenceParser(HTMLParser):
    """Collect local href/src paths from HTML embedded in README.md."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paths: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name not in {"href", "src"} or not value:
                continue

            parsed = urlsplit(value.strip())
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue

            path = unquote(parsed.path)
            if path:
                self.paths.append(path)


def main() -> int:
    if not README.is_file():
        print(f"README not found: {README}")
        return 2

    parser = LocalReferenceParser()
    parser.feed(README.read_text(encoding="utf-8"))

    missing: list[str] = []
    for reference in sorted(set(parser.paths)):
        candidate = (ROOT / reference.lstrip("/")).resolve()
        try:
            candidate.relative_to(ROOT)
        except ValueError:
            missing.append(f"{reference} (path escapes repository)")
            continue

        if not candidate.exists():
            missing.append(reference)

    if missing:
        print("Missing or unsafe local README references:")
        for reference in missing:
            print(f"  - {reference}")
        return 1

    print(f"Checked {len(set(parser.paths))} local README references; all exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
