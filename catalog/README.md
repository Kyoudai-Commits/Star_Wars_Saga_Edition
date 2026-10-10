# Agent navigation catalog

These files map the original uploads without moving, changing or cleaning them. The original four maps are **document/summary navigation metadata**. A separate implemented entity/FTS5 layer now uses them and versioned curation; see [agent retrieval](../docs/AGENT_RETRIEVAL.md). Neither layer is independent proof of published-rule authority or a complete game-rules interpreter.

## Build and lookup

Python **3.10+**, standard library only. From the repository root:

```bash
python tools/build_catalog.py
python tools/build_catalog.py --find "Armored Defense"
python tools/build_catalog.py --find "Staggering Attack"
python -m unittest discover -s tests -v
```

Optional arguments: `--repo PATH`, `--output PATH` (defaults to `catalog/` relative to the repository), and `--workbook PATH` (defaults to the uploaded workbook). The builder will not write inside `SWSE-Analysis/`.

`--find` performs case-insensitive substring matching on **wiki titles/headings and workbook labels only**. It returns JSON lines with source coordinates and marker locations; it does not search body text, resolve semantic aliases or answer rules questions. Use a text-search tool such as `rg` for body searches, and read original sources for conclusions. Lookup checks source-input and Markdown fingerprints and refuses stale mappings.

Outputs are deterministic for unchanged inputs. Rebuilding overwrites the four generated files below but not this guide. The original export manifest, workbook and last-run report have fingerprints in `audit.json`; each wiki document additionally has a full-file hash. Missing files, unindexed Markdown, article hash/count mismatches, front-matter disagreement or duplicate document identities make the build fail without overwriting an existing catalog.

## Generated files

| File | Granularity | How to use it |
| --- | --- | --- |
| `wiki_documents.jsonl` | One record per exported page: 809 in this snapshot | Find page identities, embedded headings, source-marker lines and local reference neighbors |
| `workbook_records.jsonl` | One record per subject-sheet data row: 644 | Read spreadsheet summaries without opening XLSX; retain sheet/row/cell provenance |
| `missing_wiki_targets.jsonl` | One record per normalized linked host/title with no local document: 2,622 | Prioritize document-coverage investigation; not a list of proven missing game rules |
| `audit.json` | One repository audit object | Read source fingerprints, sheet/header/table structure, counts, anomalies and last import errors |

Do not load all of these into an agent prompt. Query selected records or construct specific views.

### Wiki document fields

- `document_id` / `canonical_url`: the page's canonical URL. A document ID is **not** a game-entity or rule-variant ID.
- `title`, `path`, `source_url`, `revision_id`, `retrieved_at_utc`: original provenance and repository-root-relative source path.
- `document_kind_hint`, `entity_type_hints`, `categories`: category-based navigation, not an authoritative taxonomy. Hints can overlap; Corruption has both force-power and destiny hints.
- `article_sha256`, `article_characters`: verified against the source manifest. The article is the stripped content after the generated `> Source:` line, excluding front matter and generated H1/source wrapper. It **includes** scrape noise.
- `file_sha256`, `file_bytes`: fingerprint/size of the entire original file.
- `article_start_line`, `article_end_line`: original-file coordinates, **1-based and inclusive**.
- `sections`: heading label, level and original-file start/end. End extends through descendants to just before the next equal-or-higher-level heading. Parent/child spans therefore overlap; repeated labels are preserved as separate positions. These are navigation spans, not final retrieval chunks.
- `source_markers`: original-file lines containing Reference Book(s), plus linked reference labels/URLs. These can include FAQ/Jedi Counseling references. They are declarations and locations, **not verified bibliography entries or automatically inferred source/adoption ranges**.
- `linked_document_ids`: deduplicated local document neighbors found in article inline links. The only relation asserted is **references**; not prerequisites, eligibility, stacking or other game logic.
- `has_markdown_table`, `article_inline_link_count`, `no_local_document_link_count`: retrieval/coverage hints.

