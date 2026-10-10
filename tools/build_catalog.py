#!/usr/bin/env python3
"""Build a deterministic, read-only navigation catalog for this SWSE snapshot.

Python 3.10+; standard library only. This is not a general Markdown/YAML/XLSX
parser, a rules interpreter, or a scraper. See catalog/README.md for its scope.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import posixpath
import re
import sys
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

SOURCE_DIR = Path("SWSE-Analysis")
EXPORT_DIR = SOURCE_DIR / "swse_wiki_export"
DEFAULT_WORKBOOK = SOURCE_DIR / "SWSE_Master_Reference_10-8-2026.xlsx"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
WIKI_HOSTS = {"swse.miraheze.org", "swse.fandom.com"}
ENTITY_CATEGORIES = {
    "Feats": "feat",
    "Talent Trees": "talent_tree",
    "Species": "species",
    "Force Powers": "force_power",
    "Prestige Classes": "prestige_class",
    "Heroic Classes": "heroic_class",
    "Destinies": "destiny",
}
SHEET_KINDS = {
    "Heroic Classes": "heroic_class",
    "Prestige Classes": "prestige_class",
    "Feats": "feat",
    "Force Powers": "force_power",
    "Talents": "talent_tree",
}
META_FIELDS = (
    "title", "source_url", "canonical_url", "source_host", "revision_id",
    "retrieved_at_utc", "content_sha256", "categories",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def within(base: Path, relative: str) -> Path:
    """Do not let a source manifest point outside its archive, even via symlinks."""
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError(f"Source path escapes its archive: {relative}")
    return path


def wiki_key(url: str) -> tuple[str, str] | None:
    """Normalize encoding/underscores, NOT disambiguators, namespaces or casing.

    Hosts remain part of identity. Fragments/query strings do not identify a
    different document; a resolved document does not validate a fragment.
    """
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.path.startswith("/wiki/"):
        return None
    title = re.sub(r"\s+", " ", unquote(parsed.path[len("/wiki/"):]).replace("_", " ")).strip()
    return (parsed.hostname or "", title)


class Resolver:
    def __init__(self, documents: list[dict]):
        self.canonical: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.aliases: dict[tuple[str, str], set[str]] = defaultdict(set)
        for doc in documents:
            for url, mapping in ((doc["canonical_url"], self.canonical),
                                 (doc["source_url"], self.aliases)):
                key = wiki_key(url)
                if key:
                    mapping[key].add(doc["canonical_url"])

    def match(self, url: str) -> dict:
        key = wiki_key(url)
        fragment = urlsplit(url).fragment
        suffix = {"fragment_unvalidated": fragment} if fragment else {}
        if not key or key[0] not in WIKI_HOSTS:
            return {"status": "not_swse_wiki", **suffix}
        if key in self.canonical or key in self.aliases:
            ids = self.canonical.get(key) or self.aliases[key]
            return {"status": "local_document", "document_ids": sorted(ids),
                    "matched_via": "canonical_url" if key in self.canonical else "source_url_alias",
                    **suffix}
        # A title on a different host is only a candidate, never a verified alias.
        if key[0] == "swse.fandom.com":
            candidates = self.canonical.get(("swse.miraheze.org", key[1]), set())
            if candidates:
                return {"status": "cross_host_title_candidate",
                        "candidate_document_ids": sorted(candidates), **suffix}
        return {"status": "not_exported", **suffix}


def inline_urls(text: str):
    """Yield HTTP destinations in the export's inline Markdown links.

    Balanced parentheses keep e.g. Armor_Proficiency_(Light) intact. Fenced
    code is ignored. Bare URLs, reference-style links and HTML aren't scanned.
    """
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence:
            continue
        for match in re.finditer(r"\]\((https?://)", line):
            pos = match.start(1)
            end, depth = pos, 0
            while end < len(line):
                char = line[end]
                if char.isspace():
                    break
                if char == "(":
                    depth += 1
                elif char == ")":
                    if not depth:
                        break
                    depth -= 1
                end += 1
            yield line[pos:end]


def export_parts(text: str) -> tuple[dict, str, int, int, int]:
    """Parse the JSON-valued front matter and generated wrapper in this export.

    content_sha256 hashes the *stripped article*, excluding front matter, the
    generated H1 and the '> Source:' line. It includes original scrape noise.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("Expected export front matter")
    close = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if close is None:
        raise ValueError("Unclosed front matter")
    meta = {}
    for line in lines[1:close]:
        if line.strip():
            name, value = line.split(":", 1)
            meta[name.strip()] = json.loads(value)
    source_line = next((i for i in range(close + 1, len(lines))
                        if lines[i].startswith("> Source:")), None)
    if source_line is None:
        raise ValueError("Expected the export's generated Source line")
    start = source_line + 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = len(lines)
    while end > start and not lines[end - 1].strip():
        end -= 1
    body = "".join(lines[source_line + 1:]).strip()
    return meta, body, start + 1, end, close + 1


