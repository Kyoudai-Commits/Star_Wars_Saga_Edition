"""Atomic SQLite/FTS5 builds and strict source/curation freshness checks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import quote
import tempfile

from tools.build_catalog import EXPORT_DIR, build_catalog, sha256, within
from .constraints import validate_ast
from .extract import CURATION_FILES, extract
from .text import key

SCHEMA_VERSION = 1
DEFAULT_DB = Path("artifacts/swse.sqlite3")

SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE documents (document_id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, data TEXT NOT NULL);
CREATE TABLE entities (
 entity_id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL, kind TEXT NOT NULL,
 parent_id TEXT REFERENCES entities(entity_id), document_id TEXT REFERENCES documents(document_id),
 scope TEXT NOT NULL, rule_role TEXT NOT NULL, review_status TEXT NOT NULL,
 has_prerequisites INTEGER NOT NULL, data TEXT NOT NULL
);
CREATE INDEX entity_name_idx ON entities(name_key,kind);
CREATE INDEX entity_parent_idx ON entities(parent_id);
CREATE INDEX entity_kind_idx ON entities(kind,scope);
CREATE TABLE aliases (alias_key TEXT NOT NULL, entity_id TEXT REFERENCES entities(entity_id),
 required_kind TEXT NOT NULL, data TEXT NOT NULL,
 PRIMARY KEY(alias_key,entity_id,required_kind));
CREATE INDEX aliases_key_idx ON aliases(alias_key);
CREATE TABLE entity_sources (entity_id TEXT REFERENCES entities(entity_id), name TEXT, name_key TEXT,
 PRIMARY KEY(entity_id,name_key));
CREATE TABLE class_hints (tree_id TEXT REFERENCES entities(entity_id), class_key TEXT, class_name TEXT,
 PRIMARY KEY(tree_id,class_key));
CREATE TABLE actions (entity_id TEXT REFERENCES entities(entity_id), action_key TEXT, action_text TEXT,
 PRIMARY KEY(entity_id,action_key));
CREATE TABLE chunks (
 chunk_id TEXT PRIMARY KEY, entity_id TEXT REFERENCES entities(entity_id), document_id TEXT REFERENCES documents(document_id),
 rule_role TEXT NOT NULL, scope TEXT NOT NULL, char_count INTEGER NOT NULL, data TEXT NOT NULL
);
CREATE INDEX chunk_entity_idx ON chunks(entity_id);
CREATE TABLE chunk_sources (chunk_id TEXT REFERENCES chunks(chunk_id), name_key TEXT, PRIMARY KEY(chunk_id,name_key));
CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED,entity_name,headings,body,
 tokenize='porter unicode61 remove_diacritics 2');
CREATE TABLE relationships (source TEXT REFERENCES entities(entity_id), relation TEXT, target TEXT, data TEXT NOT NULL);
CREATE INDEX relationship_source_idx ON relationships(source);
CREATE TABLE workbook (sheet TEXT, row_number INTEGER, data TEXT NOT NULL, PRIMARY KEY(sheet,row_number));
CREATE TABLE coverage (name_key TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE missing_targets (wiki_title TEXT, name_key TEXT, host TEXT, data TEXT NOT NULL, PRIMARY KEY(wiki_title,host));
CREATE INDEX missing_name_idx ON missing_targets(name_key);
"""


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def fingerprints(root: Path, documents: list[dict], inputs: list[dict]) -> list[dict]:
    result = {record["path"]: record["sha256"] for record in inputs}
    result.update({doc["path"]: doc["file_sha256"] for doc in documents})
    for name in CURATION_FILES:
        path = root / "curation" / name
        result[path.relative_to(root).as_posix()] = sha256(path.read_bytes())
    paths = [root / "tools/build_catalog.py", *sorted((root / "tools/swse").glob("*.py"))]
    for path in paths:
        result[path.relative_to(root).as_posix()] = sha256(path.read_bytes())
    return [{"path": path, "sha256": digest} for path, digest in sorted(result.items())]


