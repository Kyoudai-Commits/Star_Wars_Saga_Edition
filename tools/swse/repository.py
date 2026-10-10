"""Read-only, policy-aware agent queries with explicit ambiguity and evidence."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from urllib.parse import quote, unquote, urlsplit

from .constraints import evaluate, validate_character
from .store import DEFAULT_DB, SCHEMA_VERSION, verify_inputs
from .text import alias_key, key, safe_fts_query


class Repository:
    def __init__(self, root: Path, database: Path | None = None):
        self.root = root.resolve()
        self.database = (database or self.root / DEFAULT_DB).resolve()
        if not self.database.is_file():
            raise ValueError("Retrieval index missing. Run python -m tools.swse build")
        self.connection = sqlite3.connect("file:" + quote(self.database.as_posix(), safe="/") + "?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        self.metadata = {row["key"]: json.loads(row["value"]) for row in self.connection.execute("SELECT * FROM metadata")}
        if self.metadata.get("schema_version") != SCHEMA_VERSION:
            self.close()
            raise ValueError("Unsupported retrieval schema; rebuild the index")
        self.policy = self.metadata["policy"]
        try:
            self.fresh()
        except Exception:
            self.close()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def fresh(self):
        verify_inputs(self.root, self.metadata["fingerprints"])

    def _reply(self, **data):
        return {"snapshot_id": self.metadata["snapshot_id"],
                "authority": "Local wiki/workbook evidence; not independently verified published rules.", **data}

    def _switches(self, options: dict) -> tuple[bool, bool, bool]:
        values = []
        for field in ("include_homebrew", "include_optional", "include_unreviewed"):
            value = options.get(field, self.policy[field])
            if type(value) is not bool:
                raise ValueError(f"{field} must be boolean")
            values.append(value)
        return tuple(values)

    def _where(self, options: dict, chunk: bool = False) -> tuple[str, list]:
        accepted = {"include_homebrew", "include_optional", "include_unreviewed", "kind", "variant", "book",
                    "tree", "class_name", "action", "reviewed_prerequisites"}
        if set(options) - accepted:
            raise ValueError(f"Unknown filters: {sorted(set(options) - accepted)}")
        for field in ("kind", "variant", "book", "tree", "class_name", "action"):
            if field in options and (not isinstance(options[field], str) or not options[field].strip() or len(options[field]) > 2000):
                raise ValueError(f"{field} must be a nonempty string of at most 2000 characters")
        if "reviewed_prerequisites" in options and type(options["reviewed_prerequisites"]) is not bool:
            raise ValueError("reviewed_prerequisites must be boolean")
        if options.get("kind") and options["kind"] not in self.metadata["audit"]["entities_by_kind"]:
            raise ValueError("Unknown/unimplemented entity kind; see doctor audit.entities_by_kind. Zero results must not masquerade as an unsupported taxonomy.")
        homebrew, optional, unreviewed = self._switches(options)
        terms, params = ["e.kind != 'document_context'"], []
        if not homebrew:
            terms.append("e.scope != 'homebrew'")
            if chunk:
                terms.append("c.scope != 'homebrew'")
        if not optional:
            terms.append("e.rule_role != 'optional_rule'")
            if chunk:
                terms.append("c.rule_role != 'optional_rule'")
        if not unreviewed:
            terms.append("e.review_status LIKE 'reviewed_%'")
        for field in ("kind", "variant"):
            if options.get(field):
                if field == "kind":
                    terms.append("e.kind=?")
                else:
                    terms.append("lower(json_extract(e.data,'$.variant'))=lower(?)")
                params.append(options[field])
        if options.get("book"):
            if chunk:
                terms.append("EXISTS(SELECT 1 FROM chunk_sources s WHERE s.chunk_id=c.chunk_id AND s.name_key=?)")
            else:
                terms.append("EXISTS(SELECT 1 FROM entity_sources s WHERE s.entity_id=e.entity_id AND s.name_key=?)")
            params.append(key(options["book"]))
        allowed = self.policy.get("allowed_sources")
        if allowed is not None:
            if not allowed:
                terms.append("0")
            else:
                table, identity = ("chunk_sources", "s.chunk_id=c.chunk_id") if chunk else ("entity_sources", "s.entity_id=e.entity_id")
                terms.append(f"EXISTS(SELECT 1 FROM {table} s WHERE {identity} AND s.name_key IN ({','.join('?' for _ in allowed)}))")
                params.extend(key(source) for source in allowed)
        if options.get("tree"):
            candidates = self._resolve(options["tree"], {"kind": "talent_tree", "include_homebrew": homebrew,
                                                        "include_optional": optional, "include_unreviewed": unreviewed})
            if candidates["status"] != "resolved":
                raise ValueError("Tree filter does not resolve uniquely to a local talent tree")
            terms.append("e.parent_id=?")
            params.append(candidates["entity"]["entity_id"])
        if options.get("class_name"):
            terms.append("EXISTS(SELECT 1 FROM class_hints h WHERE (h.tree_id=e.entity_id OR h.tree_id=e.parent_id) AND h.class_key=?)")
            params.append(key(options["class_name"]))
        if options.get("action"):
            terms.append("EXISTS(SELECT 1 FROM actions a WHERE a.entity_id=e.entity_id AND a.action_key=?)")
            params.append(key(options["action"]))
        if options.get("reviewed_prerequisites"):
            terms.append("e.has_prerequisites=1")
        return " AND ".join(terms), params

    @staticmethod
    def _choice(entity: dict) -> dict:
        return {field: entity.get(field) for field in ("entity_id", "name", "kind", "variant", "declared_sources",
                                                      "scope", "review_status", "tree_name", "summary_only")}

    def _resolve(self, name: str, options: dict) -> dict:
        accepted = {"kind", "variant", "book", "include_homebrew", "include_optional", "include_unreviewed"}
        if set(options) - accepted:
            raise ValueError(f"Unsupported lookup filters: {sorted(set(options) - accepted)}")
        if not isinstance(name, str) or not name.strip() or len(name) > 2000:
            raise ValueError("Lookup name must contain 1–2000 characters")
        direct = self.connection.execute("SELECT data FROM entities WHERE entity_id=?", (name,)).fetchone()
        if direct:
            candidates = [json.loads(direct["data"])]
        else:
            rows = self.connection.execute("SELECT e.data,a.required_kind FROM aliases a JOIN entities e USING(entity_id) WHERE a.alias_key=?", (alias_key(name),)).fetchall()
            contextual = [json.loads(row["data"]) for row in rows if row["required_kind"] and not options.get("kind")]
            if contextual and not any(not row["required_kind"] for row in rows):
                return {"status": "needs_context", "choices": [self._choice(entity) for entity in contextual],
                        "reason": "This alias requires an explicit kind; it is not a global URL/name equivalence."}
            candidates = [json.loads(row["data"]) for row in rows
                          if not row["required_kind"] or row["required_kind"] == options.get("kind")]
        if not candidates and name.startswith(("http://", "https://")):
            url = urlsplit(name)
            if url.hostname == "swse.fandom.com" and url.path.startswith("/wiki/"):
                local = self._resolve(unquote(url.path[len("/wiki/"):]).replace("_", " "), options)
                if local["status"] in {"resolved", "ambiguous"}:
                    choices = [self._choice(local["entity"])] if local["status"] == "resolved" else local["choices"]
                    return {"status": "cross_host_candidate", "choices": choices,
                            "reason": "Same local name/type does not verify remote page equivalence. Query the local entity explicitly."}
        unique = {entity["entity_id"]: entity for entity in candidates}
        where, parameters = self._where({k: v for k, v in options.items() if k not in {"tree", "class_name", "action", "reviewed_prerequisites"}})
        allowed = []
        for entity in unique.values():
            if self.connection.execute(f"SELECT 1 FROM entities e WHERE e.entity_id=? AND {where}", [entity["entity_id"], *parameters]).fetchone():
                allowed.append(entity)
        if not allowed:
            return {"status": "excluded_by_policy" if candidates else "not_found", "choices": [],
                    "reason": "No entity is selectable under the explicit kind/source/policy filters."}
        if len(allowed) > 1:
            return {"status": "ambiguous", "choices": [self._choice(entity) for entity in sorted(allowed, key=lambda value: value["entity_id"])],
                    "reason": "Select an entity ID, kind, source book or variant; source-specific rules will not be blended."}
        return {"status": "resolved", "entity": allowed[0]}

    def resolve(self, name: str, **options) -> dict:
        self.fresh()
        return self._reply(**self._resolve(name, options))

    @staticmethod
    def _pagination(limit, offset):
        if type(limit) is not int or not 1 <= limit <= 500 or type(offset) is not int or offset < 0:
            raise ValueError("limit must be 1–500 and offset must be a nonnegative integer")

    def list_entities(self, limit: int = 100, offset: int = 0, **options) -> dict:
        self.fresh()
        self._pagination(limit, offset)
        where, parameters = self._where(options)
        total = self.connection.execute(f"SELECT count(*) FROM entities e WHERE {where}", parameters).fetchone()[0]
        rows = self.connection.execute(f"SELECT e.data FROM entities e WHERE {where} ORDER BY e.name_key,e.entity_id LIMIT ? OFFSET ?", [*parameters, limit, offset])
        items = [self._choice(json.loads(row["data"])) for row in rows]
        warnings = ["Enumeration covers local extracted/curated entities under these filters, not all game rules."]
        if options.get("class_name"):
            warnings.append("Class filtering uses category access hints, not proof of character eligibility or unconditional access.")
        return self._reply(status="ok", operation="enumeration_not_top_k_search", total=total, offset=offset,
                           items=items, next_offset=offset + len(items) if offset + len(items) < total else None,
                           complete_for_this_page=len(items) == total, warnings=warnings)

    def search(self, query: str, limit: int = 8, offset: int = 0, **options) -> dict:
        self.fresh()
        self._pagination(limit, offset)
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ValueError("Search text must contain 1–4000 characters")
        expression = safe_fts_query(query)
        if not expression:
            return self._reply(status="no_search_terms", items=[], total_matching_chunks=0)
        where, parameters = self._where(options, chunk=True)
        join = "FROM chunks_fts JOIN chunks c ON c.chunk_id=chunks_fts.chunk_id JOIN entities e ON e.entity_id=c.entity_id"
        conjunction = expression.replace(" OR ", " AND ")
        total = self.connection.execute(f"SELECT count(*) {join} WHERE chunks_fts MATCH ? AND {where}", [conjunction, *parameters]).fetchone()[0]
        strategy = "all_terms"
        if total:
            expression = conjunction
        else:
            strategy = "any_terms_fallback"
            total = self.connection.execute(f"SELECT count(*) {join} WHERE chunks_fts MATCH ? AND {where}", [expression, *parameters]).fetchone()[0]
        rows = self.connection.execute(f"SELECT c.data AS chunk_data,e.data AS entity_data,bm25(chunks_fts,0,6,3,1) AS rank {join} WHERE chunks_fts MATCH ? AND {where} ORDER BY rank,c.chunk_id LIMIT ? OFFSET ?", [expression, *parameters, limit, offset])
        items = []
        for row in rows:
            chunk, entity = json.loads(row["chunk_data"]), json.loads(row["entity_data"])
            items.append({**self._choice(entity), "chunk_id": chunk["chunk_id"], "rule_role": chunk["rule_role"],
                          "passage_scope": chunk["scope"], "declared_sources": chunk["declared_sources"],
                          "heading_path": chunk["heading_path"], "citation": chunk["citation"],
                          "has_table": chunk["has_table"], "char_count": chunk["char_count"],
                          "excerpt": chunk["text"][:1400], "excerpt_only": len(chunk["text"]) > 1400,
                          "context_chunk_ids": chunk.get("context_chunk_ids", []), "lexical_rank": row["rank"]})
        return self._reply(status="ok", operation="lexical_evidence_search_not_rules_answer", query=query,
                           match_strategy=strategy, total_matching_chunks=total, items=items,
                           next_offset=offset + len(items) if offset + len(items) < total else None,
                           warning="Search excerpts can be partial. Fetch a chunk or entity bundle for full allowed evidence; do not infer exhaustive options from top-k results.")

    @staticmethod
    def _budget(value):
        if type(value) is not int or not 1 <= value <= 200000:
            raise ValueError("max_chars must be 1–200000 (characters, not model tokens)")

    def _allowed_chunks(self, entity_id: str, options: dict) -> list[dict]:
        # A source facet selects an entity/variant. Related clarification chunks
        # can declare another source, so do not apply the facet again here.
        chunk_options = {k: v for k, v in options.items() if k not in {"book", "variant", "tree", "class_name", "action", "reviewed_prerequisites"}}
        where, parameters = self._where(chunk_options, chunk=True)
        rows = self.connection.execute(f"SELECT c.data FROM chunks c JOIN entities e USING(entity_id) WHERE c.entity_id=? AND {where}", [entity_id, *parameters])
        return sorted((json.loads(row["data"]) for row in rows), key=lambda chunk: chunk["citation"]["start_line"])

    def get(self, name: str, max_chars: int | None = None, expand: bool = False, **options) -> dict:
        self.fresh()
        if type(expand) is not bool:
            raise ValueError("expand must be boolean")
        budget = self.policy["evidence_char_budget"] if max_chars is None else max_chars
        self._budget(budget)
        selected = self._resolve(name, options)
        if selected["status"] != "resolved":
            return self._reply(**selected)
        entity = selected["entity"]
        if entity.get("summary_only"):
            return self._reply(status="summary_only_insufficient_rules", entity=entity,
                               workbook_summaries=self._workbook_for(entity["entity_id"]),
                               warning="Only spreadsheet summaries are local; do not reconstruct a complete class or rules entry.")
        allowed = self._allowed_chunks(entity["entity_id"], options)
        total = self.connection.execute("SELECT count(*) FROM chunks WHERE entity_id=?", (entity["entity_id"],)).fetchone()[0]
        chosen, omitted, used = [], [], 0
        for chunk in allowed:
            if used + chunk["char_count"] <= budget:
                chosen.append(chunk)
                used += chunk["char_count"]
            else:
                omitted.append({"chunk_id": chunk["chunk_id"], "citation": chunk["citation"],
                                "char_count": chunk["char_count"], "reason": "character_budget"})
        related = [json.loads(row["data"]) for row in self.connection.execute("SELECT data FROM relationships WHERE source=?", (entity["entity_id"],))]
        context, omitted_context = [], []
        withheld_context = 0
        if expand and entity.get("parent_id"):
            parent_row = self.connection.execute("SELECT data FROM entities WHERE entity_id=?", (entity["parent_id"],)).fetchone()
            if parent_row:
                parent = json.loads(parent_row["data"])
                parent_total = self.connection.execute("SELECT count(*) FROM chunks WHERE entity_id=?", (parent["entity_id"],)).fetchone()[0]
                parent_allowed = self._allowed_chunks(parent["entity_id"], {k: v for k, v in options.items() if k != "kind"})
                withheld_context = parent_total - len(parent_allowed)
                # Context is parent's own passages only; never sibling variants/talents.
                for chunk in parent_allowed:
                    if used + chunk["char_count"] <= budget:
                        context.append(chunk)
                        used += chunk["char_count"]
                    else:
                        omitted_context.append({"chunk_id": chunk["chunk_id"], "citation": chunk["citation"],
                                                "char_count": chunk["char_count"], "reason": "character_budget"})
        return self._reply(status="ok", entity=entity, evidence=chosen, context=context,
                           relationships=related, workbook_summaries=self._workbook_for(entity["entity_id"]),
                           emitted_characters=used, max_chars=budget, omitted_chunks=omitted,
                           context_requested=expand, omitted_context_chunks=omitted_context,
                           withheld_context_by_policy=withheld_context,
                           complete_for_entity_allowed_passages=not omitted,
                           complete_for_requested_context=not omitted_context if expand else None,
                           withheld_by_policy=total - len(allowed), complete_for_allowed_passages=not (omitted or omitted_context),
                           warnings=["Review/source labels describe local text, not independently verified published rules.",
                                     "Unreviewed mixed-source records need per-passage source interpretation; retrieval is not a rules ruling."])

    def chunk(self, chunk_id: str, max_chars: int | None = None, **options) -> dict:
        self.fresh()
        budget = self.policy["evidence_char_budget"] if max_chars is None else max_chars
        self._budget(budget)
        where, parameters = self._where(options, chunk=True)
        row = self.connection.execute(f"SELECT c.data FROM chunks c JOIN entities e USING(entity_id) WHERE c.chunk_id=? AND {where}", [chunk_id, *parameters]).fetchone()
        if not row:
            return self._reply(status="not_found_or_excluded_by_policy")
        chunk = json.loads(row["data"])
        if chunk["char_count"] > budget:
            return self._reply(status="budget_too_small", char_count=chunk["char_count"], citation=chunk["citation"],
                               reason="Whole paragraphs/tables are not truncated to appear complete.")
        return self._reply(status="ok", evidence=chunk)

    def _workbook_for(self, entity_id: str) -> list[dict]:
        # Small 644-row table; indexed entity join could be added if needed.
        result = []
        for row in self.connection.execute("SELECT data FROM workbook ORDER BY sheet,row_number"):
            association = json.loads(row["data"])
            if entity_id in association["entity_ids"]:
                result.append(association)
        return result

    def coverage(self, name: str, **options) -> dict:
        self.fresh()
        row = self.connection.execute("SELECT data FROM coverage WHERE name_key=?", (key(name),)).fetchone()
        selected = self._resolve(name, options)
        gaps = [json.loads(item["data"]) for item in self.connection.execute("SELECT data FROM missing_targets WHERE name_key=?", (key(name),))]
        if row:
            assessment = json.loads(row["data"])
            return self._reply(status=assessment["status"], assessment=assessment, entity_resolution=selected,
                               linked_document_gaps=gaps,
                               warning="Coverage applies only to the stated local scope, not the entire game's rules.")
        if selected["status"] == "resolved":
            entity = selected["entity"]
            status = "summary_only_insufficient_rules" if entity.get("summary_only") else "local_entity_evidence"
            return self._reply(status=status, entity_resolution=selected, linked_document_gaps=gaps,
                               warning="Entity presence does not prove complete semantic rule coverage or primary-source accuracy.")
        if selected["status"] in {"ambiguous", "needs_context", "excluded_by_policy", "cross_host_candidate"}:
            return self._reply(status=selected["status"], entity_resolution=selected, linked_document_gaps=gaps)
        return self._reply(status="document_gap_semantic_coverage_unreviewed" if gaps else "no_curated_local_evidence",
                           entity_resolution=selected, linked_document_gaps=gaps,
                           warning="A failed name lookup or absent linked page is not proof that all embedded evidence is absent. Search passages; do not invent details.")

    def _talent(self, value, options: dict) -> dict | None:
        if isinstance(value, str):
            name, tree = value, None
        else:
            name, tree = value.get("entity_id", value.get("name")), value.get("tree")
        selected = self._resolve(name, {**options, "kind": "talent"})
        if selected["status"] != "resolved":
            # Ambiguous names can be narrowed by explicit tree context.
            if tree:
                candidates = self.connection.execute("SELECT data FROM entities WHERE kind='talent' AND name_key=?", (key(name),))
                values = [json.loads(row["data"]) for row in candidates]
                matching = [entity for entity in values if key(entity.get("tree_name", "")) == key(tree)]
                if len(matching) == 1 and self._resolve(matching[0]["entity_id"], {**options, "kind": "talent"})["status"] == "resolved":
                    return matching[0]
            return None
        entity = selected["entity"]
        if tree and key(tree) != key(entity.get("tree_name", "")):
            return None  # Never trust a forged name/tree assignment.
        return entity

    def check(self, name: str, character: dict, **options) -> dict:
        self.fresh()
        validate_character(character)
        selected = self._resolve(name, options)
        if selected["status"] != "resolved":
            return self._reply(result="unknown", **selected)
        entity = selected["entity"]
        if "prerequisites_ast" not in entity:
            return self._reply(status="unencoded_prerequisites", result="unknown", entity=self._choice(entity),
                               prerequisites_raw=entity.get("prerequisites_raw"),
                               citations=entity.get("prerequisite_citations", entity["citations"]),
                               reason="No source-reviewed executable prerequisite expression exists; absence of an AST does not mean no prerequisites.")
        expression = evaluate(entity["prerequisites_ast"], character,
                              lambda value: self._talent(value, {k: v for k, v in options.items() if k not in {"kind", "book", "variant"}}))
        return self._reply(status="encoded_prerequisites_checked", result=expression["result"],
                           entity=self._choice(entity), explanation=expression,
                           citations=entity["prerequisite_citations"], scope=entity["prerequisite_check_scope"],
                           warning="This checks explicit supplied facts against reviewed local prerequisites only. It does not validate progression, acquisition, class/tree access, source adoption or full character legality.")

    def doctor(self) -> dict:
        self.fresh()
        integrity = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = self.connection.execute("PRAGMA foreign_key_check").fetchall()
        return self._reply(status="ok" if integrity == "ok" and not foreign_keys else "failed",
                           sqlite_integrity=integrity, foreign_key_violations=len(foreign_keys),
                           policy=self.policy, audit=self.metadata["audit"])