def display_heading(text: str) -> str:
    # Display only; URLs, not this lossy label, are document identities.
    return re.sub(r"\[([^\]]*)\]\(https?://\S+(?:\s+\"[^\"]*\")?\)", r"\1", text)


def sections(text: str, front_matter_end: int) -> list[dict]:
    lines = text.splitlines()
    result = []
    for number, line in enumerate(lines, 1):
        if number <= front_matter_end:
            continue
        match = re.match(r"^(#{1,6}) (.+)$", line)
        if match:
            result.append({"heading": display_heading(match.group(2)),
                           "level": len(match.group(1)), "start_line": number})
    for i, section in enumerate(result):
        section["end_line"] = next(
            (other["start_line"] - 1 for other in result[i + 1:]
             if other["level"] <= section["level"]), len(lines))
    return result


def source_markers(text: str) -> list[dict]:
    result = []
    for number, line in enumerate(text.splitlines(), 1):
        if re.match(r"^\*Reference Books?:", line):
            books = []
            for url in inline_urls(line):
                key = wiki_key(url)
                if key:
                    books.append({"title": key[1], "url": url})
            # Includes linked FAQ/Jedi Counseling labels; these are declarations,
            # not a verified bibliography or an automatic authority assignment.
            result.append({"line": number, "declared_references": books})
    return result


def duplicates(values) -> list[dict]:
    return [{"value": value, "count": count} for value, count in sorted(Counter(values).items())
            if count > 1]


def zip_target(base: str, target: str) -> str:
    return target.lstrip("/") if target.startswith("/") else posixpath.normpath(
        posixpath.join(posixpath.dirname(base), target))


def relationships(archive: ZipFile, part: str) -> dict[str, str]:
    rel_path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if rel_path not in archive.namelist():
        return {}
    return {rel.attrib["Id"]: zip_target(part, rel.attrib["Target"])
            for rel in ET.fromstring(archive.read(rel_path))
            if rel.attrib.get("TargetMode") != "External"}