def build(root: Path, database: Path | None = None) -> dict:
    root = root.resolve()
    database = (database or root / DEFAULT_DB).resolve()
    if database.is_relative_to((root / "SWSE-Analysis").resolve()):
        raise ValueError("The retrieval database must be outside the source archive")
    protected = (".git", "tools", "curation", "catalog", "docs", "tests", "examples", "evaluation")
    if any(database.is_relative_to((root / folder).resolve()) for folder in protected):
        raise ValueError("Database destination is inside a protected repository directory")
    if database.suffix not in {".sqlite3", ".sqlite", ".db"}:
        raise ValueError("Database destination must have a SQLite extension")
    if database.exists():
        try:
            existing = sqlite3.connect("file:" + quote(database.as_posix(), safe="/") + "?mode=ro", uri=True)
            try:
                names = {row[0] for row in existing.execute("SELECT key FROM metadata")}
                if not {"snapshot_id", "fingerprints", "schema_version"} <= names:
                    raise ValueError("Destination is not an existing SWSE retrieval index")
            finally:
                existing.close()
        except (sqlite3.Error, ValueError) as error:
            raise ValueError("Refusing to overwrite an unrelated database/file") from error
    audit = build_catalog(root, root / "catalog")
    data = extract(root)
    for entity in data["entities"]:
        if "prerequisites_ast" in entity:
            validate_ast(entity["prerequisites_ast"])
    inputs = fingerprints(root, data["documents"], audit["inputs"])
    snapshot_id = sha256(dumps(inputs).encode())
    database.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".swse-", suffix=".tmp", dir=database.parent)
    os.close(fd)
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(SCHEMA)
            with connection:
                metadata = {"schema_version": SCHEMA_VERSION, "snapshot_id": snapshot_id,
                            "fingerprints": inputs, "policy": data["policy"], "audit": data["audit"]}
                connection.executemany("INSERT INTO metadata VALUES (?,?)", [(name, dumps(value)) for name, value in metadata.items()])
                connection.executemany("INSERT INTO documents VALUES (?,?,?)",
                                       [(doc["document_id"], doc["path"], dumps(doc)) for doc in data["documents"]])
                for entity in data["entities"]:
                    connection.execute("INSERT INTO entities VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                        entity["entity_id"], entity["name"], entity["name_key"], entity["kind"],
                        entity["parent_id"], entity["document_id"], entity["scope"], entity["rule_role"],
                        entity["review_status"], int("prerequisites_ast" in entity), dumps(entity)))
                    for source in dict.fromkeys(entity["declared_sources"]):
                        connection.execute("INSERT OR IGNORE INTO entity_sources VALUES (?,?,?)", (entity["entity_id"], source, key(source)))
                    for label in entity.get("class_access_hints", []):
                        connection.execute("INSERT OR IGNORE INTO class_hints VALUES (?,?,?)", (entity["entity_id"], key(label), label))
                    for field in entity.get("mechanic_fields", {}).get("time", []):
                        connection.execute("INSERT OR IGNORE INTO actions VALUES (?,?,?)", (entity["entity_id"], key(field["text"]), field["text"]))
                for alias in data["aliases"]:
                    connection.execute("INSERT OR REPLACE INTO aliases VALUES (?,?,?,?)", (
                        alias["key"], alias["entity_id"], alias.get("required_kind") or "", dumps(alias)))
                names = {entity["entity_id"]: entity["name"] for entity in data["entities"]}
                for chunk in data["chunks"]:
                    connection.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?,?)", (
                        chunk["chunk_id"], chunk["entity_id"], chunk["document_id"], chunk["rule_role"],
                        chunk["scope"], chunk["char_count"], dumps(chunk)))
                    connection.execute("INSERT INTO chunks_fts VALUES (?,?,?,?)", (
                        chunk["chunk_id"], names[chunk["entity_id"]], " / ".join(chunk["heading_path"]), chunk["text"]))
                    for source in dict.fromkeys(chunk["declared_sources"]):
                        connection.execute("INSERT OR IGNORE INTO chunk_sources VALUES (?,?)", (chunk["chunk_id"], key(source)))
                for relation in data["relationships"]:
                    connection.execute("INSERT INTO relationships VALUES (?,?,?,?)", (
                        relation["source"], relation["relation"], relation.get("target"), dumps(relation)))
                for record in data["workbook"]:
                    connection.execute("INSERT INTO workbook VALUES (?,?,?)", (record["sheet"], record["row"], dumps(record)))
                for concept in data["coverage"]:
                    for label in [concept["name"], *concept.get("aliases", [])]:
                        connection.execute("INSERT INTO coverage VALUES (?,?)", (key(label), dumps(concept)))
                from tools.build_catalog import json_lines
                for target in json_lines(root / "catalog/missing_wiki_targets.jsonl"):
                    connection.execute("INSERT INTO missing_targets VALUES (?,?,?,?)", (target["wiki_title"], key(target["wiki_title"]), target["host"], dumps(target)))
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite integrity check failed")
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise ValueError(f"SQLite foreign-key violations: {violations}")
        finally:
            connection.close()
        os.replace(temporary, database)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    report = {**data["audit"], "snapshot_id": snapshot_id,
              "database_schema_version": SCHEMA_VERSION, "database_bytes_at_build": database.stat().st_size,
              "rebuild_command": "python -m tools.swse build"}
    report_path = root / "catalog/retrieval_audit.json"
    temporary_report = report_path.with_suffix(".json.tmp")
    temporary_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_report.replace(report_path)
    queue_path = root / "catalog/coverage_review_queue.json"
    temporary_queue = queue_path.with_suffix(".json.tmp")
    temporary_queue.write_text(json.dumps({"schema_version": 1, "snapshot_id": snapshot_id,
        "scope": "Top 75 non-bibliographic/media document gaps by referring-document count; not proven missing rules.",
        "items": data["coverage_queue"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_queue.replace(queue_path)
    return report


def verify_inputs(root: Path, records: list[dict]):
    for record in records:
        path = within(root, record["path"])
        if not path.is_file() or sha256(path.read_bytes()) != record["sha256"]:
            raise ValueError(f"Stale retrieval index input: {record['path']}. Run python -m tools.swse build")
    expected = {record["path"] for record in records if record["path"].startswith(EXPORT_DIR.as_posix() + "/pages/") and record["path"].endswith(".md")}
    actual = {file.relative_to(root).as_posix() for file in (root / EXPORT_DIR / "pages").rglob("*.md")}
    if expected != actual:
        raise ValueError("Stale retrieval index Markdown inventory; rebuild the index")
    expected_code = {record["path"] for record in records if record["path"].startswith("tools/swse/")}
    actual_code = {file.relative_to(root).as_posix() for file in (root / "tools/swse").glob("*.py")}
    if expected_code != actual_code:
        raise ValueError("Stale retrieval implementation inventory; rebuild the index")
