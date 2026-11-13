#!/usr/bin/env python3
"""Check local README references and HTML image alt attributes."""

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
                candidates = _srcset_urls(value)
            else:
                continue

            for candidate in candidates:
                path = _local_path(candidate)
                if path:
                    self.paths.append(path)


class MissingImageAltParser(HTMLParser):
    """Find HTML image elements without an explicit alt attribute."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.missing_alt_lines: list[int] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        has_alt = any(name.lower() == "alt" for name, _ in attrs)
        if tag.lower() == "img" and not has_alt:
            self.missing_alt_lines.append(self.getpos()[0])


def _srcset_urls(value: str) -> list[str]:
    """Split srcset candidates while preserving commas inside each URL."""
    urls: list[str] = []
    index = 0

    while index < len(value):
        while index < len(value) and (value[index].isspace() or value[index] == ","):
            index += 1
        if index >= len(value):
            break

        start = index
        while index < len(value) and not value[index].isspace():
            index += 1
        url = value[start:index]

        if url.endswith(","):
            url = url.rstrip(",")
            if url:
                urls.append(url)
            continue

        if url:
            urls.append(url)

        in_parentheses = False
        while index < len(value):
            char = value[index]
            if char == "(":
                in_parentheses = True
            elif char == ")":
                in_parentheses = False
            elif char == "," and not in_parentheses:
                index += 1
                break
            index += 1

    return urls


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
            if text[index] in "\r\n":
                return None
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


def _skip_reference_whitespace(text: str, start: int) -> int | None:
    """Skip optional horizontal whitespace and at most one line ending."""
    index = start
    while index < len(text) and text[index] in " \t":
        index += 1

    if text.startswith("\r\n", index):
        index += 2
    elif index < len(text) and text[index] in "\r\n":
        index += 1
    else:
        return index

    while index < len(text) and text[index] in " \t":
        index += 1
    if index < len(text) and text[index] in "\r\n":
        return None
    return index


def _reference_definitions(readme_text: str) -> dict[str, str]:
    """Collect reference definitions, including labels and destinations split across lines."""
    definitions: dict[str, str] = {}
    line_start = 0

    for line in readme_text.splitlines(keepends=True):
        line_content = line.rstrip("\r\n")
        indentation = len(line_content) - len(line_content.lstrip(" "))

        if indentation <= 3 and indentation < len(line_content):
            opening_index = line_start + indentation
            if line_content[indentation] == "[":
                closing_index = _matching_bracket_end(readme_text, opening_index)
                if closing_index is not None:
                    label_text = readme_text[opening_index + 1:closing_index]
                    normalized = _normalize_reference_label(label_text)
                    has_blank_line = re.search(
                        r"(?:\r\n|\r|\n)[ \t]*(?:\r\n|\r|\n)",
                        label_text,
                    )
                    colon_index = closing_index + 1

                    if (
                        normalized
                        and not has_blank_line
                        and colon_index < len(readme_text)
                        and readme_text[colon_index] == ":"
                    ):
                        destination_start = _skip_reference_whitespace(
                            readme_text, colon_index + 1
                        )
                        if destination_start is not None:
                            destination = _parse_destination(
                                readme_text, destination_start
                            )
                            if destination is not None:
                                definitions.setdefault(normalized, destination)

        line_start += len(line)

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


def find_images_without_alt(readme_text: str) -> list[int]:
    """Return line numbers for HTML image elements missing an alt attribute."""
    parser = MissingImageAltParser()
    parser.feed(_without_code_examples(readme_text))
    return parser.missing_alt_lines


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

    readme_text = README.read_text(encoding="utf-8")
    references = collect_local_references(readme_text)
    missing = find_missing_references(ROOT, references)
    missing_alt = find_images_without_alt(readme_text)

    if missing or missing_alt:
        if missing:
            print("Missing or unsafe local README references:")
            for reference in missing:
                print(f"  - {reference}")
        if missing_alt:
            print("README images missing alt attributes:")
            for line_number in missing_alt:
                print(f"  - line {line_number}")
        return 1

    print(f"Checked {len(references)} unique local README references; all exist.")
    print("All HTML image elements include alt attributes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
