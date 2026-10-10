"""Golden local evidence/policy evaluation; not a universal game-rules benchmark."""
from __future__ import annotations

import json
from pathlib import Path
import statistics
import time

from .cli import dispatch


def assert_expected(result: dict, expected: dict):
    for field in ("status", "result", "total"):
        if field in expected and result.get(field) != expected[field]:
            raise AssertionError(f"{field}: expected {expected[field]!r}, got {result.get(field)!r}")
    if "choices" in expected and len(result.get("choices", [])) != expected["choices"]:
        raise AssertionError("Wrong ambiguity-choice count")
    if "entity_id" in expected and result.get("entity", {}).get("entity_id") != expected["entity_id"]:
        raise AssertionError("Wrong entity selected")
    text = "\n".join(chunk["text"] for chunk in result.get("evidence", []))
    if "contains" in expected and expected["contains"] not in text:
        raise AssertionError(f"Expected evidence absent: {expected['contains']}")
    if "forbidden" in expected and expected["forbidden"] in text:
        raise AssertionError(f"Forbidden variant/optional evidence leaked: {expected['forbidden']}")
    roles = {chunk["rule_role"] for chunk in result.get("evidence", [])}
    if expected.get("forbidden_role") in roles:
        raise AssertionError("Forbidden role leaked")
    if "required_role" in expected and expected["required_role"] not in roles:
        raise AssertionError("Required role absent")
    if "forbidden_item" in expected and any(item["name"] == expected["forbidden_item"] for item in result.get("items", [])):
        raise AssertionError("Forbidden enumerated entity leaked")
    if "hit_entity" in expected:
        top = result.get("items", [])[:expected.get("within", 5)]
        matches = [item for item in top if item["entity_id"] == expected["hit_entity"] and
                   ("hit_role" not in expected or item["rule_role"] == expected["hit_role"]) and
                   ("hit_contains" not in expected or expected["hit_contains"] in item["excerpt"])]
        if not matches:
            raise AssertionError("Required evidence not retrieved within the top-k bound")


def run_evaluation(repo, root: Path, save: bool = True) -> dict:
    specification = json.loads((root / "evaluation/cases.json").read_text(encoding="utf-8"))
    if specification.get("schema_version") != 1:
        raise ValueError("Unsupported evaluation schema")
    results, timings = [], []
    for case in specification["cases"]:
        start = time.perf_counter()
        try:
            result = dispatch(repo, case["method"], case["params"])
            assert_expected(result, case["expect"])
            state, error = "passed", None
        except (AssertionError, ValueError, KeyError, TypeError) as failure:
            state, error = "failed", str(failure)
        elapsed = (time.perf_counter() - start) * 1000
        timings.append(elapsed)
        results.append({"id": case["id"], "status": state, "error": error,
                        "elapsed_ms": round(elapsed, 3)})
    passed = sum(result["status"] == "passed" for result in results)
    report = {"schema_version": 1, "snapshot_id": repo.metadata["snapshot_id"],
              "scope": specification["scope"], "case_count": len(results), "passed": passed,
              "failed": len(results) - passed, "cases": results,
              "latency_ms": {"median": round(statistics.median(timings), 3),
                             "p95_floor_rank": round(sorted(timings)[int((len(timings) - 1) * .95)], 3),
                             "maximum": round(max(timings), 3)},
              "latency_scope": "Local operation including per-request source/code/curation fingerprint checks; excludes initial database build and Repository construction.",
              "limits": ["Passing local evidence fixtures does not establish primary-source correctness or complete semantic coverage.",
                         "Not a benchmark against other retrieval systems, embeddings or full character/rules engines."]}
    if save:
        path = root / "catalog/evaluation_report.json"
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
    return report