def workbook_catalog(path: Path, root: Path, resolver: Resolver) -> tuple[list[dict], dict]:
    """Read OOXML directly; retain raw cells/coordinates, don't evaluate formulas."""
    records, sheet_summaries = [], []
    workbook_path = path.relative_to(root).as_posix()
    workbook_hash = sha256(path.read_bytes())
    with ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(t.text or "" for t in item.findall(".//m:t", NS))
                       for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = relationships(archive, "xl/workbook.xml")
        for sheet in workbook.findall("m:sheets/m:sheet", NS):
            name = sheet.attrib["name"]
            part = rels[sheet.attrib[REL_ID]]
            xml = ET.fromstring(archive.read(part))
            xml_rows = xml.findall("m:sheetData/m:row", NS)
            populated, formula_cells = [], {}
            for row in xml_rows:
                cells, formulas = {}, {}
                for cell in row.findall("m:c", NS):
                    reference = cell.attrib["r"]
                    value = cell.find("m:v", NS)
                    cell_type = cell.attrib.get("t")
                    if cell_type == "s" and value is not None:
                        text = strings[int(value.text)]
                    elif cell_type == "inlineStr":
                        text = "".join(t.text or "" for t in cell.findall("m:is//m:t", NS))
                    else:
                        text = (value.text or "") if value is not None else ""
                    if text != "":
                        cells[reference] = text
                    formula = cell.find("m:f", NS)
                    if formula is not None:
                        formulas[reference] = {"formula_xml": dict(formula.attrib),
                                               "formula": formula.text,
                                               "cached_value": text if value is not None else None}
                if cells or formulas:
                    populated.append((int(row.attrib["r"]), cells, formulas))
                    formula_cells.update(formulas)
            tables = []
            sheet_rels = relationships(archive, part)
            for table_part in xml.findall("m:tableParts/m:tablePart", NS):
                table = ET.fromstring(archive.read(sheet_rels[table_part.attrib[REL_ID]]))
                tables.append({"name": table.attrib["name"], "range": table.attrib["ref"],
                               "header_row_count": int(table.attrib.get("headerRowCount", "1")),
                               "columns": [col.attrib["name"] for col in
                                           table.findall("m:tableColumns/m:tableColumn", NS)]})
            header_rows = set()
            if name in SHEET_KINDS and populated:
                header_rows.add(populated[0][0])
                for table in tables:
                    if table["header_row_count"]:
                        header_rows.add(int(re.search(r"\d+", table["range"]).group()))
            headers, markers = [], []
            matches, hosts = Counter(), Counter()
            missing, by_label, by_url = [], defaultdict(list), defaultdict(list)
            scope, section_label, header_row, record_count, url_count = "unmarked", None, None, 0, 0
            for number, cells, formulas in populated:
                label = cells.get(f"A{number}", "")
                if number in header_rows:
                    header_row = number
                    headers.append({"row": number, "cells": cells})
                    continue
                if label == "Homebrew" or re.fullmatch(r"\[\[.+\]\]", label):
                    section_label = label
                    if label == "Homebrew":
                        scope = "explicit_homebrew"
                    markers.append({"row": number, "label": label})
                    continue
                links = []
                for cell, value in cells.items():
                    if value.startswith(("http://", "https://")):
                        match = resolver.match(value)
                        links.append({"cell": cell, "url": value, **match})
                        matches[match["status"]] += 1
                        hosts[urlsplit(value).hostname or ""] += 1
                        by_url[value].append(number)
                        url_count += 1
                        if match["status"] in {"not_exported", "not_swse_wiki"}:
                            missing.append({"row": number, "cell": cell, "label": label,
                                            "url": value, "status": match["status"]})
                if name in SHEET_KINDS:
                    record_count += 1
                    by_label[label].append(number)
                    record = {
                        "workbook": workbook_path, "workbook_sha256": workbook_hash,
                        "sheet": name, "row": number, "header_row": header_row,
                        "label": label, "entity_type_hint": SHEET_KINDS[name],
                        "scope": scope, "cells": cells, "links": links,
                    }
                    if section_label:
                        record["section_label"] = section_label
                    if formulas:
                        record["formulas_not_evaluated"] = formulas
                    records.append(record)
            sheet_summaries.append({
                "name": name, "state": sheet.attrib.get("state", "visible"),
                "xml_row_count": len(xml_rows), "populated_row_count": len(populated),
                "record_count": record_count, "literal_url_cell_count": url_count,
                "url_hosts": dict(sorted(hosts.items())), "link_match_counts": dict(sorted(matches.items())),
                "unresolved_literal_urls": missing,
                "duplicate_record_labels": [{"label": label, "rows": rows}
                                            for label, rows in sorted(by_label.items()) if len(rows) > 1],
                "duplicate_literal_urls": [{"url": url, "rows": rows}
                                           for url, rows in sorted(by_url.items()) if len(rows) > 1],
                "headers": headers, "section_markers": markers, "tables": tables,
                "merged_ranges": [merge.attrib["ref"] for merge in
                                  xml.findall("m:mergeCells/m:mergeCell", NS)],
                "hyperlink_element_count": len(xml.findall("m:hyperlinks/m:hyperlink", NS)),
                "formula_cells_not_evaluated": formula_cells,
            })
    return records, {"path": workbook_path, "sha256": workbook_hash,
                     "record_count": len(records), "sheets": sheet_summaries}


