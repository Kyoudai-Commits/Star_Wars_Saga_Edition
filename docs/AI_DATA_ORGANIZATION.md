# Organizing the SWSE repository for AI-agent analysis

**Assessment date:** 2026-10-09. **Scope:** the uploaded local repository, not a live review of the wiki or published books.

## Executive recommendation

Keep the existing uploads intact. Add a **source-preserving, entity-aware retrieval layer**, rather than reorganizing the Markdown into new folders or feeding the whole repository into an agent's context.

The most useful progression is:

1. **A document/workbook atlas** to find titles, embedded sections, source declarations and coverage gaps. A reproducible starter is included in `catalog/`.
2. **A curated entity and rule-variant registry**, with citations back to the original uploads. This is the highest-value next step for trustworthy analysis.
3. **SQLite full-text search plus structured filters and evidence-backed relationships.** Add embeddings only if evaluation shows that lexical retrieval misses useful narrative material.

The key distinction is **document ≠ game entity ≠ rule variant**. One page can contain many talents, two different rules with the same name, a base rule plus clarifications, or optional rules. A better folder tree alone will not solve these problems.

## 1. What is actually in the repository

### Source archive

| Asset | Observed contents | Best role |
| --- | --- | --- |
| `SWSE-Analysis/SWSE_Master_Reference_10-8-2026.xlsx` | Six sheets; 644 summary records across five subject sheets, plus a Links intake sheet | Structured discovery, summaries and initial cross-reference hints |
| `SWSE-Analysis/swse_wiki_export/pages/swse-miraheze-org/` | 809 Markdown pages; 4,833,128 bytes | Original local rule/narrative evidence |
| `SWSE-Analysis/swse_wiki_export/index.jsonl` | 809 records containing title, source/canonical URLs, host, revision, retrieval time, path, article hash, character count and categories | Existing authoritative manifest for the *export's identity and provenance*, not for rules authority |
| `SWSE-Analysis/swse_wiki_export/report.json` | Last export-run status, including two HTTP 403 failures | Import diagnostics; not a declaration of complete rules coverage |

All indexed Markdown files exist, none are unindexed, and all 809 article hashes, character counts and front-matter records agree with the manifest. There are no duplicate document titles, canonical URLs, indexed paths or declared article hashes in this snapshot.

**Important hash detail:** `content_sha256` describes the stripped article after the generated `> Source:` line. It excludes front matter and the generated title/source wrapper, but includes original scrape noise. Comparing it against the entire file would incorrectly report every page as corrupt. The new catalog also records a separate full-file hash.

The pages were retrieved between `2026-10-09T09:36:19Z` and `2026-10-09T09:37:43Z`; all are from `swse.miraheze.org`. These are wiki transcriptions with book/source declarations, **not independently verified copies of the published books**. No acquisition script or `targets.txt` referenced by the last-run report is present in the upload.

### Subject coverage at document level

| Primary document/category hint | Pages |
| --- | ---: |
| Feats | 352 |
| Talent trees | 167 |
| Species | 133 |
| Force powers | 88 |
| Prestige classes | 30 |
| Heroic classes | 5 |
| General/aggregate references | 30 |
| Category pages | 4 |
| **Total** | **809** |

These are navigation hints, **not counts of distinct game mechanics**. For example, Corruption also has a `Destinies` category; the catalog retains both entity-type hints. Talent-tree pages contain individual talents that do not have their own local files.

The corpus is particularly useful for character-option discovery. Its general references cover topics such as character creation, abilities, combat, skills, equipment, droids, the Force, organizations, gamemastering and starship modifications. The presence of an overview does not establish that its linked detailed subrules were exported.

### Workbook structure

| Sheet | Actual data records | Interpretation / caveat |
| --- | ---: | --- |
| Heroic Classes | 7 | Five entries before a Homebrew marker; Technician and Force Prodigy after it |
| Prestige Classes | 28 | Wiki export additionally contains Imperial Knight and Shaper |
| Feats | 353 | Staggering Attack occurs twice, with different source-specific rules |
| Force Powers | 89 | 65 general-power rows and 24 form-power rows; a second header occurs at row 67 |
| Talents | 167 | **Talent trees**, not individual talents |
| Links | 818 literal URL cells | Intake list, not an entity table; also contains seven section markers |