A single H1-only page can still contain multiple source-specific rules separated by Reference Book markers, as Staggering Attack does. Use the assessment's collision examples before building rule-level chunks.

### Workbook record fields

- `workbook`, `workbook_sha256`, `sheet`, `row`: exact source location and snapshot fingerprint.
- `header_row`: which header applies. Column meaning comes from the matching `audit.json` sheet `headers` entry. Force Powers uses row 1 for general powers and row 67 for form powers.
- `label`, `entity_type_hint`: first-column label and subject-sheet type hint. Talents means **talent_tree**.
- `scope`: `explicit_homebrew` only when under the workbook's Homebrew marker; otherwise `unmarked`. **Unmarked does not mean verified official.**
- `section_label`: an explicit section marker if applicable.
- `cells`: original cell references mapped to literal strings. Sparse columns remain sparse, merged blanks are not filled, newlines and summary wording are retained. Do not interpret commas, abbreviations or prerequisite logic mechanically without review.
- `links`: primary literal URL cells with match status. Embedded Excel hyperlink targets are not exported as a semantic graph; the audit records hyperlink-element counts.
- `formulas_not_evaluated`: present only if formulas are encountered; formula XML and cached value are preserved, not recalculated. There are none in this uploaded workbook. Numeric/date cell representations, if added later, are not converted into typed domain values.

The Links intake sheet is audited but not duplicated into the subject-record file. Its section markers and unrelated W3C URL do not become entities. Styled empty spreadsheet rows, headers and section markers are not subject records.

### Link-match status

| Status | Meaning |
| --- | --- |
| `local_document` | Same normalized host/title matches an indexed canonical URL or recorded source-URL alias; `document_ids` names the matching documents |
| `cross_host_title_candidate` | Fandom title matches a Miraheze canonical title; `candidate_document_ids` is **not a verified alias** |
| `not_exported` | No local document or exact cross-host title candidate was found |
| `not_swse_wiki` | Not an HTTP(S) `/wiki/` URL on either recognized SWSE host |

A document match does not select the correct variant within it or prove the URL's full rules are locally supported. URL fragments are retained as `fragment_unvalidated` if present; only the parent document has been matched.

Normalization decodes percent escapes and replaces underscores with spaces. It retains host, namespace, disambiguators and title casing; it does not strip `(FUCG)` or globally map Blind to Force Blind. Reviewed aliases and variant selections should be added as separate curated data.

### Missing-target fields

`host`, `wiki_title` and `example_url` identify a normalized target; `occurrences`, `source_document_count` and up to three `sample_source_paths` explain its relevance. Records are ordered by descending referencing-document count, then occurrences, then target identity. Counts scan **article inline HTTP Markdown links only**, not generated Source links, bare URLs or the workbook.

The status explicitly describes document absence, **not semantic coverage**. Embedded sections, book metadata, lore and terminology references need different treatment. Prioritize evidence needed for the task rather than crawling every entry.

## Scope and limitations

- The parser is scoped to the uploaded export's JSON-valued YAML front matter, generated Source wrapper, ATX headings, inline HTTP links and OOXML workbook. It is not a general YAML/Markdown/Excel implementation. Inline-link scanning handles balanced parentheses and skips fenced code; reference-style links, bare URLs and HTML are outside that scan.
- The catalog does not remove UI boilerplate from raw files, infer prerequisite logic, resolve tab/source collisions, verify official source authority, select optional rules, or download additional pages.
- Cross-host candidates need review. The assessment identifies contextual candidates for Corruption (Force Power), Force Storm (FUCG) and Blind/Force Blind, but the generated matcher deliberately does not promote them to aliases.
- The last-run report records two failed homebrew-page requests; its counters are not a full historical crawl summary.
- Document categories can be multi-domain, source markers can be coarse, and exact game entities require a further reviewed layer.
- Tests validate integrity, preservation, sparse/header-aware spreadsheet reading, URL matching, section navigation and stale-index refusal. They do not establish rules correctness or benchmark retrieval recall.

## Implemented entity/retrieval layer

