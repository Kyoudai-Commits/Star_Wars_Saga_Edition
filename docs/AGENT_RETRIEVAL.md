# Using the local SWSE agent tools

The repository now has an offline SQLite/FTS5 retrieval layer and a source-reviewed prerequisite subset. **It retrieves local evidence; it does not independently authenticate published rules or implement the whole game.**

Python 3.10+ with SQLite FTS5/JSON support is required. No third-party Python packages, API keys, embeddings, web server or remote database are needed.

## Build and verify

From the repository root:

```bash
# Complete build, regression suite, golden evidence evaluation and integrity check.
python -m tools.swse verify

# Individual operations when iterating.
python -m tools.swse build
python -m tools.swse doctor
python -m tools.swse evaluate
python -m unittest discover -s tests -v
```

`build` first verifies/regenerates the original document/workbook catalog, validates curation hashes and line spans, then atomically replaces `artifacts/swse.sqlite3`. Source/curation/schema/integrity validation failures leave the previous database intact. Auxiliary catalog reports are separately replaced; they are not a multi-file filesystem transaction. The database is intentionally ignored by Git and can always be rebuilt. Do not commit SQLite or vector artifacts.

Queries open the database **read-only**. Each operation checks original source, curation and implementation fingerprints. An index from a different snapshot refuses to serve stale citations; rebuild it rather than bypassing the check. Updating original rules can also invalidate curated line spans/hashes, requiring an explicit local re-review before rebuilding.

Global options `--repo PATH` and `--database PATH` precede the subcommand. Custom database destinations must use a SQLite extension, cannot be inside protected source/code/curation/Git directories, and cannot overwrite unrelated files or databases.

## Exact lookup and source separation

```bash
python -m tools.swse resolve "Armored Defense"
python -m tools.swse get "Armored Defense"
python -m tools.swse bundle "Expert Tracker" --kind talent

# Returns two choices, not a blended rule.
python -m tools.swse get "Staggering Attack"

# Selects one source-specific rule.
python -m tools.swse get "Staggering Attack" --book "Scum and Villainy"
python -m tools.swse get "Force Storm" --book "Jedi Academy Training Manual"

# Same name, different entity types.
python -m tools.swse get "Corruption" --kind force_power
python -m tools.swse get "Intercept" --kind starship_maneuver
```

`get` returns the selected entity, full allowed evidence passages, citations, workbook associations and outgoing relationships. `bundle` also adds the parent's **own** context where it fits; it does not pull in sibling source variants or all sibling talents. `--max-chars` bounds emitted evidence text (default 12,000, maximum 200,000), not all JSON metadata or model tokens.

Response statuses are deliberate:

- `ok`: local evidence selected; read its role, source and review labels.
- `ambiguous`: choose an entity ID, kind, book or variant; the tool will not select by publication date or merge requirements.
- `needs_context`: a contextual alias requires a kind. `Blind` requires `--kind force_power`; it is not a global condition alias.
- `cross_host_candidate`: an unreviewed Fandom URL has a same-name local candidate, **not verified URL equivalence**. Query the local entity explicitly if appropriate.
- `excluded_by_policy`: an entity is known but not enabled by the current scope/kind/source filters.
- `summary_only_insufficient_rules`: only a workbook summary exists, as for Technician and Force Prodigy. It is not a complete class entry.
- `not_found`: no exact eligible alias/entity match, not proof that all body-text coverage is absent.

Semantic name lookup is case-insensitive. URL identities retain title casing, host, namespace, disambiguators and query strings; percent encoding and underscores/spaces are normalized. Unrecorded `oldid`/`diff` URLs are not rewritten to the current local revision; use the canonical URL and inspect the returned revision/snapshot. Known Armor/Weapons/Vehicles redirects are retained from the original manifest. Tree abbreviations require the `talent_tree` namespace so, for example, a Bounty Hunter tree alias does not make the Bounty Hunter class lookup ambiguous.

## Search versus enumeration

```bash
python -m tools.swse search "Rapid Strike Whirlwind Attack" --limit 5
python -m tools.swse search "Move Object size damage" --kind force_power

# Complete local filtered enumeration, with totals and pagination.
python -m tools.swse list --kind talent --tree "Awareness Talent Tree" --limit 100
python -m tools.swse list --kind feat --book "Core Rulebook" --limit 100 --offset 0
python -m tools.swse list --kind force_power --action "Swift Action" --limit 100
python -m tools.swse list --kind talent_tree --class Scout --limit 100
python -m tools.swse list --kind prestige_class --reviewed-prerequisites --limit 100
```

