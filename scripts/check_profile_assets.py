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
MARKDOWN_ESCAPABLE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!<>|~])")


class LocalReferenceParser(HTMLParser):
    """Collect local href/src/srcset paths from HTML embedded in README.md."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paths: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if not value:
                continue
            if name in {"href", "src"}:
                candidates = [value]
            elif name == "srcset":
                # "a.svg, b.svg 2x": each comma-separated entry is a URL plus an optional descriptor.
                candidates = [entry.split()[0] for entry in value.split(",") if entry.strip()]
            else:
                continue

            for candidate in candidates:
                path = _local_path(candidate)
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


def _is_escaped(text: str, index: int) -> bool:
    """Return whether the character at index is preceded by an odd backslash run."""
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _matching_bracket_end(text: str, opening_index: int) -> int | None:
    """Find the closing bracket for a possibly nested Markdown label."""
    depth = 1
    index = opening_index + 1
    while index < len(text):
        if _is_escaped(text, index):
            index += 1
            continue
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _normalize_reference_label(label: str) -> str:
    """Normalize a Markdown reference label for case- and whitespace-insensitive lookup."""
    unescaped = MARKDOWN_ESCAPABLE.sub(r"\1", label)
    return " ".join(unescaped.split()).casefold()


def _parse_destination(text: str, start: int) -> str | None:
    """Read an angle-bracket or balanced-parenthesis Markdown destination."""
    while start < len(text) and text[start].isspace():
        start += 1

    if start >= len(text):
        return None

    if text[start] == "<":
        index = start + 1
        while index < len(text):
            if text[index] == ">" and not _is_escaped(text, index):
                return MARKDOWN_ESCAPABLE.sub(r"\1", text[start + 1:index])
            index += 1
        return None

    index = start
    depth = 0
    while index < len(text):
        char = text[index]
        if _is_escaped(text, index):
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

    destination = text[start:index]
    if not destination or depth != 0:
        return None
    return MARKDOWN_ESCAPABLE.sub(r"\1", destination)


def _reference_definitions(readme_text: str) -> dict[str, str]:
    """Collect reference-style link definitions and their destinations."""
    definitions: dict[str, str] = {}

    for line in readme_text.splitlines():
        indentation = len(line) - len(line.lstrip(" "))
        if indentation > 3:
            continue

        opening_index = indentation
        if opening_index >= len(line) or line[opening_index] != "[":
            continue

        closing_index = _matching_bracket_end(line, opening_index)
        if closing_index is None or closing_index + 1 >= len(line):
            continue
        if line[closing_index + 1] != ":":
            continue

        label = _normalize_reference_label(line[opening_index + 1:closing_index])
        if not label:
            continue

        destination = _parse_destination(line, closing_index + 2)
        if destination:
            definitions.setdefault(label, destination)

    return definitions


def _markdown_destinations(readme_text: str) -> set[str]:
    """Extract inline and reference-style Markdown link/image destinations."""
    definitions = _reference_definitions(readme_text)
    destinations = set(definitions.values())
    index = 0

    while index < len(readme_text):
        if readme_text[index] != "[" or _is_escaped(readme_text, index):
            index += 1
            continue

        closing_index = _matching_bracket_end(readme_text, index)
        if closing_index is None:
            index += 1
            continue

        label = readme_text[index + 1:closing_index]
        normalized_label = _normalize_reference_label(label)
        suffix_index = closing_index + 1

        if suffix_index < len(readme_text) and readme_text[suffix_index] == "(":
            destination = _parse_destination(readme_text, suffix_index + 1)
            if destination:
                destinations.add(destination)
            index = suffix_index + 1
            continue

        if suffix_index < len(readme_text) and readme_text[suffix_index] == "[":
            reference_end = _matching_bracket_end(readme_text, suffix_index)
            if reference_end is not None:
                reference_label = readme_text[suffix_index + 1:reference_end]
                key = _normalize_reference_label(reference_label or label)
                if key in definitions:
                    destinations.add(definitions[key])
                index = reference_end + 1
                continue

        if normalized_label in definitions:
            destinations.add(definitions[normalized_label])

        index = closing_index + 1

    return destinations


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
    """Collect local paths from HTML attributes and Markdown links/images."""
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
