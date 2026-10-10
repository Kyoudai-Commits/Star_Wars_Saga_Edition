# Autonomous execution plan — SWSE agent retrieval

This plan uses only the uploaded repository and local, dependency-free tooling. It does not require accounts, API keys, paid services, source-policy decisions or interactive approval. Existing uploads will remain unchanged.

## Operating defaults

- All uploaded text remains a **local wiki transcription or workbook summary**, not independently verified published rules.
- Keep source-specific variants and entity types separate. Never repair ambiguities by silently merging names.
- Exclude explicitly labeled homebrew and optional/variant-rule passages by default. Retain them in the index for explicit opt-in.
- Preserve incomplete knowledge: missing evidence or character facts produce **unknown**, not invented rules or automatic eligibility.
- Keep generated SQLite/text-search artifacts under ignored `artifacts/`; version only tools, curation, small reports, tests and documentation.
- Do not fetch additional wiki pages in this environment: the allowed outbound hosts do not include either SWSE wiki. Do not reconstruct missing rules from model memory or import unlicensed third-party collections.

## Execution sequence

1. **Source-safe specification and curation**
   - Define versioned source-policy and curation formats.
   - Lock local reviews to article hashes and original line spans.
   - Separate Staggering Attack, Force Storm, Corruption and other mixed-type pages.
   - Review contextual aliases and selected embedded concepts.
   - Detect homebrew inside talent-tree pages, not just spreadsheet classes.
2. **Granular local index**
   - Build entities for every page and individual talents inside all talent trees.
   - Create non-overlapping, source-cited retrieval units; retain tables and qualification context.
   - Index cleaned display text without editing original text.
   - Build SQLite FTS5, exact aliases, facets, evidence-backed relationships and coverage metadata.
   - Make index replacement atomic and reject stale or inconsistent inputs.
3. **Agent-facing operations**
   - Exact lookup with ambiguity responses, lexical search, exhaustive/paginated enumeration, bounded evidence bundles and coverage queries.
   - Explicit kind/source/tree/action filters and opt-in switches for homebrew/optional passages.
   - JSON CLI and a local JSON-lines request adapter; no long-running server or browser service required.
4. **Deterministic constraint subset**
   - Encode source-reviewed prerequisite expressions with AND/OR, thresholds and talent counts.
   - Check explicit character facts using three-valued logic.
   - Return per-condition explanations and citations; do not claim a full character validator or universal rules engine.
5. **Evaluation and hardening**
   - Golden local evidence cases for collisions, clarification retrieval, optional-rule exclusion, homebrew exclusion and missing-rule abstention.
   - Regression tests for source hashes, spans, source-role boundaries, table integrity, aliases, enumeration, malformed requests, staleness and constraints.
   - Measure actual corpus coverage, retrieval success and local query latency.
   - Document completed work, remaining coverage gaps and exact rebuild/use commands.

## Completion criteria

- All 809 source article hashes continue to validate; no original upload changes.
- Every extracted entity/chunk has reproducible source coordinates and an explicit review/provenance status.
- Same-name variants require disambiguation rather than producing blended evidence.
- Known homebrew and optional sections do not leak through default retrieval or parent-document bundles.
- Enumeration is distinguishable from top-k search and reports totals/pagination.
- Unsupported detailed rules and unencoded/unknown prerequisite facts have explicit unknown outcomes.
- Build and query tools work offline with Python 3.10+ and SQLite FTS5.
- Tests and golden evidence evaluation run from a single documented command sequence.

## Stop conditions

Continue autonomously through the local index, tools, curation subset, tests and documentation. Stop short of claiming primary-source verification, complete game-rule coverage, exhaustive semantic interpretation, unrestricted source acquisition or a validated campaign-specific character builder. Record those limits and a prioritized follow-up queue instead of asking the user to resolve them now.

## Executed status — 2026-10-09

All five local stages are implemented and validated. The final `python -m tools.swse verify` run passed **53 regression tests and 33/33 golden cases**, with SQLite integrity `ok` and zero foreign-key violations. The index contains all 809 original documents, 1,142 individual talents, 44 prerequisite expressions and source-cited/policy-aware query operations. The 75-topic coverage queue records follow-up leads without claiming semantic closure.

See [implementation results](IMPLEMENTATION_REPORT.md) for exact counts, timing, remaining scope and commands, and [agent retrieval](AGENT_RETRIEVAL.md) for the usable interface. A CI template is added under `docs/ci/verify.yml`; it is not active because the repository app lacks workflow-write permission. Local verification is complete; remote CI is not claimed. Local execution required no source acquisition, original-source change or deployment; Git delivery is a separate step. The stated stop conditions remain in force.