Search uses literal terms, English stemming and BM25 over entity names, headings and derived text. It prefers all-term matches, then explicitly labels an any-term fallback if no eligible all-term passages match. User text is never executed as SQL/FTS syntax. Search results are **evidence pointers/excerpts, not rule answers**. An excerpt may be incomplete; fetch its `chunk_id` using `chunk`, or retrieve the entity bundle.

Enumeration returns `total`, ordered `items`, `next_offset` and a page-completeness flag. Follow `next_offset` until null for exhaustive results under the chosen local filters. Do not substitute top-k search for option listings.

Supported kinds are available in `doctor` → `audit.entities_by_kind`. They currently include feats, talents, talent trees, powers, classes, species, reviewed embedded concepts, a reviewed starship maneuver, references and category pages. Internal document-context records are not ordinary selectable rules. **Equipment items, species traits, detailed skills and every class feature have not been normalized into individual entities.** Their uploaded text can still be searched; an unsupported kind is rejected instead of returning a misleading empty enumeration.

`--class` uses declared category access hints, not unconditional availability or complete character eligibility. `--action` uses literal declared Time fields, not inferred action economy. Book/variant facets select entity sources for lookup; relevant clarification passages can declare other sources. Campaign-wide source restrictions belong in `curation/source_policy.json`, not a one-off lookup facet.

## Policy and passage roles

Default policy:

- Explicit homebrew **off**.
- Explicit optional/variant-rule passages **off**.
- Unreviewed structural extraction searchable, with review labels.
- No campaign-specific book restrictions presumed.

```bash
python -m tools.swse get "Move Object" --include-optional
python -m tools.swse get "Wilderness Medic" --kind talent --include-homebrew
python -m tools.swse get "Technician" --include-homebrew
python -m tools.swse list --kind talent --reviewed-only
```

Roles include `base_rule`, `clarification`, `optional_rule`, `gm_advice` and `unclassified`. Scope includes `unmarked` versus explicit `homebrew`. Unmarked is **not independently verified official**. Boundary reviews are local-text reviews, not human approvals or primary-publication authentication.

The default suppression applies to passages as well as entities, including optional rules/homebrew inside otherwise unmarked parent documents. Locked annotations separate Move Object's interleaved base Special text, Q&A, optional damage interpretation and GM advice. A newly discovered optional paragraph can require additional review; automatic detection is conservative, not a guarantee of perfect whole-corpus semantics.

Tables and long paragraphs are stored intact, even when they exceed the preferred 3,200-character chunk size. A retrieval budget that cannot fit a whole chunk reports its omission or `budget_too_small`, rather than cutting a table and claiming full evidence. `complete_for_allowed_passages`, `omitted_chunks` and `withheld_by_policy` make evidence scope explicit. Bundles separately report `omitted_context_chunks`, `withheld_context_by_policy` and entity/context completeness; a full entity excerpt does not silently imply complete requested parent context. Parent/entity-wide source ranges may contain excluded sections; use **returned passage citations** for conclusions under the selected policy.

## Coverage and the follow-up queue

```bash
python -m tools.swse coverage "Use the Force"
python -m tools.swse coverage "Force Point"
python -m tools.swse coverage "Reflex Defense"
```

Reviewed coverage can be `embedded_evidence` or `insufficient_local_evidence` for a stated scope. Unreviewed absent standalone pages are reported as `document_gap_semantic_coverage_unreviewed`; this is not a declaration that every explanation of the concept is absent. A local entity likewise does not prove that every related rule, exception or erratum is present.

`catalog/coverage_review_queue.json` prioritizes 75 non-bibliographic/media gaps by referring-document count, with local-name candidates and existing scope reviews. The full original gap registry remains in `catalog/missing_wiki_targets.jsonl`. Name candidates are not confirmed URL aliases or semantic closure. Bibliographic/media targets excluded from the short queue remain in the complete registry.

Detailed Use the Force uses, action economy, defense/condition/damage rules and progression dependencies are high-value follow-up subjects. No additional rules were downloaded or invented in this implementation.

## Reviewed prerequisite checks