def build_catalog(root: Path, output: Path, workbook: Path | None = None) -> dict:
    root, output = root.resolve(), output.resolve()
    if output.is_relative_to((root / SOURCE_DIR).resolve()):
        raise ValueError("The catalog must live outside the source archive")
    workbook = (workbook or root / DEFAULT_WORKBOOK).resolve()
    if not workbook.is_relative_to(root):
        raise ValueError("Workbook must be inside the repository")
    export = root / EXPORT_DIR
    index_path = export / "index.jsonl"
    index = json_lines(index_path)
    for field in ("canonical_url", "path"):
        if duplicates(row[field] for row in index):
            raise ValueError(f"Duplicate document identity in source index: {field}")
    resolver = Resolver(index)
    documents, category_counts, kind_counts = [], Counter(), Counter()
    link_counts, gap_counts, gap_sources, gap_urls = Counter(), Counter(), defaultdict(set), {}
    noise, article_sizes, repeated_headings = Counter(), [], []
    integrity_errors = []
    indexed_paths = {row["path"] for row in index}
    unindexed = sorted(file.relative_to(export).as_posix() for file in export.rglob("*.md")
                       if file.relative_to(export).as_posix() not in indexed_paths)
    if unindexed:
        integrity_errors.append(f"Unindexed Markdown files: {unindexed}")
    for row in sorted(index, key=lambda entry: entry["canonical_url"]):
        file = within(export, row["path"])
        if not file.is_file():
            integrity_errors.append(f"Missing indexed file: {row['path']}")
            continue
        raw = file.read_bytes()
        text = raw.decode("utf-8")
        meta, body, start_line, end_line, front_end = export_parts(text)
        computed_hash = sha256(body.encode("utf-8"))
        if computed_hash != row["content_sha256"] or len(body) != row["character_count"]:
            integrity_errors.append(f"Article hash/count mismatch: {row['path']}")
        for field in META_FIELDS:
            if meta.get(field) != row[field]:
                integrity_errors.append(f"Front matter/index mismatch ({field}): {row['path']}")
        entity_types = [kind for category, kind in ENTITY_CATEGORIES.items()
                        if category in row["categories"]]
        key = wiki_key(row["canonical_url"])
        kind = "category" if key and key[1].startswith("Category:") else (
            entity_types[0] if entity_types else "reference")
        category_counts.update(row["categories"])
        kind_counts[kind] += 1
        article_sizes.append(len(body))
        page_sections = sections(text, front_end)
        repeated = duplicates(section["heading"] for section in page_sections)
        if repeated:
            repeated_headings.append({"title": row["title"], "headings": repeated})
        markers = source_markers(text)
        local_ids, unresolved, total = set(), 0, 0
        for url in inline_urls(body):
            total += 1
            match = resolver.match(url)
            key = wiki_key(url)
            if not key or key[0] not in WIKI_HOSTS:
                link_counts["non_swse_link_occurrences"] += 1
                continue
            link_counts["swse_link_occurrences"] += 1
            if match["status"] == "local_document":
                link_counts["local_document_link_occurrences"] += 1
                local_ids.update(match["document_ids"])
                if urlsplit(url).fragment:
                    link_counts["local_document_fragments_unvalidated"] += 1
            else:
                unresolved += 1
                link_counts["no_local_document_link_occurrences"] += 1
                gap_counts[key] += 1
                gap_sources[key].add((EXPORT_DIR / row["path"]).as_posix())
                gap_urls.setdefault(key, url.split("#", 1)[0])
        if "Loading comments..." in body:
            noise["pages_with_loading_comments"] += 1
        if "Jedi CounselingJedi Counseling" in body:
            noise["pages_with_duplicated_jedi_counseling_label"] += 1
        record = {
            "document_id": row["canonical_url"], "title": row["title"],
            "path": (EXPORT_DIR / row["path"]).as_posix(), "document_kind_hint": kind,
            "entity_type_hints": entity_types, "categories": row["categories"],
            "source_url": row["source_url"], "canonical_url": row["canonical_url"],
            "revision_id": row["revision_id"], "retrieved_at_utc": row["retrieved_at_utc"],
            "article_sha256": computed_hash, "file_sha256": sha256(raw),
            "article_characters": len(body), "file_bytes": len(raw),
            "article_start_line": start_line, "article_end_line": end_line,
            "sections": page_sections, "source_markers": markers,
            "has_markdown_table": bool(re.search(r"^\|\s*:?-{3,}", body, re.M)),
            "linked_document_ids": sorted(local_ids),
            "article_inline_link_count": total, "no_local_document_link_count": unresolved,
        }
        documents.append(record)
    if integrity_errors:
        raise ValueError("Source integrity checks failed; catalog not overwritten:\n" +
                         "\n".join(integrity_errors))
    records, workbook_summary = workbook_catalog(workbook, root, resolver)
    missing_targets = [
        {"host": key[0], "wiki_title": key[1], "example_url": gap_urls[key],
         "occurrences": count, "source_document_count": len(gap_sources[key]),
         "sample_source_paths": sorted(gap_sources[key])[:3],
         "status": "no_local_document_not_a_semantic_coverage_test"}
        for key, count in sorted(gap_counts.items(), key=lambda item:
                                (-len(gap_sources[item[0]]), -item[1], item[0]))
    ]
    sizes = sorted(article_sizes)
    input_paths = [index_path, workbook, export / "report.json"]
    audit = {
        "schema_version": 1,
        "method": "Local snapshot only; no network, rules verification, or source edits.",
        "inputs": [{"path": path.relative_to(root).as_posix(), "sha256": sha256(path.read_bytes())}
                   for path in input_paths],
        "wiki": {
            "document_count": len(documents), "markdown_bytes": sum(doc["file_bytes"] for doc in documents),
            "article_characters": sum(article_sizes),
            "source_hosts": dict(sorted(Counter(row["source_host"] for row in index).items())),
            "retrieval_range_utc": [min(row["retrieved_at_utc"] for row in index),
                                    max(row["retrieved_at_utc"] for row in index)] if index else [],
            "verified_article_hashes": len(documents), "verified_front_matter_records": len(documents),
            "hash_scope": "Stripped article after generated Source line, including scrape noise; not full file.",
            "duplicate_titles": duplicates(row["title"] for row in index),
            "duplicate_article_hashes": duplicates(row["content_sha256"] for row in index),
            "unindexed_files": unindexed,
            "document_kind_hints": dict(sorted(kind_counts.items())),
            "category_counts": dict(sorted(category_counts.items())),
            "article_size_characters": {
                "minimum": sizes[0] if sizes else 0,
                "median": sizes[len(sizes) // 2] if sizes else 0,
                "p90_floor_rank": sizes[int((len(sizes) - 1) * .9)] if sizes else 0,
                "maximum": sizes[-1] if sizes else 0,
                "over_20000": sum(size > 20000 for size in sizes),
                "over_50000": sum(size > 50000 for size in sizes),
            },
            "section_heading_count": sum(len(doc["sections"]) for doc in documents),
            "pages_with_multiple_source_markers": sum(len(doc["source_markers"]) > 1 for doc in documents),
            "pages_with_markdown_tables": sum(doc["has_markdown_table"] for doc in documents),
            "repeated_headings": repeated_headings, "scrape_noise": dict(sorted(noise.items())),
            "link_scan_scope": "Inline HTTP Markdown destinations in article only; excludes generated Source link.",
            "link_counts": dict(sorted(link_counts.items())),
            "distinct_targets_without_local_document": len(missing_targets),
            "top_targets_without_local_document": [
                {key: value for key, value in target.items() if key != "sample_source_paths"}
                for target in missing_targets[:25]],
        },
        "workbook": workbook_summary,
        "last_export_run": json.loads((export / "report.json").read_text(encoding="utf-8")),
        "limitations": [
            "Document/category hints are not a curated rules/entity taxonomy.",
            "A local document match does not select a rule variant or verify its provenance.",
            "Cross-host title candidates require review; disambiguators are never stripped.",
            "Absent linked pages can have partial coverage embedded in another article.",
            "Source markers can include FAQs and do not determine authority or optional-rule adoption.",
            "Workbook cells are literal strings/cached values, not parsed game mechanics.",
            "Workbook embedded hyperlink targets are not exported; primary links use literal URL cells.",
            "The Links intake sheet is audited, not duplicated in workbook_records.jsonl.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, entries in (("wiki_documents.jsonl", documents),
                          ("workbook_records.jsonl", records),
                          ("missing_wiki_targets.jsonl", missing_targets)):
        content = "".join(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
                          for entry in entries)
        (output / name).write_text(content, encoding="utf-8")
    (output / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    return audit


def find_entries(root: Path, output: Path, query: str) -> list[dict]:
    """Lookup labels/headings, not full text. Refuse stale snapshot coordinates."""
    audit = json.loads((output / "audit.json").read_text(encoding="utf-8"))
    for source in audit["inputs"]:
        file = within(root, source["path"])
        if not file.is_file() or sha256(file.read_bytes()) != source["sha256"]:
            raise ValueError(f"Stale catalog input: {source['path']}; rebuild the catalog")
    documents = json_lines(output / "wiki_documents.jsonl")
    indexed = {doc["path"] for doc in documents}
    current = {file.relative_to(root).as_posix() for file in (root / EXPORT_DIR).rglob("*.md")}
    if current != indexed:
        raise ValueError("Stale catalog Markdown inventory; rebuild the catalog")
    result, term = [], query.casefold()
    for doc in documents:
        file = within(root, doc["path"])
        if not file.is_file() or sha256(file.read_bytes()) != doc["file_sha256"]:
            raise ValueError(f"Stale catalog document: {doc['path']}; rebuild the catalog")
        matched = [section for section in doc["sections"] if term in section["heading"].casefold()]
        if term in doc["title"].casefold() or matched:
            result.append({"type": "wiki_document", "title": doc["title"], "path": doc["path"],
                           "canonical_url": doc["canonical_url"], "revision_id": doc["revision_id"],
                           "article_sha256": doc["article_sha256"], "matching_sections": matched,
                           "source_markers": doc["source_markers"]})
    for row in json_lines(output / "workbook_records.jsonl"):
        if term in row["label"].casefold():
            result.append({"type": "workbook_record", **row})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("catalog"))
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--find", metavar="TEXT", help="Search catalog titles/headings and workbook labels, not full text")
    args = parser.parse_args(argv)
    root = args.repo.resolve()
    output = (root / args.output).resolve()
    try:
        if args.find is not None:
            if not args.find.strip():
                raise ValueError("Lookup text must not be empty")
            for entry in find_entries(root, output, args.find):
                print(json.dumps(entry, ensure_ascii=False))
        else:
            audit = build_catalog(root, output, root / args.workbook)
            print(f"Catalog: {output}")
            print(f"Verified {audit['wiki']['document_count']} wiki documents; "
                  f"mapped {audit['workbook']['record_count']} workbook records.")
            print(f"Reported {audit['wiki']['distinct_targets_without_local_document']} linked targets "
                  "without a local document (not a test of semantic rules coverage).")
        return 0
    except (ValueError, KeyError, OSError, ET.ParseError, BadZipFile) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
