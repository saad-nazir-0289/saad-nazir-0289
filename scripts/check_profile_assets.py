#!/usr/bin/env python3
"""Check that local files referenced by the profile README exist."""

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
FENCE_OPEN_RE = re.compile(r" {0,3}(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"(?<!`)(`+).*?(?<!`)\1(?!`)", re.DOTALL)
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(")
MARKDOWN_ESCAPABLE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!<>|~])")


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


def _without_code_examples(readme_text: str) -> str:
    """Remove fenced and inline code so examples are not treated as real links."""
    output: list[str] = []
    fence_char: str | None = None
    fence_length = 0

    for line in readme_text.splitlines(keepends=True):
        if fence_char is None:
            opening = FENCE_OPEN_RE.match(line)
            if opening:
                fence = opening.group(1)
                fence_char, fence_length = fence[0], len(fence)
                output.append("\n" if line.endswith(("\n", "\r")) else "")
                continue
        else:
            closing = re.match(
                rf" {{0,3}}{re.escape(fence_char)}{{{fence_length},}}[ \t]*(?:\r?\n)?$",
                line,
            )
            if closing:
                fence_char, fence_length = None, 0
            output.append("\n" if line.endswith(("\n", "\r")) else "")
            continue

        output.append(line)

    text = "".join(output)
    return INLINE_CODE_RE.sub(
        lambda match: "".join(
            char if char in "\r\n" else " " for char in match.group(0)
        ),
        text,
    )


def _markdown_destinations(readme_text: str) -> set[str]:
    """Extract inline Markdown link/image destinations, including balanced parentheses."""
    destinations: set[str] = set()

    for match in MARKDOWN_LINK_RE.finditer(readme_text):
        index = match.end()
        while index < len(readme_text) and readme_text[index].isspace():
            index += 1

        if index < len(readme_text) and readme_text[index] == "<":
            start = index + 1
            index = start
            while index < len(readme_text):
                if readme_text[index] == ">" and not _is_escaped(readme_text, index):
                    destinations.add(
                        MARKDOWN_ESCAPABLE.sub(r"\1", readme_text[start:index])
                    )
                    break
                index += 1
            continue

        start = index
        depth = 0
        while index < len(readme_text):
            char = readme_text[index]
            if _is_escaped(readme_text, index):
                index += 1
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
            elif char.isspace() and depth == 0:
                break
            index += 1

        destination = readme_text[start:index]
        if destination:
            destinations.add(MARKDOWN_ESCAPABLE.sub(r"\1", destination))

    return destinations


def _is_escaped(text: str, index: int) -> bool:
    """Return whether the character at index is preceded by an odd backslash run."""
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


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
    readme_text = _without_code_examples(readme_text)

    parser = LocalReferenceParser()
    parser.feed(readme_text)
    references = set(parser.paths)

    for destination in _markdown_destinations(readme_text):
        path = _local_path(destination)
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