```bash
python -m tools.swse check "Bounty Hunter" --character examples/bounty-hunter-ready.json
python -m tools.swse check "Elite Trooper" --character examples/elite-trooper-ready.json
python -m tools.swse check "Bounty Hunter" --character examples/partial-character.json
```

There are 44 reviewed local prerequisite expressions, including all 30 exported prestige-class prerequisite blocks. Remaining checks return `unknown`/`unencoded_prerequisites`, even if no prerequisite line was extracted. Armor Proficiency (Light) is an explicitly reviewed absence case: its local full entry states no prerequisites; the empty expression covers only locally stated prerequisites, not acquisition/progression permission.

Results are `met`, `not_met` or `unknown`, with per-condition explanations, exact citations and scope. **Met means the encoded prerequisite expression is satisfied by the supplied facts. It does not mean the entire character is legal or the option can certainly be acquired.** No level/BAB progression, feat acquisition, class/tree access, bonus stacking, build optimization or GM permissions are inferred.

Character JSON supports:

| Field | Meaning |
| --- | --- |
| `level`, `base_attack_bonus` | Explicit nonnegative integers; BAB is not inferred from level |
| `force_talent_count`, `force_technique_count` | Explicit externally established counts, not inferred from coarse category membership |
| `feats`, `trained_skills`, `force_powers`, `droid_systems` | Lists using exact canonical feature names; unknown source/acquisition legality is not repaired |
| `talents` | Local talent IDs, exact names, or `{ "name": "...", "tree": "... Talent Tree" }` objects; ambiguous/unresolved/forged tree assignments remain unknown |
| `species` | Explicit species name for reviewed equality requirements |
| `facts` | Explicit boolean special conditions using fact names shown in the prerequisite AST/explanation, e.g. `jedi_membership` |
| `inventories_complete` | Optional per-inventory booleans; supplied lists are complete unless explicitly false; missing inventories are unknown |

AND/OR/count logic is preserved. Duplicate talent identities do not count twice. Known failures dominate AND; known successes dominate OR; other unresolved conditions remain unknown. Source expressions for Elite Trooper and Martial Arts Master retain requirements omitted by abbreviated workbook summaries. Special membership/construction/weapon-focus predicates remain explicit facts rather than guessed from story text.

Relationships derived from prerequisites are labeled `prerequisite_reference`, with the original condition and logic path. Do not flatten an OR alternative or a count over multiple trees into separate mandatory requirements.

## Machine interface

```bash
printf '%s\n' \
  '{"id":1,"method":"search","params":{"query":"Rapid Strike Whirlwind Attack","limit":3}}' \
  '{"id":2,"method":"get","params":{"name":"Armored Defense"}}' \
  | python -m tools.swse serve
```

The adapter reads one JSON request per line and returns one JSON response per line until EOF. It opens no port and performs no network calls. Available operations are `resolve`, `get`, `bundle`, `chunk`, `search`, `list`, `coverage`, `check` and `doctor`. `build`/`verify` are deliberately not remotely dispatchable methods. Malformed, oversized, unknown-parameter or stale-index requests produce structured errors; valid subsequent requests continue.

Tool argument schemas are in `tools/swse/agent_tools.json`. Python agents can also use `Repository` and `dispatch` directly. This is a repository-specific JSON-lines transport, **not a claim of MCP protocol support**; a thin protocol-specific wrapper can be added later.

## Maintenance and CI

Versioned curation is under `curation/`; derived catalog files must be regenerated, not hand-edited. Source/implementation changes require rebuilding. Keep reviews linked to article hashes and inclusive original-file line spans; reviewed boundaries cannot cut a table or overlap sibling variants.

The CI template in `docs/ci/verify.yml` runs `verify` on Python 3.10 and 3.13 with read-only permissions and commit-pinned actions. It is **not active**: the repository app lacks permission to create/update `.github/workflows/` files, so the configuration is preserved as documentation. A maintainer with workflow-write permission can install it at `.github/workflows/verify.yml`. Local verification uses the sandbox's Python 3.11; no remote CI pass is claimed. Database/text-search artifacts are not published by the template.

See [the execution plan](EXECUTION_PLAN.md), [implementation results](IMPLEMENTATION_REPORT.md), and [original assessment](AI_DATA_ORGANIZATION.md) for scope and follow-up priorities.
