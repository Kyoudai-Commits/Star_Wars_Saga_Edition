"""Conservative entity and passage extraction; no changes to uploaded sources."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

from tools.build_catalog import json_lines, wiki_key
from .text import alias_key, heading_paths, inferred_role, is_homebrew, key, prereq_lines, slug, units

CURATION_FILES = ("source_policy.json", "overrides.json", "aliases.json", "coverage.json",
                  "prerequisites.json", "relationships.json")
ROLES = {"base_rule", "clarification", "optional_rule", "gm_advice", "unclassified"}


def load_curation(root: Path) -> dict:
    result = {}
    for name in CURATION_FILES:
        data = json.loads((root / "curation" / name).read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            raise ValueError(f"Unsupported curation schema: {name}")
        result[name] = data
    policy = result["source_policy.json"]
    for field in ("include_homebrew", "include_optional", "include_unreviewed"):
        if not isinstance(policy.get(field), bool):
            raise ValueError(f"Policy {field} must be boolean")
    if policy.get("allowed_sources") is not None and not (
            isinstance(policy["allowed_sources"], list) and
            all(isinstance(item, str) for item in policy["allowed_sources"])):
        raise ValueError("allowed_sources must be null or a list of source names")
    for field in ("chunk_char_budget", "evidence_char_budget", "default_search_limit"):
        if type(policy.get(field)) is not int or policy[field] <= 0:
            raise ValueError(f"Policy {field} must be a positive integer")
    return result


def citation(doc: dict, start: int, end: int) -> dict:
    return {"path": doc["path"], "start_line": start, "end_line": end,
            "canonical_url": doc["canonical_url"], "revision_id": doc["revision_id"],
            "article_sha256": doc["article_sha256"], "file_sha256": doc["file_sha256"],
            "provenance": "local_wiki_transcription_not_primary_verified"}


def validate_review(review: dict, docs: dict, label: str) -> dict:
    stem = review["document"]
    if stem not in docs:
        raise ValueError(f"Unknown document in {label}: {stem}")
    doc = docs[stem]
    if review.get("article_sha256") != doc["article_sha256"]:
        raise ValueError(f"Stale curated article hash in {label}: {stem}")
    for start, end in review.get("ranges", []):
        if type(start) is not int or type(end) is not int or not (
                doc["article_start_line"] <= start <= end <= doc["article_end_line"]):
            raise ValueError(f"Invalid curated range in {label}: {stem} {start}:{end}")
    return doc


def _source_context(doc: dict, paths: dict, line: int) -> list[str]:
    path = paths[line]
    candidates = []
    for marker in doc["source_markers"]:
        if marker["line"] > line:
            continue
        owner = paths.get(marker["line"], ())
        if path[:len(owner)] == owner:
            candidates.append((len(owner), marker["line"], marker))
    if not candidates:
        return []
    depth, _, marker = max(candidates, key=lambda value: (value[0], value[1]))
    # Do not call unmarked additional/homebrew talents Core merely because a
    # different source was declared in the document introduction.
    if depth == 0 and any("additional" in title.casefold() or "homebrew" in title.casefold() for title in path):
        return []
    return [ref["title"] for ref in marker["declared_references"]]


def _metadata(doc: dict, id_: str, name: str, kind: str, ranges: list[list[int]],
              parent: str | None = None, **extra) -> dict:
    return {"entity_id": id_, "name": name, "name_key": key(name), "kind": kind,
            "parent_id": parent, "document_id": doc["document_id"], "ranges": ranges,
            "scope": "unmarked", "rule_role": "unclassified", "variant": None,
            "declared_sources": [], "source_attribution": "extracted_declaration",
            "review_status": "extracted_not_semantically_reviewed",
            "provenance": "local_wiki_transcription_not_primary_verified",
            "citations": [citation(doc, start, end) for start, end in ranges], **extra}


def extract(root: Path) -> dict:
    documents = json_lines(root / "catalog/wiki_documents.jsonl")
    docs = {Path(doc["path"]).stem: doc for doc in documents}
    curation = load_curation(root)
    overrides = curation["overrides.json"]["documents"]
    for stem, override in overrides.items():
        validate_review({**override, "document": stem}, docs, "overrides")
    entities, passages, aliases, relationships = [], [], [], []
    entity_map = {}
    annotation_count = 0

    def add_entity(entity: dict):
        if entity["entity_id"] in entity_map:
            raise ValueError(f"Duplicate entity ID: {entity['entity_id']}")
        entities.append(entity)
        entity_map[entity["entity_id"]] = entity

    for stem, doc in sorted(docs.items()):
        lines = (root / doc["path"]).read_text(encoding="utf-8").splitlines()
        start, end = doc["article_start_line"], doc["article_end_line"]
        paths = heading_paths(lines, start, end)
        override = overrides.get(stem, {})
        replaced = bool(override.get("replace_entities"))
        kind = "document_context" if replaced else doc["document_kind_hint"]
        page_id = ("document" if replaced else kind) + ":" + stem
        page = _metadata(doc, page_id, doc["title"], kind, [[start, end]],
                         needs_source_review=len(doc["source_markers"]) > 1 and not replaced)
        add_entity(page)
        members = [page]
        for spec in override.get("replace_entities", []) + override.get("add_entities", []):
            validate_review({"document": stem, "article_sha256": override["article_sha256"],
                             "ranges": spec["ranges"]}, docs, "entity override")
            if spec["rule_role"] not in ROLES:
                raise ValueError(f"Unknown rule role: {spec['rule_role']}")
            entity = _metadata(doc, spec["id"], spec["name"], spec["kind"], spec["ranges"],
                               page_id, variant=spec["variant"],
                               declared_sources=spec["declared_sources"],
                               rule_role=spec["rule_role"], review_status=spec["review_status"],
                               source_attribution="reviewed_local_span", extra_aliases=spec.get("aliases", []))
            add_entity(entity)
            members.append(entity)
        if doc["document_kind_hint"] == "talent_tree":
            for section in doc["sections"]:
                if section["level"] != 3:
                    continue
                name = section["heading"]
                entity = _metadata(doc, f"talent:{stem}:{slug(name)}", name, "talent",
                                   [[section["start_line"], section["end_line"]]], page_id,
                                   scope="homebrew" if is_homebrew(paths[section["start_line"]]) else "unmarked",
                                   rule_role="base_rule", tree_name=doc["title"],
                                   review_status="extracted_heading_not_semantically_reviewed")
                add_entity(entity)
                members.append(entity)
                relationships.append({"source": entity["entity_id"], "relation": "belongs_to_tree",
                                      "target": page_id, "review_status": "explicit_heading_structure",
                                      "citations": [citation(doc, section["start_line"], section["start_line"])]})
        annotations = override.get("annotations", [])
        for annotation in annotations:
            validate_review({"document": stem, "article_sha256": override["article_sha256"],
                             "ranges": [annotation["range"]]}, docs, "role annotation")
            if annotation["rule_role"] not in ROLES:
                raise ValueError(f"Unknown annotation role: {annotation['rule_role']}")
        annotation_count += len(annotations)
        for i, left in enumerate(annotations):
            for right in annotations[i + 1:]:
                if max(left["range"][0], right["range"][0]) <= min(left["range"][1], right["range"][1]):
                    raise ValueError(f"Overlapping role annotations: {stem}")
        # Sibling reviewed entities must not overlap. Parent containment is fine.
        reviewed = [member for member in members if member is not page and member["kind"] != "talent"]
        for i, left in enumerate(reviewed):
            for right in reviewed[i + 1:]:
                for a, b in left["ranges"]:
                    for c, d in right["ranges"]:
                        if max(a, c) <= min(b, d):
                            raise ValueError(f"Overlapping reviewed entity ranges: {stem}")
        boundaries = {a for member in members for a, _ in member["ranges"]}
        boundaries.update(b + 1 for member in members for _, b in member["ranges"])
        boundaries.update(marker["line"] for marker in doc["source_markers"])
        boundaries.update(x for annotation in annotations for x in (annotation["range"][0], annotation["range"][1] + 1))
        source_units = units(lines, start, end, boundaries)
        for member in members:
            if not member["declared_sources"]:
                first = next((unit for unit in source_units
                              if any(a <= unit.start and unit.end <= b for a, b in member["ranges"])
                              and not re.match(r"^(#{1,6} |\*Reference Books?:)", lines[unit.start - 1])), None)
                if first:
                    member["declared_sources"] = _source_context(doc, paths, first.start)
            if member["kind"] in {"feat", "talent", "heroic_class", "prestige_class", "force_power"}:
                raw, spans = prereq_lines(lines, member["ranges"])
                if raw:
                    member["prerequisites_raw"] = raw
                    member["prerequisite_citations"] = [citation(doc, a, b) for a, b in spans]
            if member["kind"] == "talent_tree":
                classes = [category[:-len(" Talent Trees")] for category in doc["categories"]
                           if category.endswith(" Talent Trees") and category[:-len(" Talent Trees")] in
                           {item["title"] for item in documents if item["document_kind_hint"] in {"heroic_class", "prestige_class"}}]
                member["class_access_hints"] = sorted(classes)
                for label in classes:
                    relationships.append({"source": member["entity_id"], "relation": "class_access_hint",
                                          "target_name": label, "review_status": "category_hint_not_eligibility",
                                          "citations": [citation(doc, 9, 9)]})
        packed, buffer, attributes = [], [], None

        def flush():
            nonlocal buffer, attributes
            if not buffer:
                return
            entity_id, role, scope, sources, headings = attributes
            text = "\n\n".join(unit.text for unit in buffer)
            a, b = buffer[0].start, buffer[-1].end
            chunk_id = "chunk:" + hashlib.sha256(f"{doc['document_id']}|{a}|{b}|{entity_id}".encode()).hexdigest()[:24]
            packed.append({"chunk_id": chunk_id, "entity_id": entity_id,
                           "document_id": doc["document_id"], "text": text,
                           "rule_role": role, "scope": scope, "declared_sources": list(sources),
                           "heading_path": list(headings), "has_table": any(unit.table for unit in buffer),
                           "char_count": len(text), "citation": citation(doc, a, b),
                           "review_status": entity_map[entity_id]["review_status"]})
            buffer, attributes = [], None

        for unit in source_units:
            raw_line = lines[unit.start - 1]
            if re.match(r"^(#{1,6} |\*Reference Books?:)", raw_line):
                continue  # These remain in structured context and original citations.
            candidates = [member for member in members
                          if any(a <= unit.start and unit.end <= b for a, b in member["ranges"])]
            if not candidates:
                raise ValueError(f"Unassigned text unit: {stem}:{unit.start}")
            member = min(candidates, key=lambda value: sum(b - a + 1 for a, b in value["ranges"]))
            sources = _source_context(doc, paths, unit.start)
            if member["source_attribution"] == "reviewed_local_span":
                sources = member["declared_sources"]
            role = inferred_role(unit)
            if role == "unclassified" and any(source in {"Jedi Counseling", "Saga Edition FAQ"} for source in sources):
                role = "clarification"
            if role == "unclassified" and member["rule_role"] != "unclassified":
                role = member["rule_role"]
            if role == "unclassified" and member["kind"] in {"feat", "force_power", "talent"}:
                role = "base_rule"
            scope = "homebrew" if is_homebrew(unit.heading_path) or member["scope"] == "homebrew" else "unmarked"
            for annotation in annotations:
                if annotation["range"][0] <= unit.start and unit.end <= annotation["range"][1]:
                    role, sources = annotation["rule_role"], annotation["declared_sources"]
            attrs = (member["entity_id"], role, scope, tuple(sources), unit.heading_path)
            budget = curation["source_policy.json"]["chunk_char_budget"]
            if attributes is not None and (attrs != attributes or sum(len(item.text) + 2 for item in buffer) + len(unit.text) > budget):
                flush()
            attributes = attrs
            buffer.append(unit)
            if len(unit.text) > budget:
                flush()  # Never split a table or paragraph to pretend to meet a budget.
        flush()
        for i, chunk in enumerate(packed):
            if chunk["has_table"] and i and packed[i - 1]["entity_id"] == chunk["entity_id"]:
                chunk["context_chunk_ids"] = [packed[i - 1]["chunk_id"]]
        passages.extend(packed)
        for member in members:
            member["mechanic_fields"] = {}
            if member["kind"] in {"force_power", "starship_maneuver"}:
                for chunk in packed:
                    if chunk["entity_id"] != member["entity_id"] or chunk["rule_role"] != "base_rule":
                        continue
                    for line in chunk["text"].splitlines():
                        match = re.match(r"^(Time|Targets?):\s*(.+)$", line)
                        if match:
                            member["mechanic_fields"].setdefault(match.group(1).lower(), []).append(
                                {"text": match.group(2), "citation": chunk["citation"]})
            labels = [member["name"], *member.pop("extra_aliases", [])]
            for label in labels:
                aliases.append({"text": label, "key": alias_key(label), "entity_id": member["entity_id"],
                                "required_kind": None, "association": "local_entity_name"})
            if member["kind"] == "talent_tree":
                label = member["name"].removesuffix(" Talent Tree")
                aliases.append({"text": label, "key": alias_key(label), "entity_id": member["entity_id"],
                                "required_kind": "talent_tree", "association": "kind_scoped_tree_abbreviation"})
            if member is page and not replaced or member in reviewed and replaced:
                for url in {doc["canonical_url"], doc["source_url"]}:
                    aliases.append({"text": url, "key": alias_key(url), "entity_id": member["entity_id"],
                                    "required_kind": None, "association": "export_manifest_document_url"})
                    title_key = wiki_key(url)
                    if title_key and doc["document_kind_hint"] == "category":
                        aliases.append({"text": title_key[1], "key": alias_key(title_key[1]),
                                        "entity_id": member["entity_id"], "required_kind": None,
                                        "association": "category_title_or_recorded_redirect"})

    workbook = json_lines(root / "catalog/workbook_records.jsonl")
    row_overrides = {(row["sheet"], row["row"]): row["entity_id"]
                     for row in curation["aliases.json"]["workbook_rows"]}
    associations, unresolved_rows = [], []
    for row in workbook:
        chosen = row_overrides.get((row["sheet"], row["row"]))
        matches = [member for member in entities if member["kind"] == row["entity_type_hint"]
                   and member["name_key"] == key(row["label"])]
        if chosen:
            if chosen not in entity_map:
                raise ValueError(f"Unknown workbook override entity: {chosen}")
            matches = [entity_map[chosen]]
        if not matches and row["scope"] == "explicit_homebrew":
            id_ = f"{row['entity_type_hint']}:{slug(row['label'])}"
            entity = {"entity_id": id_, "name": row["label"], "name_key": key(row["label"]),
                      "kind": row["entity_type_hint"], "parent_id": None, "document_id": None,
                      "ranges": [], "citations": [{"path": row["workbook"], "sheet": row["sheet"],
                                                    "row": row["row"], "file_sha256": row["workbook_sha256"],
                                                    "provenance": "workbook_summary_only"}],
                      "scope": "homebrew", "rule_role": "unclassified", "variant": None,
                      "declared_sources": [], "source_attribution": "workbook_summary_only",
                      "review_status": "summary_only_not_complete_rules", "provenance": "workbook_summary_only",
                      "mechanic_fields": {}, "summary_only": True}
            add_entity(entity)
            matches = [entity]
            aliases.append({"text": entity["name"], "key": alias_key(entity["name"]),
                            "entity_id": id_, "required_kind": None, "association": "workbook_summary_name"})
        if len(matches) != 1:
            unresolved_rows.append({"sheet": row["sheet"], "row": row["row"], "label": row["label"],
                                    "candidate_entity_ids": [match["entity_id"] for match in matches]})
        associations.append({"sheet": row["sheet"], "row": row["row"], "record": row,
                             "entity_ids": [match["entity_id"] for match in matches],
                             "association": "reviewed_local_context" if chosen else "local_name_and_type_association",
                             "remote_url_equivalence_verified": False})
    for alias in curation["aliases.json"]["aliases"]:
        if alias["entity_id"] not in entity_map:
            raise ValueError(f"Unknown curated alias entity: {alias['entity_id']}")
        if alias.get("required_kind") and alias["required_kind"] != entity_map[alias["entity_id"]]["kind"]:
            raise ValueError(f"Alias kind mismatch: {alias['text']}")
        aliases.append({**alias, "key": alias_key(alias["text"])})
    for review in curation["prerequisites.json"]["rules"]:
        doc = validate_review(review, docs, "prerequisites")
        if not review.get("ranges") or review["entity_id"] not in entity_map:
            raise ValueError(f"Invalid reviewed prerequisite entity: {review['entity_id']}")
        entity = entity_map[review["entity_id"]]
        if entity["document_id"] != doc["document_id"] or any(
                not any(a <= c and d <= b for a, b in entity["ranges"]) for c, d in review["ranges"]):
            raise ValueError(f"Prerequisite citation escapes its entity: {review['entity_id']}")
        entity["prerequisites_ast"] = review["ast"]
        entity["prerequisite_review_status"] = review["review_status"]
        entity["prerequisite_check_scope"] = review["scope"]
        entity["prerequisite_citations"] = [citation(doc, a, b) for a, b in review["ranges"]]
    # These are references within a reviewed expression, NOT flattened mandatory
    # edges. AND/OR/count semantics stay in the AST and explicit logic path.
    for entity in entities:
        if "prerequisites_ast" not in entity:
            continue

        def expression_refs(node, path=()):
            if node["op"] in {"all", "any"}:
                for index, child in enumerate(node["args"]):
                    yield from expression_refs(child, path + ((node["op"], index),))
                return
            labels = []
            if node["op"] == "has":
                kind = {"feats": "feat", "talents": "talent", "force_powers": "force_power",
                        "trained_skills": "skill", "droid_systems": "droid_system"}[node["field"]]
                labels.append((node["value"], kind))
            elif node["op"] == "has_talent":
                labels.append((node["name"], "talent"))
            elif node["op"] == "count_talents":
                labels.extend((label, "talent_tree") for label in node["trees"])
            for label, kind in labels:
                candidates = [item for item in entities if item["name_key"] == key(label) and item["kind"] == kind
                              and ("tree" not in node or item.get("tree_name") == node["tree"])]
                yield {"source": entity["entity_id"], "relation": "prerequisite_reference",
                       "target": candidates[0]["entity_id"] if len(candidates) == 1 else None,
                       "target_name": label, "target_kind": kind,
                       "target_is_local": len(candidates) == 1,
                       "candidate_entity_ids": [item["entity_id"] for item in candidates],
                       "condition": node, "logic_path": [{"operator": op, "child_index": i} for op, i in path],
                       "review_status": "reviewed_expression_reference_not_flat_requirement",
                       "citations": entity["prerequisite_citations"]}

        relationships.extend(expression_refs(entity["prerequisites_ast"]))
    for relation in curation["relationships.json"]["relationships"]:
        doc = validate_review(relation, docs, "relationships")
        if relation["source"] not in entity_map:
            raise ValueError(f"Unknown relationship source: {relation['source']}")
        if relation["target"] not in entity_map and not relation["target"].startswith("rule_reference:"):
            raise ValueError(f"Unknown relationship target: {relation['target']}")
        relationships.append({**relation, "target_is_local": relation["target"] in entity_map,
                              "citations": [citation(doc, a, b) for a, b in relation["ranges"]]})
    coverage = curation["coverage.json"]["concepts"]
    for review in coverage:
        if "evidence_document" in review:
            doc = validate_review({**review, "document": review["evidence_document"]}, docs, "coverage")
            review["citations"] = [citation(doc, a, b) for a, b in review["ranges"]]
        for id_ in review.get("entity_ids", []):
            if id_ not in entity_map:
                raise ValueError(f"Unknown coverage entity: {id_}")
    ids = [passage["chunk_id"] for passage in passages]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate chunk IDs")
    missing_targets = json_lines(root / "catalog/missing_wiki_targets.jsonl")
    source_labels = {key(ref["title"]) for doc in documents for marker in doc["source_markers"]
                     for ref in marker["declared_references"]}
    name_candidates = defaultdict(list)
    for entity in entities:
        if entity["kind"] not in {"document_context", "reference", "category"}:
            name_candidates[entity["name_key"]].append(entity["entity_id"])
    reviews = {key(label): concept for concept in coverage for label in [concept["name"], *concept.get("aliases", [])]}
    queue = []
    embedded_candidates = 0
    for target in missing_targets:
        label = key(target["wiki_title"])
        candidates = name_candidates.get(label, [])
        embedded_candidates += bool(candidates)
        if label in source_labels or target["wiki_title"].startswith(("File:", "Category:")):
            continue  # Keep bibliographic/media targets in the full original gap registry.
        review = reviews.get(label)
        queue.append({**target, "local_name_candidate_ids": candidates,
                      "reviewed_coverage_status": review["status"] if review else None,
                      "interpretation": "Local name candidates are not URL equivalence or complete semantic coverage."})
    queue = queue[:75]
    audit = {
        "schema_version": 1, "document_count": len(documents), "entity_count": len(entities),
        "entities_by_kind": dict(sorted(Counter(entity["kind"] for entity in entities).items())),
        "individual_talents": sum(entity["kind"] == "talent" for entity in entities),
        "homebrew_talents": [entity["entity_id"] for entity in entities if entity["kind"] == "talent" and entity["scope"] == "homebrew"],
        "summary_only_entities": [entity["entity_id"] for entity in entities if entity.get("summary_only")],
        "reviewed_boundary_documents": sorted(overrides), "reviewed_prerequisite_expressions": len(curation["prerequisites.json"]["rules"]),
        "manual_role_annotations": annotation_count, "chunk_count": len(passages),
        "chunks_by_role": dict(sorted(Counter(passage["rule_role"] for passage in passages).items())),
        "homebrew_chunks": sum(passage["scope"] == "homebrew" for passage in passages),
        "table_chunks": sum(passage["has_table"] for passage in passages),
        "oversized_unsplit_chunks": sum(passage["char_count"] > curation["source_policy.json"]["chunk_char_budget"] for passage in passages),
        "search_text_characters": sum(passage["char_count"] for passage in passages),
        "raw_article_characters": sum(doc["article_characters"] for doc in documents),
        "workbook_associations": len(associations), "ambiguous_or_unmatched_workbook_rows": unresolved_rows,
        "relationship_count": len(relationships),
        "missing_document_targets_with_local_entity_name_candidates": embedded_candidates,
        "coverage_queue_count": len(queue),
        "limits": ["Structural extraction is not comprehensive semantic review or primary-source verification.",
                   "Role detection is conservative and partly heuristic outside locked manual annotations.",
                   "Unreviewed multi-source entities must be read with their per-chunk source labels.",
                   "Only reviewed prerequisite expressions are executable; all other checks remain unknown.",
                   "Missing detailed rules cannot be fetched from the SWSE wiki in this network environment."],
    }
    return {"documents": documents, "entities": entities, "chunks": passages, "aliases": aliases,
            "relationships": relationships, "workbook": associations, "coverage": coverage,
            "policy": curation["source_policy.json"], "coverage_queue": queue, "audit": audit}
