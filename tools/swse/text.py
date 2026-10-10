"""Small, source-coordinate-preserving parsers for this Markdown snapshot."""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from urllib.parse import urlsplit, unquote


NOISE = {
    "Loading comments...", "Jedi CounselingJedi Counseling",
    "Scum and VillainyGalaxy at War", "Force PowerStarship Maneuver",
    "DestinyForce Power", "Legacy Era Campaign GuideWeb Enhancements",
    "Force Unleashed Campaign GuideJedi Academy Training Manual",
    "Point-Blank Shot, Rangefinders, and Targeting ScopesPoint-Blank Shot, Rangefinders, and Targeting Scopes",
    "Message From the Faculty: Move ObjectMessage From the Faculty: Move Object",
    "Message From the Faculty: Saber LocksMessage From the Faculty: Saber Locks",
}


def key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", text).encode(
        "ascii", "ignore").decode().lower()).strip("-")
    if not value:
        raise ValueError(f"Cannot construct a nonempty identifier: {text!r}")
    return value


def alias_key(text: str) -> str:
    if text.startswith(("https://", "http://")):
        url = urlsplit(text)
        title = " ".join(unicodedata.normalize("NFKC", unquote(url.path).replace("_", " ")).split())
        # Semantic names are case-insensitive; MediaWiki URL identities are not.
        # In particular, never turn an unrecorded oldid/diff URL into the current
        # local revision merely by dropping its query string.
        suffix = "?" + url.query if url.query else ""
        return f"url:{url.hostname}:{title}{suffix}"
    return key(text)


def _close(text: str, pos: int, left: str, right: str) -> int | None:
    depth, quote = 1, None
    i = pos + 1
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if left == "(" and char == '"':
            quote = None if quote else char
        if quote is None:
            if char == left:
                depth += 1
            elif char == right:
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None


def strip_links(text: str) -> str:
    """Preserve nested link labels; remove destinations and images, not words."""
    output = []
    i = 0
    while i < len(text):
        image = text.startswith("![", i)
        start = i + 1 if image else i
        if start < len(text) and text[start] == "[":
            bracket = _close(text, start, "[", "]")
            if bracket is not None and bracket + 1 < len(text) and text[bracket + 1] == "(":
                end = _close(text, bracket + 1, "(", ")")
                if end is not None:
                    if not image:
                        output.append(strip_links(text[start + 1:bracket]))
                    i = end + 1
                    continue
        output.append(text[i])
        i += 1
    return "".join(output)


def plain(text: str) -> str:
    text = strip_links(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"\\([*_\[\]])", r"\1", text)
    return text.strip()


def clean_line(line: str) -> str:
    if line.strip() in NOISE:
        return ""
    return plain(line)


@dataclass(frozen=True)
class Unit:
    start: int
    end: int
    text: str
    heading_path: tuple[str, ...]
    table: bool = False


def heading_paths(lines: list[str], start: int, end: int) -> dict[int, tuple[str, ...]]:
    paths, stack = {}, []
    for number in range(start, end + 1):
        match = re.match(r"^(#{1,6}) (.+)$", lines[number - 1])
        if match:
            level = len(match.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, plain(match.group(2))))
        paths[number] = tuple(label for _, label in stack)
    return paths


def units(lines: list[str], start: int, end: int, boundaries: set[int] | None = None) -> list[Unit]:
    """Paragraph/list/table units, split at headers and curated/source boundaries.

    A contiguous Markdown table is never divided. Curated boundaries must not
    cut a table; the builder checks that constraint before using this parser.
    """
    boundaries = boundaries or set()
    paths = heading_paths(lines, start, end)
    result = []
    i = start
    while i <= end:
        line = lines[i - 1]
        if not line.strip():
            i += 1
            continue
        begin = i
        table = line.lstrip().startswith("|")
        heading = bool(re.match(r"^#{1,6} ", line))
        marker = bool(re.match(r"^\*Reference Books?:", line))
        i += 1
        if table:
            while i <= end and lines[i - 1].lstrip().startswith("|"):
                if i in boundaries:
                    raise ValueError(f"Boundary at line {i} would split a Markdown table")
                i += 1
        elif not heading and not marker:
            while i <= end and lines[i - 1].strip() and i not in boundaries:
                if re.match(r"^(#{1,6} |\*Reference Books?:|\|)", lines[i - 1]):
                    break
                i += 1
        text = "\n".join(clean_line(value) for value in lines[begin - 1:i - 1]).strip()
        if text:
            result.append(Unit(begin, i - 1, text, paths[begin], table))
    return result


def inferred_role(unit: Unit) -> str:
    headings = " ".join(unit.heading_path).casefold()
    if "optional" in headings or "variant rule" in headings:
        return "optional_rule"
    if re.search(r"\b(as an optional rule|this optional rule|with this optional rule)\b", unit.text, re.I):
        return "optional_rule"
    if re.match(r"^[QA]:", unit.text):
        return "clarification"
    return "unclassified"


def is_homebrew(headings: tuple[str, ...]) -> bool:
    return any("homebrew" in heading.casefold() for heading in headings)


def prereq_lines(lines: list[str], ranges: list[list[int]]) -> tuple[str, list[list[int]]]:
    """Extract only explicit prerequisite declarations, not explanatory mentions."""
    found, spans = [], []
    for start, end in ranges:
        i = start
        while i <= end:
            label = plain(lines[i - 1])
            if re.match(r"^Prerequisites?:", label, re.I):
                begin = i
                text = [label]
                # Class prerequisite lists can follow a blank line and be nested.
                j = i + 1
                while j <= end and not lines[j - 1].strip():
                    j += 1
                if j <= end and re.match(r"^\s*- ", lines[j - 1]):
                    while j <= end and (not lines[j - 1].strip() or re.match(r"^\s*- ", lines[j - 1])):
                        text.append(plain(lines[j - 1]))
                        j += 1
                    i = j - 1
                found.append("\n".join(text).strip())
                spans.append([begin, i])
            i += 1
    return "\n\n".join(found), spans


def safe_fts_query(query: str) -> str:
    """Treat user text as terms, never as SQL or FTS operators."""
    stops = {"a", "an", "and", "are", "as", "at", "be", "can", "do", "does", "for", "how",
             "i", "in", "is", "it", "of", "on", "or", "the", "to", "use", "with", "what"}
    all_words = re.findall(r"\w+", unicodedata.normalize("NFKC", query), re.UNICODE)
    words = list(dict.fromkeys(word.casefold() for word in all_words if word.casefold() not in stops))
    words = (words or all_words)[:32]
    return " OR ".join('"' + word.replace('"', '""') + '"' for word in words)