```bash
python -m tools.swse verify
python -m tools.swse get "Armored Defense"
python -m tools.swse get "Force Storm" --book "Force Unleashed Campaign Guide"
python -m tools.swse list --kind talent --tree "Awareness Talent Tree"
python -m tools.swse coverage "Use the Force"
```

This builds an ignored SQLite database at `artifacts/swse.sqlite3` and three small, versionable products here:

| File | Purpose |
| --- | --- |
| `retrieval_audit.json` | Counts, policy/scope/review labels, extraction limits, input snapshot ID and index size |
| `coverage_review_queue.json` | Top 75 non-bibliographic/media document gaps by referring-document count; local name candidates are not verified aliases/closure |
| `evaluation_report.json` | Golden local evidence/policy/prerequisite results and measured local operation latency; not a universal rules-accuracy score |

The database schema is defined in `tools/swse/store.py` (schema version 1):

- `metadata`: input/code/curation fingerprints, snapshot ID, source policy and extraction audit.
- `documents`: preserved navigation/provenance JSON, keyed by original canonical document URL.
- `entities`: stable local IDs, namespace/name, parent/document IDs, scope, role, review label and full structured JSON. Separate IDs represent source variants, talents and reviewed embedded concepts; five document-context records are internal, not selectable rules.
- `aliases`: many-to-many exact name/document URL mappings with optional required kind. Semantic names are case-insensitive; URL title casing, namespaces, disambiguators and query strings are retained. Contextual aliases do not become global condition/host rewrites.
- `entity_sources`, `chunk_sources`: normalized source facets and span-level declared attribution. Declaration is not primary verification; unmarked additional talents do not inherit the root Core introduction indiscriminately.
- `class_hints`, `actions`: declared category access hints and literal Time fields, not full class availability or action-economy predicates.
- `chunks`: one narrowest-entity-owned, original-coordinate evidence unit, with role/scope/source labels, heading path, review status, table flag, character count and citation. Paragraph/list/table boundaries and tables are retained; source/role changes force boundaries.
- `chunks_fts`: FTS5 over name, headings and derived display text using English Porter/unicode tokenization. Raw uploads are never cleaned in place. Search is literal lexical discovery, not semantic/rules completeness.
- `relationships`: tree membership, category access hints, reviewed interaction evidence and `prerequisite_reference` edges. Prerequisite references retain the condition and AND/OR path; count/OR logic is not flattened into mandatory edges. Targets can remain external/unresolved.
- `workbook`: original sheet/row records plus candidate/reviewed local associations; ambiguous Dark Transfer row 43 remains associated with both variants without merging them.
- `coverage`: explicitly reviewed scope assessments, distinct from document presence.
- `missing_targets`: the full original missing-document registry. Its identity preserves raw normalized title casing/host; the case-insensitive name-lookup index is not a deduplication key.

Full entity/chunk structures include local path, inclusive line range, original article and full-file hashes, URL, revision and retrieval time. Workbook-only summaries cite sheet/row/cell provenance and cannot become fabricated rule paragraphs.

Curation formats are versioned JSON in `curation/`: `overrides.json`, `source_policy.json`, `aliases.json`, `coverage.json`, `prerequisites.json`, and `relationships.json`. Local reviews are locked to article hashes and inclusive spans. Changes require a rebuild, and changed articles require affected reviews to be refreshed rather than bypassed. Inputs and every `tools/swse/*.py` file are fingerprinted; the database opens read-only for query operations.

Tables/paragraphs larger than preferred chunks remain intact. Evidence omissions and policy withholding are reported explicitly. The default excludes marked homebrew/optional at entity and passage levels; unreviewed extraction is allowed and labeled. No independent official-source authentication, full progression/eligibility engine or unrestricted missing-page reconstruction is implied.

See [the tool guide](../docs/AGENT_RETRIEVAL.md) for operations and response statuses, [implementation results](../docs/IMPLEMENTATION_REPORT.md) for measured scope, and [the original assessment](../docs/AI_DATA_ORGANIZATION.md) for the architecture rationale.
