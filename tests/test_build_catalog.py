"""Regression checks for the local navigation catalog; no third-party packages."""
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from xml.sax.saxutils import escape
from zipfile import ZipFile

from tools.build_catalog import (
    EXPORT_DIR, Resolver, build_catalog, export_parts, find_entries, inline_urls,
    json_lines, main, sections, sha256, wiki_key, workbook_catalog,
)

ROOT = Path(__file__).resolve().parents[1]
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def cell(reference, value):
    return f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'


def row(number, values, extra=""):
    return (f'<row r="{number}">' +
            "".join(cell(f"{column}{number}", value) for column, value in values.items()) +
            extra + '</row>')


def fixture_workbook(path):
    """Sparse columns, rich shared strings, a second header and styled empties."""
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", f'''<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">
          <sheets><sheet name="Heroic Classes" sheetId="1" r:id="r1"/>
          <sheet name="Force Powers" sheetId="2" r:id="r2"/>
          <sheet name="Links" sheetId="3" r:id="r3"/></sheets></workbook>''')
        archive.writestr("xl/_rels/workbook.xml.rels", '''<Relationships>
          <Relationship Id="r1" Target="/xl/worksheets/sheet1.xml"/>
          <Relationship Id="r2" Target="worksheets/sheet2.xml"/>
          <Relationship Id="r3" Target="worksheets/sheet3.xml"/></Relationships>''')
        archive.writestr("xl/sharedStrings.xml", f'''<sst xmlns="{MAIN_NS}">
          <si><r><t>Force </t></r><r><t>Prodigy</t></r></si></sst>''')
        hero = (row(1, {"A": "CLASS", "H": "LINKS"}) +
                row(2, {"A": "Jedi", "H": "https://swse.miraheze.org/wiki/Jedi"}) +
                row(3, {"A": "Homebrew"}) +
                row(4, {"H": "https://swse.fandom.com/wiki/Force_Prodigy"},
                    '<c r="A4" t="s"><v>0</v></c>') +
                '<row r="999"><c r="A999" s="1"/></row>')
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{MAIN_NS}"><sheetData>{hero}</sheetData></worksheet>')
        powers = (row(1, {"A": "FORCE POWER", "C": "TYPE", "F": "Links"}) +
                  row(2, {"A": "Battle Strike", "C": "N/A", "F": "https://swse.fandom.com/wiki/Battle_Strike"}) +
                  row(67, {"A": "FORM POWER", "B": "FORM", "F": "Links"}) +
                  row(68, {"A": "Unhindered Charge", "B": "Sokan", "F": "https://swse.fandom.com/wiki/Unhindered_Charge"}) +
                  row(69, {"A": "Formula test"}, '<c r="D69"><f>1+1</f><v>2</v></c><c r="E69"><f>2+2</f></c>'))
        archive.writestr("xl/worksheets/sheet2.xml", f'''<worksheet xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">
          <sheetData>{powers}</sheetData><mergeCells><mergeCell ref="A1:B1"/>
          <mergeCell ref="A2:B2"/></mergeCells><tableParts><tablePart r:id="t1"/></tableParts></worksheet>''')
        archive.writestr("xl/worksheets/_rels/sheet2.xml.rels", '''<Relationships>
          <Relationship Id="t1" Target="../tables/table1.xml"/></Relationships>''')
        archive.writestr("xl/tables/table1.xml", f'''<table xmlns="{MAIN_NS}" name="FormPowers" ref="A67:F69">
          <tableColumns><tableColumn name="FORM POWER"/><tableColumn name="FORM"/></tableColumns></table>''')
        links = row(1, {"A": "[[Main]]"}) + row(2, {"A": "http://www.w3.org/1999/xhtml"})
        archive.writestr("xl/worksheets/sheet3.xml", f'<worksheet xmlns="{MAIN_NS}"><sheetData>{links}</sheetData></worksheet>')


def fixture_repository(root):
    export = root / EXPORT_DIR
    page = export / "pages/example.md"
    page.parent.mkdir(parents=True)
    body = "*Reference Book: [Core Rulebook](https://swse.miraheze.org/wiki/Core_Rulebook) *\n\n## Sample rule\n\nText."
    metadata = {
        "title": "Example", "source_url": "https://swse.miraheze.org/wiki/Example",
        "canonical_url": "https://swse.miraheze.org/wiki/Example", "source_host": "swse.miraheze.org",
        "revision_id": "1", "retrieved_at_utc": "2026-10-09T00:00:00Z",
        "content_sha256": sha256(body.encode()), "categories": [],
    }
    wrapper = "---\n" + "".join(f"{key}: {json.dumps(value)}\n" for key, value in metadata.items())
    page.write_text(wrapper + "---\n\n# Example\n\n> Source: example\n\n" + body + "\n", encoding="utf-8")
    entry = {**metadata, "path": "pages/example.md", "character_count": len(body)}
    (export / "index.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    (export / "report.json").write_text('{"counts": {"failed": 0}}', encoding="utf-8")
    workbook = root / "SWSE-Analysis/reference.xlsx"
    fixture_workbook(workbook)
    return page, workbook


class ParserTests(unittest.TestCase):
    def test_url_identity_preserves_disambiguators_namespaces_and_hosts(self):
        self.assertEqual(wiki_key("https://swse.fandom.com/wiki/Vornskr%27s_Ferocity#Details"),
                         ("swse.fandom.com", "Vornskr's Ferocity"))
        self.assertEqual(wiki_key("https://swse.miraheze.org/wiki/Category%3AForce_Powers?oldid=1"),
                         ("swse.miraheze.org", "Category:Force Powers"))
        self.assertNotEqual(wiki_key("https://swse.miraheze.org/wiki/Force_Storm_(FUCG)"),
                            wiki_key("https://swse.miraheze.org/wiki/Force_Storm"))
        self.assertNotEqual(wiki_key("https://swse.miraheze.org/wiki/Force_Storm"),
                            wiki_key("https://swse.miraheze.org/wiki/force_storm"))
        self.assertIsNone(wiki_key("http://www.w3.org/1999/xhtml"))

    def test_mirror_title_is_candidate_not_verified_alias(self):
        resolver = Resolver([{"canonical_url": "https://swse.miraheze.org/wiki/Category:Armor",
                              "source_url": "https://swse.miraheze.org/wiki/Armor"},
                             {"canonical_url": "https://swse.miraheze.org/wiki/Battle_Strike",
                              "source_url": "https://swse.miraheze.org/wiki/Battle_Strike"}])
        alias = resolver.match("https://swse.miraheze.org/wiki/Armor")
        self.assertEqual(alias["status"], "local_document")
        self.assertEqual(alias["matched_via"], "source_url_alias")
        candidate = resolver.match("https://swse.fandom.com/wiki/Battle_Strike")
        self.assertEqual(candidate["status"], "cross_host_title_candidate")
        self.assertNotIn("document_ids", candidate)
        self.assertEqual(resolver.match("https://swse.fandom.com/wiki/Blind")["status"], "not_exported")
        fragment = resolver.match("https://swse.miraheze.org/wiki/Battle_Strike#Not_verified")
        self.assertEqual(fragment["fragment_unvalidated"], "Not_verified")

    def test_links_keep_parentheses_and_skip_fenced_code(self):
        text = ('[a](https://swse.miraheze.org/wiki/Armor_Proficiency_(Light) "Light")\n'
                '[b](https://swse.miraheze.org/wiki/Knowledge_(Life_Sciences))\n'
                '```md\n[ignored](https://example.com/ignored)\n```\n'
                '[c](https://example.com/ok)')
        self.assertEqual(list(inline_urls(text)), [
            "https://swse.miraheze.org/wiki/Armor_Proficiency_(Light)",
            "https://swse.miraheze.org/wiki/Knowledge_(Life_Sciences)", "https://example.com/ok"])

    def test_article_hash_excludes_wrapper_but_not_scrape_noise(self):
        text = ('---\ntitle: "Example"\ncategories: []\n---\n\n# Example\n\n'
                '> Source: generated\n\nParagraph.\n\nLoading comments...\n\n')
        metadata, body, start, end, front_end = export_parts(text)
        self.assertEqual(metadata, {"title": "Example", "categories": []})
        self.assertEqual(body, "Paragraph.\n\nLoading comments...")
        self.assertEqual((start, end, front_end), (10, 12, 4))
        self.assertNotEqual(sha256(text.encode()), sha256(body.encode()))

    def test_section_ranges_preserve_hierarchy_and_repeated_names(self):
        text = '# Page\n## Repeat\nA\n### Child\nB\n## Repeat\nC\n'
        result = sections(text, 0)
        self.assertEqual([(s["heading"], s["start_line"], s["end_line"]) for s in result],
                         [("Page", 1, 7), ("Repeat", 2, 5), ("Child", 4, 5), ("Repeat", 6, 7)])

    def test_workbook_keeps_sparse_cells_headers_and_homebrew_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "fixture.xlsx"
            fixture_workbook(workbook)
            resolver = Resolver([{"canonical_url": "https://swse.miraheze.org/wiki/Battle_Strike",
                                  "source_url": "https://swse.miraheze.org/wiki/Battle_Strike"}])
            records, summary = workbook_catalog(workbook, root, resolver)
            hero = [record for record in records if record["sheet"] == "Heroic Classes"]
            self.assertEqual(len(hero), 2)
            self.assertEqual(hero[1]["label"], "Force Prodigy")
            self.assertEqual(hero[1]["scope"], "explicit_homebrew")
            self.assertEqual(summary["sheets"][0]["xml_row_count"], 5)
            self.assertEqual(summary["sheets"][0]["populated_row_count"], 4)
            powers = [record for record in records if record["sheet"] == "Force Powers"]
            self.assertEqual(powers[0]["cells"]["C2"], "N/A")
            self.assertNotIn("B2", powers[0]["cells"])
            self.assertEqual(powers[0]["links"][0]["status"], "cross_host_title_candidate")
            self.assertEqual(powers[1]["header_row"], 67)
            self.assertEqual(powers[1]["cells"]["B68"], "Sokan")
            self.assertEqual(powers[2]["formulas_not_evaluated"]["D69"]["cached_value"], "2")
            self.assertIsNone(powers[2]["formulas_not_evaluated"]["E69"]["cached_value"])
            self.assertEqual(summary["sheets"][2]["link_match_counts"], {"not_swse_wiki": 1})
            self.assertFalse(any(record["sheet"] == "Links" for record in records))


class BuildTests(unittest.TestCase):
    def test_snapshot_round_trip_is_deterministic_and_does_not_edit_sources(self):
        files = [file for file in (ROOT / "SWSE-Analysis").rglob("*") if file.is_file()]
        before = {file: sha256(file.read_bytes()) for file in files}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "catalog"
            audit = build_catalog(ROOT, output)
            first = {file.name: file.read_bytes() for file in output.iterdir()}
            build_catalog(ROOT, output)
            self.assertEqual(first, {file.name: file.read_bytes() for file in output.iterdir()})
            index = json_lines(ROOT / EXPORT_DIR / "index.jsonl")
            self.assertEqual(audit["wiki"]["verified_article_hashes"], len(index))
            self.assertEqual(audit["wiki"]["verified_front_matter_records"], len(index))
            self.assertEqual(len(json_lines(output / "wiki_documents.jsonl")), len(index))
            hits = find_entries(ROOT, output, "Armored Defense")
            self.assertTrue(any(hit.get("title") == "Armor Specialist Talent Tree" for hit in hits))
            # Preserve the two distinct same-named book variants instead of deduplicating.
            hits = find_entries(ROOT, output, "Staggering Attack")
            self.assertEqual(len([hit for hit in hits if hit["type"] == "workbook_record"]), 2)
        self.assertEqual(before, {file: sha256(file.read_bytes()) for file in files})

    def test_integrity_failure_does_not_overwrite_existing_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page, workbook = fixture_repository(root)
            output = root / "catalog"
            build_catalog(root, output, workbook)
            before = {file.name: file.read_bytes() for file in output.iterdir()}
            page.write_text(page.read_text().replace("Text.", "Changed text."), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash/count mismatch"):
                build_catalog(root, output, workbook)
            self.assertEqual(before, {file.name: file.read_bytes() for file in output.iterdir()})
            with self.assertRaisesRegex(ValueError, "Stale catalog document"):
                find_entries(root, output, "Sample")

    def test_front_matter_disagreement_fails_even_with_valid_article_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page, workbook = fixture_repository(root)
            output = root / "catalog"
            build_catalog(root, output, workbook)
            before = (output / "audit.json").read_bytes()
            page.write_text(page.read_text().replace('title: "Example"', 'title: "Wrong title"'),
                            encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Front matter/index mismatch"):
                build_catalog(root, output, workbook)
            self.assertEqual(before, (output / "audit.json").read_bytes())

    def test_lookup_rejects_changed_workbook_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, workbook = fixture_repository(root)
            output = root / "catalog"
            build_catalog(root, output, workbook)
            with ZipFile(workbook, "a") as archive:
                archive.writestr("changed.txt", "Changed input fingerprint")
            with self.assertRaisesRegex(ValueError, "Stale catalog input"):
                find_entries(root, output, "Example")

    def test_new_unindexed_page_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page, workbook = fixture_repository(root)
            output = root / "catalog"
            build_catalog(root, output, workbook)
            (page.parent / "unindexed.md").write_text("New data", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unindexed Markdown"):
                build_catalog(root, output, workbook)
            with self.assertRaisesRegex(ValueError, "Stale catalog Markdown inventory"):
                find_entries(root, output, "Example")

    def test_cli_returns_nonzero_for_stale_or_malformed_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, workbook = fixture_repository(root)
            output = root / "catalog"
            build_catalog(root, output, workbook)
            workbook.write_bytes(b"Not an XLSX ZIP archive")
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = main(["--repo", str(root), "--find", "Example"])
            self.assertEqual(code, 1)
            self.assertIn("Stale catalog input", errors.getvalue())
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = main(["--repo", str(root), "--workbook", str(workbook)])
            self.assertEqual(code, 1)
            self.assertIn("not a zip file", errors.getvalue())

    def test_cannot_write_catalog_into_source_archive(self):
        with self.assertRaisesRegex(ValueError, "outside the source archive"):
            build_catalog(ROOT, ROOT / EXPORT_DIR / "catalog")


if __name__ == "__main__":
    unittest.main()