Do not use spreadsheet dimensions or XML row counts as entity counts. Several sheets contain styled but empty rows extending to approximately row 1,000. Force Powers merges columns A/B in its general-power section, leaving no independent B header there; B becomes **FORM** in the section beginning at row 67. No formulas are present in the uploaded workbook.

The generated workbook map preserves original cell references and text, rather than trying to interpret comma-separated lists, prerequisite expressions or abbreviated formulas automatically.

## 2. The reliability issues an agent must handle

### A. Link coverage is not the same as rule coverage

Scanning inline HTTP Markdown links in the **article text only**, excluding generated source-wrapper links, found:

- **27,677** link occurrences targeting the two SWSE wiki hosts.
- **4,401** occurrences with an exact local document match, including source-URL aliases documented by the manifest: **15.9%**.
- **23,276** occurrences without a local document, targeting **2,622** distinct normalized host/title pairs.

**This does not mean 84.1% of the game's rules are missing.** Repeated terminology, book metadata, lore links and text embedded in other articles all affect this measurement. It is a navigation/closure audit, not a semantic completeness score.

Frequently linked targets without standalone local pages include:

| Target | Occurrences | Referencing documents |
| --- | ---: | ---: |
| Use the Force | 508 | 186 |
| Force Point | 357 | 194 |
| Standard Action | 355 | 185 |
| Reflex Defense | 341 | 210 |
| Swift Action | 338 | 177 |
| Will Defense | 271 | 148 |
| Condition Track | 213 | 105 |
| Base Attack Bonus | 196 | 99 |

Some concepts have useful embedded coverage: `the-force.md` has Force Points and Using Force Points sections, and `abilities.md` covers ability modifiers and checks. Others are primarily linked from overview pages: `skills.md`, for example, has a skill table and general skill-check rules, not the complete detailed Use the Force skill entry.

**Recommendation:** maintain three separate coverage states: `local_document`, `embedded_or_partial_evidence`, and `no_sufficient_local_evidence`. The starter catalog establishes only the first distinction. Check actual passages before assigning either of the latter states. Prioritize detailed skills, action economy, defenses, condition/damage rules and build prerequisites ahead of indiscriminately collecting all 2,622 targets.

### B. Title collisions need rule-level identities

These are meaningful distinctions in the local text, not necessarily bad duplicates to delete:

| Local document | Distinct contents | Mapping implication |
| --- | --- | --- |
| [Staggering Attack](../SWSE-Analysis/swse_wiki_export/pages/swse-miraheze-org/staggering-attack.md) | Scum and Villainy declaration at line 18; Galaxy at War at line 26. Workbook rows 138 and 270 point to the same URL but describe these different rules. | Keep two source-specific feat records, not one merged benefit/prerequisite set. |
| [Force Storm](../SWSE-Analysis/swse_wiki_export/pages/swse-miraheze-org/force-storm.md) | Force Unleashed Campaign Guide declaration at line 18; Jedi Academy Training Manual at line 39. | Select a source-specific power variant, not just the page. |
| [Corruption](../SWSE-Analysis/swse_wiki_export/pages/swse-miraheze-org/corruption.md) | Destiny material begins with references at line 18; Force-power material with a reference at line 28. | Separate different entity types sharing a name. |
| [Armor Specialist Talent Tree](../SWSE-Analysis/swse_wiki_export/pages/swse-miraheze-org/armor-specialist-talent-tree.md) | Individual talents are H3 sections within one tree file. | Give talents identities and citations within their parent tree. |

A rule identifier should include kind, name and source/variant where needed. For talents, parent-tree context is also useful. Identity cannot safely be inferred from filename or title alone.

### C. URL aliases must be evidence-based and sometimes context-specific

The export manifest records three useful redirects: Armor, Vehicles and Weapons source URLs resolve to `Category:` canonical pages. Preserve both URLs. Do not identify a category by its human display title (`Category : Weapons`) or a guessed slug alone.

Workbook link matching currently gives:

| Sheet | Local document matches | Same-title cross-host candidates | Unresolved / unrelated |
| --- | ---: | ---: | ---: |
| Heroic Classes | 5 | 0 | 2 |
| Prestige Classes | 28 | 0 | 0 |
| Feats | 353 | 0 | 0 |
| Force Powers | 0 | 86 | 3 |
| Talents | 167 | 0 | 0 |
| Links | 815 | 0 | 3 |

All 89 Force Powers links use Fandom, while the local export is Miraheze. The 86 same-title matches are **candidates**, not proof that the two hosts contain identical versions.

The remaining three power rows merit contextual alias review:

- `Force Powers!F28`, `Corruption_(Force_Power)`: candidate is the **Force-power portion** of `corruption.md`, not its Destiny portion.
- `Force Powers!F31`, `Force_Storm_(FUCG)`: candidate is the **FUCG portion** of `force-storm.md`.
- `Force Powers!F50`, `Blind`: candidate is `force-blind.md`, whose local text explains the rename. **Do not globally alias every Blind reference to Force Blind**; the page itself distinguishes another similarly named concept.

The two absent homebrew-class pages are the same URLs listed as HTTP 403 failures in the last-run report. Their absence does not license reconstructing full classes from spreadsheet summaries. The Links sheet also contains `http://www.w3.org/1999/xhtml` at A698, an unrelated namespace URL that should not become a game entity or crawler target.

Normalize percent encoding and underscores/spaces for lookup, but retain host, namespace, title casing and disambiguators. Strip fragments only for document matching; verify section targets separately. Fuzzy matches must remain suggestions until reviewed.

### D. Source/status distinctions exist inside pages

104 pages have more than one reference-book marker. Some have clarifications from Web Enhancements/Jedi Counseling; some include optional or variant rules. For instance, [Move Object](../SWSE-Analysis/swse_wiki_export/pages/swse-miraheze-org/move-object.md) includes a specifically optional size-linked damage interpretation, and [The Force](../SWSE-Analysis/swse_wiki_export/pages/swse-miraheze-org/the-force.md) includes optional daily Force Points.

A page's category list is too coarse to assign source authority or adoption to every paragraph. Preserve:

- Declared publication/source, separately from actual evidence location and verification status.
- Base rule, clarification/FAQ, errata **where explicitly evidenced**, optional/variant rule, homebrew, and agent inference.
- Campaign adoption policy, independently of the fact that a rule is printed in a source.

**Default agent policy:** exclude explicitly labeled homebrew and do not activate optional variants unless requested. Unknown status remains unknown. Use applicable verified errata when available, but do not assume a newer book replaces a same-named rule, or that a wiki category proves official provenance. Campaign overrides should be explicit and distinguishable from published-rule analysis.

### E. Scrape structure affects chunking

- 802 pages contain `Loading comments...`.
- 23 contain the flattened label `Jedi CounselingJedi Counseling`.
- Multi-source tabs can become text such as `Scum and VillainyGalaxy at War`, without real heading boundaries.
- 279 pages have Markdown tables, including DC/effect tables and multi-row headers.
- There are 3,073 Markdown headings, with repeated headings in several large documents.
- Median article length is **2,715 characters**; 26 articles exceed 20,000 and 10 exceed 50,000. Gamemastering reaches **187,919**.

Keep raw text unchanged. Remove known UI boilerplate only in derived search text, and preserve a mapping back to original line spans. Do not blindly delete repeated words or deduplicate every identical heading. Split on **entity/source boundaries as well as headings**: heading-only chunking would miss the Staggering Attack and Force Storm distinctions.

## 3. Recommended information model

### Layer 0 — immutable source archive

Keep the existing `SWSE-Analysis/` paths, index and export diagnostics. Future imports should retain provenance and change history. Do not rename 809 files merely to enforce a subject hierarchy; categories overlap, and path churn would invalidate citations.

### Layer 1 — document and workbook atlas

Included now:

- `catalog/wiki_documents.jsonl`: document identities, provenance, categories/type hints, hierarchical line spans, source-marker locations and local document-reference edges.
- `catalog/workbook_records.jsonl`: 644 cell-preserving summary records with sheet/row/header coordinates, explicit-homebrew scope and link-match status.
- `catalog/missing_wiki_targets.jsonl`: the 2,622 unresolved document targets, ranked by number of referencing documents, with sample source paths.
- `catalog/audit.json`: input fingerprints, integrity results, workbook structure, coverage and import diagnostics.

These are navigation aids, **not a curated rules database**. The agent should query them selectively; loading all generated JSON into a prompt would recreate the context-size problem.

### Layer 2 — reviewed game entities and variants

Create separate records for feats, individual talents, talent trees, classes, species traits, powers, skills, combat concepts, equipment and other analysis targets. Keep narrative/lore records distinct from mechanical entities.

Suggested record fields:

| Field | Purpose |
| --- | --- |
| `entity_id`, `kind`, `name`, `variant_id` | Stable identity including source or parent context when needed |
| `aliases` | Reviewed names/URLs with context and evidence, not global fuzzy substitutions |
| `source_document_id`, revision/hash, file/line spans | Exact support and reproducibility |
| `declared_source`, `verification_status` | Distinguish wiki claims from primary-source verification |
| `rule_role`, `campaign_adoption` | Base/clarification/optional/homebrew and whether enabled |
| `rules_text`, `summary` | Retain full conditions and exceptions alongside a retrieval summary |
| `prerequisites_raw`, `prerequisites_ast` | Original wording plus reviewed AND/OR/count/threshold constraints |
| `mechanics` | Optional typed action, target, range, duration, resource cost, bonus type, stacking and formulas |
| `relations` | Evidence-backed membership, access, prerequisites and interactions |
| `review_status` | Extracted/unreviewed/reviewed/ambiguous; incomplete facts must not become false |

Treat prerequisite expressions as logic, not lists. Elite Trooper's sheet entry, for example, contains an OR choice between Point-Blank Shot and Flurry, plus a talent-selection requirement. Bounty Hunter requires a count of talents from a tree. Multiclass availability, trained-only requirements, bonus types, rounding and special exceptions must remain explicit.

Represent relationships as typed edges: `belongs_to_tree`, `available_to_class`, `requires_feat`, `requires_trained_skill`, `requires_any_of`, `clarifies`, `does_not_stack_with`, `variant_of`. A Markdown hyperlink by itself only establishes **references**, not any of those stronger meanings.

### Layer 3 — retrieval and analysis

Start with a local SQLite database containing:

- `documents`, `source_spans`, `entities`, `variants`, `aliases`, `relationships`, `coverage_gaps` and review/adoption status.
- An FTS5 index over derived rule chunks and narrative sections.
- Structured indexes for kind, source book, class/tree access, action type, prerequisites and campaign policy.

Keep the database and later vector artifacts out of Git; rebuild them from versioned sources/mappings. SQLite is a practical starting point for this repository's size; a dedicated vector or graph service is not justified yet.

**Chunking strategy:** retain small single-rule pages as complete rule units; split tree pages by individual talent with parent/access context; split large narrative pages hierarchically; split mixed-source pages by reviewed entity/variant boundaries. Preserve entire tables, their header context, and adjacent qualifications. Start around 400–1,000 model tokens per chunk where appropriate, measuring with the eventual tokenizer rather than a fixed character estimate.

Long inline URLs are useful provenance but expensive prompt material. A derived retrieval view can show link labels and compact entity IDs, with URLs in a citation map. Never replace the raw export or lose unresolved-link warnings in the process.

**Query routing:**

1. Exact entity/alias lookup, with source/variant disambiguation.
2. Structured filtering for enumeration and build questions; do not approximate exhaustive answers with top-k search.
3. Lexical retrieval for rules wording, expanding to parent context and relevant clarification/interaction edges.
4. Optional semantic retrieval for narrative intent or broad conceptual questions.
5. Deterministic constraint checks/calculations over reviewed mechanics, with an agent explaining assumptions and evidence.

A graph-expanded bundle should be bounded to relevant relations, not every linked term. The answer should separate supported rules, calculation assumptions, optional variants and unresolved evidence. Incomplete prerequisites should produce an **unknown/needs evidence** outcome, not an invented answer or an automatic failure.

