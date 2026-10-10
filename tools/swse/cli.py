"""JSON CLI and read-only JSON-lines adapter for local agents."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from .repository import Repository
from .store import DEFAULT_DB, build

FILTERS = {"kind", "variant", "book", "tree", "class_name", "action", "reviewed_prerequisites",
           "include_homebrew", "include_optional", "include_unreviewed"}
METHOD_ARGS = {
    "resolve": {"name"}, "search": {"query", "limit", "offset"},
    "list": {"limit", "offset"}, "get": {"name", "max_chars", "expand"},
    "bundle": {"name", "max_chars"}, "chunk": {"chunk_id", "max_chars"},
    "coverage": {"name"}, "check": {"name", "character"}, "doctor": set(),
}
REQUIRED = {"resolve": {"name"}, "search": {"query"}, "get": {"name"}, "bundle": {"name"},
            "chunk": {"chunk_id"}, "coverage": {"name"}, "check": {"name", "character"}}


def dispatch(repo: Repository, method: str, params: dict) -> dict:
    if method not in METHOD_ARGS:
        raise ValueError("Unknown method; available: " + ", ".join(sorted(METHOD_ARGS)))
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    method_filters = FILTERS if method in {"list", "search"} else FILTERS - {"tree", "class_name", "action", "reviewed_prerequisites"}
    allowed = METHOD_ARGS[method] | (method_filters if method != "doctor" else set())
    if set(params) - allowed or REQUIRED.get(method, set()) - set(params):
        raise ValueError(f"Unexpected or missing parameters for {method}")
    for field in {"expand", "include_homebrew", "include_optional", "include_unreviewed", "reviewed_prerequisites"} & set(params):
        if type(params[field]) is not bool:
            raise ValueError(f"{field} must be boolean")
    if method == "list":
        return repo.list_entities(**params)
    if method == "bundle":
        return repo.get(expand=True, **params)
    return getattr(repo, method)(**params)


def serve(repo: Repository, source, destination):
    """Line-oriented requests, not a network server or an MCP implementation."""
    while True:
        line = source.readline(1_000_001)
        if not line:
            break
        oversized = len(line) > 1_000_000
        if oversized and not line.endswith("\n"):
            # Drain the rest of this request without storing an unbounded line.
            tail = source.readline(1_000_001)
            while tail and not tail.endswith("\n"):
                tail = source.readline(1_000_001)
        if not line.strip():
            continue
        id_ = None
        try:
            if oversized:
                raise ValueError("Request exceeds the one-million-character limit")
            request = json.loads(line)
            if not isinstance(request, dict) or set(request) - {"id", "method", "params"}:
                raise ValueError("Request must contain only id, method and params")
            candidate_id = request.get("id")
            if candidate_id is not None and type(candidate_id) not in {str, int}:
                raise ValueError("id must be a string, integer or null")
            id_ = candidate_id
            method = request.get("method")
            if not isinstance(method, str):
                raise ValueError("method must be a string")
            result = dispatch(repo, method, request.get("params", {}))
            response = {"id": id_, "result": result}
        except (ValueError, TypeError, KeyError, OSError, RecursionError, sqlite3.Error) as error:
            response = {"id": id_, "error": {"type": "InvalidRequestOrStaleIndex", "message": str(error)}}
        destination.write(json.dumps(response, ensure_ascii=False) + "\n")
        destination.flush()


def add_filters(parser):
    for field in ("kind", "book", "variant", "tree", "action"):
        parser.add_argument("--" + field)
    parser.add_argument("--class", dest="class_name")
    parser.add_argument("--reviewed-prerequisites", action="store_true", default=None)
    parser.add_argument("--include-homebrew", action="store_true", default=None)
    parser.add_argument("--include-optional", action="store_true", default=None)
    parser.add_argument("--reviewed-only", dest="include_unreviewed", action="store_false", default=None)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="Verify sources/curation and atomically rebuild SQLite FTS5")
    commands.add_parser("doctor", help="Verify fingerprints, SQLite integrity and coverage counts")
    commands.add_parser("serve", help="Read JSON-line requests from stdin until EOF; no ports/network")
    commands.add_parser("evaluate", help="Run golden local-evidence cases and write a small report")
    commands.add_parser("verify", help="Build, run regressions/evidence evaluation and verify integrity")
    for command in ("resolve", "get", "bundle", "coverage", "check", "search", "list", "chunk"):
        sub = commands.add_parser(command)
        if command == "search":
            sub.add_argument("query")
        elif command == "chunk":
            sub.add_argument("chunk_id")
        elif command != "list":
            sub.add_argument("name")
        if command in {"get", "bundle", "chunk"}:
            sub.add_argument("--max-chars", type=int)
        if command in {"list", "search"}:
            sub.add_argument("--limit", type=int, default=100 if command == "list" else 8)
            sub.add_argument("--offset", type=int, default=0)
        if command == "check":
            sub.add_argument("--character", type=Path, required=True)
        add_filters(sub)
    args = parser.parse_args(argv)
    root = args.repo.resolve()
    database = (root / args.database).resolve()
    try:
        if args.command == "verify":
            built = build(root, database)
            tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                                   cwd=root, stdout=sys.stderr, stderr=sys.stderr, check=False)
            if tests.returncode:
                print(json.dumps({"status": "regression_tests_failed", "test_exit_code": tests.returncode}))
                return 1
            with Repository(root, database) as repo:
                from .evaluation import run_evaluation
                evaluated = run_evaluation(repo, root)
                integrity = repo.doctor()
            result = {"status": "verified" if not evaluated["failed"] and integrity["status"] == "ok" else "failed",
                      "snapshot_id": built["snapshot_id"], "regression_test_exit_code": tests.returncode,
                      "golden_cases_passed": evaluated["passed"], "golden_cases_total": evaluated["case_count"],
                      "sqlite_integrity": integrity["sqlite_integrity"], "latency_ms": evaluated["latency_ms"]}
        elif args.command == "build":
            result = {"status": "built", **build(root, database)}
        else:
            with Repository(root, database) as repo:
                if args.command == "serve":
                    serve(repo, sys.stdin, sys.stdout)
                    return 0
                if args.command == "evaluate":
                    from .evaluation import run_evaluation
                    result = run_evaluation(repo, root)
                else:
                    params = {field: value for field, value in vars(args).items()
                              if field not in {"repo", "database", "command"} and value is not None}
                    if args.command == "check":
                        path = (root / params["character"]).resolve()
                        if path.stat().st_size > 1_000_000:
                            raise ValueError("Character JSON exceeds one million bytes")
                        params["character"] = json.loads(path.read_text(encoding="utf-8"))
                    result = dispatch(repo, args.command, params)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if (args.command == "evaluate" and result["failed"] or
                     args.command == "verify" and result["status"] != "verified") else 0
    except (ValueError, TypeError, KeyError, OSError, RecursionError, sqlite3.Error) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
