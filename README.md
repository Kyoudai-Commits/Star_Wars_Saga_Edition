# Star Wars Saga Edition — local agent reference

An uploaded SWSE reference archive with **offline, source-cited retrieval tools**: exact entity lookup, SQLite full-text search, filtered enumeration, evidence bundles, coverage reporting and a reviewed prerequisite subset. The Excel workbook and all 809 original Markdown exports remain unchanged under `SWSE-Analysis/`.

## Start here

- **[Implementation report](docs/IMPLEMENTATION_REPORT.md)** — what was executed, measured results and remaining limits.
- **[Agent tool guide](docs/AGENT_RETRIEVAL.md)** — CLI, JSON-lines interface, policy, citations and prerequisite inputs.
- **[Execution plan](docs/EXECUTION_PLAN.md)** — autonomous stages and stopping criteria.
- **[Original assessment](docs/AI_DATA_ORGANIZATION.md)** — repository findings and architecture rationale.
- **[Agent instructions](AGENTS.md)** and **[catalog schema](catalog/README.md)**.

## Quick start

Python **3.10+**, SQLite FTS5/JSON support, standard library only. From the repository root:

```bash
# Rebuild, test, evaluate and verify integrity in one command.
python -m tools.swse verify

python -m tools.swse get "Armored Defense"
python -m tools.swse search "Rapid Strike Whirlwind Attack" --limit 5
python -m tools.swse list --kind talent --tree "Awareness Talent Tree" --limit 100
python -m tools.swse get "Staggering Attack" --book "Scum and Villainy"
python -m tools.swse coverage "Use the Force"
python -m tools.swse check "Elite Trooper" --character examples/elite-trooper-ready.json
```

All ordinary query outputs are JSON. Default policy excludes explicitly marked homebrew and optional rules, including those embedded in broader pages. Ambiguous identities return choices, not blended rules. Missing evidence and unencoded prerequisites remain unknown.

For local agent integrations:

```bash
printf '%s\n' '{"id":1,"method":"get","params":{"name":"Armored Defense"}}' \
  | python -m tools.swse serve
```

This is a read-only JSON-lines adapter, not a network service or an MCP implementation. Schemas: [`tools/swse/agent_tools.json`](tools/swse/agent_tools.json).

## Repository map

```text
SWSE-Analysis/                         Original uploads; preserved
  SWSE_Master_Reference_10-8-2026.xlsx  Six sheets, 644 summary/intake records
  swse_wiki_export/                    809-page manifest, report and raw Markdown
curation/                             Hash-locked policy, identities, aliases,
                                      coverage, prerequisites and relationships
tools/build_catalog.py                Original document/workbook navigation builder
tools/swse/                           Extraction, SQLite/FTS5, read-only API and CLI
artifacts/swse.sqlite3                Rebuildable search index; ignored by Git
catalog/                              Rebuildable navigation maps and small reports
  retrieval_audit.json                 Entity/chunk/source-policy measurements
  coverage_review_queue.json           Prioritized gaps, candidates and scope reviews
  evaluation_report.json               Golden local-evidence evaluation results
evaluation/cases.json                  Local retrieval/policy/prerequisite fixtures
examples/                             Synthetic character-fact JSON examples
tests/                                Navigation, retrieval, constraints and safety tests
docs/                                 Plan, assessment, tool guide and results
docs/ci/verify.yml                    Pinned-action CI template; not active
AGENTS.md                             Evidence and maintenance instructions
```

The original navigation-only interface remains available:

```bash
python tools/build_catalog.py
python tools/build_catalog.py --find "Force Storm"
```

Use `rg` or the original files when investigating parser/coverage gaps. Never hand-edit generated catalogs or replace cited raw text with cleaned excerpts.

## Reliability boundaries

- The uploads are wiki transcriptions and workbook summaries, **not independently verified primary publications**.
- Documents, individual rules and source-specific variants are different identities. Staggering Attack, Force Storm, Dark Transfer, Corruption and Intercept are separated explicitly.
- The Talents workbook lists trees; the index extracts **1,142 individual talents**, five explicitly homebrew and excluded by default.
- Technician and Force Prodigy have only homebrew workbook summaries, not fabricated complete class rules.
- Search is evidence discovery, not a game-rules answer or exhaustive option list. Enumeration is exhaustive only for the implemented local entity model under the selected filters.
- **44 prerequisite expressions** use three-valued logic; they do not implement acquisition/progression, complete character legality, stacking or combat resolution.
- A missing standalone page is not a missing-rules percentage. Embedded evidence and unresolved semantic coverage are reported separately.
- Source/curation/tool changes invalidate the index. Rebuild and re-review locked spans where needed; do not bypass stale checks.

No paid service, embedding model, source refetch or raw-archive reorganization is required. See the implementation report for the completed scope and prioritized follow-up work.