## 4. Useful agent-facing views

Views should be regenerated from the same source IDs, not copied into competing rulebooks:

- **Character building:** species → class → accessible trees → individual talents/feats → prerequisites → progression.
- **Force use:** powers and source variants → descriptors → action/target/DC tables → resources → clarifications/optional changes.
- **Combat:** action economy, defenses, conditions, damage and stacking interactions.
- **Equipment/starships/droids:** actual entities and modifications, with stat tables and compatibility rules.
- **GM/campaign:** narrative guidance, organizations, skill challenges, eras and encounter construction, separated from executable rules.
- **Source-book view:** declared sources and review/adoption flags for campaign restrictions.

These can initially be JSON queries or Markdown indexes. A tool API/MCP service can come later, exposing operations such as `find_entity`, `get_rule`, `list_options`, `check_prerequisites` and `get_coverage`, with citations in every result.

## 5. Prioritized implementation roadmap

| Priority | Work | Completion criterion |
| --- | --- | --- |
| **Now — completed starter** | Repository guide, agent instructions, reproducible atlas and audit | Original uploads unchanged; hashes verified; targeted lookup and regression tests available |
| **1 — highest value** | Review collisions, embedded talents, contextual aliases and campaign source policy | No same-name/source conflation; explicit homebrew and optional-rule boundaries |
| **2 — coverage** | Check embedded evidence and fill high-value detailed-rule gaps using a permitted acquisition process | Core analysis dependencies have cited local evidence or explicit unknown status |
| **3 — search/constraints** | Build SQLite FTS5/facets and a reviewed prerequisite/mechanics subset | Exact lookups, exhaustive filtered listings and deterministic checks work reliably |
| **4 — evaluate/extend** | Add semantic retrieval or an agent tool service only if useful | Measured improvement without losing exactness, citation fidelity or source distinctions |

Do not begin with a monolithic merged document, a vector-only index, broad automatic deduplication, or a large graph-database deployment. Check source redistribution/licensing terms before publishing new consolidated outputs; this assessment does not establish those rights.

## 6. Evaluation before relying on automated rules analysis

Build a small, reviewed test set with expected evidence and expected abstentions:

| Example question | Required behavior |
| --- | --- |
| Can Rapid Strike be combined with Whirlwind Attack? | Retrieve the relevant Q&A as well as the base feat text. |
| What does Staggering Attack require/do? | Disambiguate Scum and Villainy vs Galaxy at War; never combine them. |
| Which Force Storm is being used? | Select the correct source-specific power block. |
| How does Move Object damage relate to object size? | Distinguish base/clarification text from the explicitly optional interpretation. |
| What are the available heroic classes without homebrew? | Do not include Technician or Force Prodigy from the marked workbook section. |
| Is a character eligible for Bounty Hunter or Elite Trooper? | Preserve talent counts, AND/OR constraints and character-state assumptions. |
| What are the complete detailed uses of Use the Force? | Report the current coverage gap rather than invent missing skill rules. |

Measure evidence retrieval, citation correctness, source/variant separation, prerequisite accuracy, unsupported-claim/abstention behavior, token cost and latency. Enumeration tasks need recall over the complete selected dataset, not merely plausible top results. The included tests validate **catalog integrity and navigation**, not game-rule correctness or retrieval quality.

## 7. Immediate usage

From the repository root:

```bash
# Rebuild the maps and verify source integrity; no downloads or source edits.
python tools/build_catalog.py

# Find a talent embedded in a tree, or a same-named rule with multiple summaries.
python tools/build_catalog.py --find "Armored Defense"
python tools/build_catalog.py --find "Staggering Attack"

# For body text not found by title/heading lookup, search the original archive.
rg -n --glob '*.md' 'Condition Track' SWSE-Analysis/swse_wiki_export/pages

# Run standard-library-only regression tests.
python -m unittest discover -s tests -v
```

`--find` searches titles/headings and workbook labels, **not full text or semantic meaning**. It refuses a stale catalog if source inputs or Markdown files have changed. See [catalog documentation](../catalog/README.md) for schema details and limitations, and [AGENTS.md](../AGENTS.md) for the suggested agent workflow.
