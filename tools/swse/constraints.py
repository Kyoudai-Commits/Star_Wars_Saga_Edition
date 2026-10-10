"""Reviewed prerequisite expressions evaluated with three-valued logic.

Character facts are explicit inputs. This is not a progression, class-access,
feat-acquisition, equipment, combat or whole-character legality validator.
"""
from __future__ import annotations

from .text import key

OPS = {"all", "any", "gte", "equals", "has", "has_talent", "count_talents", "fact"}
INVENTORIES = {"feats", "trained_skills", "force_powers", "droid_systems", "talents"}
NUMBERS = {"level", "base_attack_bonus", "force_talent_count", "force_technique_count"}


def validate_ast(node: dict, depth: int = 0):
    if depth > 20 or not isinstance(node, dict) or node.get("op") not in OPS:
        raise ValueError("Unsupported or excessively nested prerequisite expression")
    op = node["op"]
    if op in {"all", "any"}:
        if not isinstance(node.get("args"), list) or op == "any" and not node["args"]:
            raise ValueError("Logical expressions require an argument list; OR cannot be empty")
        for child in node["args"]:
            validate_ast(child, depth + 1)
    elif op == "gte":
        if node.get("field") not in NUMBERS or type(node.get("value")) is not int or node["value"] < 0:
            raise ValueError("Invalid numeric prerequisite")
    elif op == "has":
        if node.get("field") not in INVENTORIES or not isinstance(node.get("value"), str):
            raise ValueError("Invalid inventory prerequisite")
    elif op == "equals":
        if node.get("field") != "species" or not isinstance(node.get("value"), str):
            raise ValueError("Unsupported equality prerequisite")
    elif op == "fact":
        if not isinstance(node.get("name"), str) or not node["name"]:
            raise ValueError("Fact name must be a nonempty string")
    elif op == "has_talent":
        if not isinstance(node.get("name"), str) or node.get("tree") is not None and not isinstance(node["tree"], str):
            raise ValueError("Invalid talent prerequisite")
    elif op == "count_talents":
        if type(node.get("at_least")) is not int or node["at_least"] <= 0 or not (
                isinstance(node.get("trees"), list) and node["trees"] and
                all(isinstance(tree, str) for tree in node["trees"])):
            raise ValueError("Invalid talent-count prerequisite")


def validate_character(character: dict):
    if not isinstance(character, dict):
        raise ValueError("Character must be a JSON object")
    allowed = NUMBERS | INVENTORIES | {"species", "facts", "inventories_complete"}
    unknown = set(character) - allowed
    if unknown:
        raise ValueError(f"Unknown character fields (avoid silently ignored facts): {sorted(unknown)}")
    for field in NUMBERS:
        if field in character and (type(character[field]) is not int or character[field] < 0):
            raise ValueError(f"{field} must be a nonnegative integer, not a boolean")
    for field in INVENTORIES:
        if field not in character:
            continue
        values = character[field]
        if not isinstance(values, list) or len(values) > 1000:
            raise ValueError(f"{field} must be a list of at most 1000 explicit features")
        for value in values:
            if field == "talents" and isinstance(value, dict):
                if not value.get("entity_id") and not (isinstance(value.get("name"), str) and value["name"]):
                    raise ValueError("Talent objects require entity_id or name")
                if set(value) - {"entity_id", "name", "tree"}:
                    raise ValueError("Unknown talent-object fields")
                if any(not isinstance(v, str) for v in value.values()):
                    raise ValueError("Talent object values must be strings")
            elif not isinstance(value, str) or not value:
                raise ValueError(f"{field} values must be nonempty strings")
    if "species" in character and not isinstance(character["species"], str):
        raise ValueError("species must be a string")
    if "facts" in character and (not isinstance(character["facts"], dict) or
                                any(not isinstance(name, str) or type(value) is not bool
                                    for name, value in character["facts"].items())):
        raise ValueError("facts must map explicit fact names to booleans")
    completeness = character.get("inventories_complete", {})
    if not isinstance(completeness, dict) or set(completeness) - INVENTORIES or any(
            type(value) is not bool for value in completeness.values()):
        raise ValueError("inventories_complete must map inventory names to booleans")


def evaluate(ast: dict, character: dict, talent_resolver) -> dict:
    """Known failures dominate AND; known successes dominate OR; otherwise unknown.

    Supplied inventory lists are complete unless marked false. Missing fields
    are unknown. Duplicate talent IDs are never counted twice. An unresolved
    supplied talent makes an insufficient count unknown, not an invented count.
    """
    validate_ast(ast)
    validate_character(character)
    cache = None

    def talents():
        nonlocal cache
        if cache is None:
            known, unresolved = {}, []
            for value in character.get("talents", []):
                result = talent_resolver(value)
                if result is None:
                    unresolved.append(value)
                else:
                    known[result["entity_id"]] = result
            cache = (list(known.values()), unresolved)
        return cache

    def complete(field):
        return character.get("inventories_complete", {}).get(field, True)

    def visit(node):
        op = node["op"]
        result = {"condition": node, "result": "unknown"}
        if op in {"all", "any"}:
            children = [visit(child) for child in node["args"]]
            values = [child["result"] for child in children]
            if op == "all":
                state = "not_met" if "not_met" in values else "unknown" if "unknown" in values else "met"
            else:
                state = "met" if "met" in values else "unknown" if "unknown" in values else "not_met"
            return {**result, "result": state, "children": children}
        if op == "fact":
            value = character.get("facts", {}).get(node["name"])
            return {**result, "result": "unknown" if value is None else "met" if value else "not_met",
                    "reason": "Explicit special-requirement fact" if value is not None else "Special fact not supplied"}
        if op == "gte":
            value = character.get(node["field"])
            return {**result, "result": "unknown" if value is None else "met" if value >= node["value"] else "not_met",
                    "actual": value, "reason": "Explicit numeric fact; no progression inferred"}
        if op == "equals":
            value = character.get(node["field"])
            return {**result, "result": "unknown" if value is None else "met" if key(value) == key(node["value"]) else "not_met",
                    "actual": value}
        if op == "has" and node["field"] != "talents":
            field = node["field"]
            if field not in character:
                return {**result, "reason": f"{field} inventory not supplied"}
            present = key(node["value"]) in {key(value) for value in character[field]}
            return {**result, "result": "met" if present else "not_met" if complete(field) else "unknown",
                    "reason": "Explicit inventory membership" if present else "Absent from complete inventory" if complete(field) else "Inventory is partial"}
        if "talents" not in character:
            return {**result, "reason": "Talent inventory not supplied"}
        known, unresolved = talents()
        if op in {"has_talent", "has"}:
            name = node.get("name", node.get("value"))
            present = any(key(talent["name"]) == key(name) and
                          ("tree" not in node or key(talent["tree_name"]) == key(node["tree"])) for talent in known)
            state = "met" if present else "unknown" if unresolved or not complete("talents") else "not_met"
            return {**result, "result": state, "unresolved_talents": unresolved}
        trees = {key(tree) for tree in node["trees"]}
        count = sum(key(talent["tree_name"]) in trees for talent in known)
        state = "met" if count >= node["at_least"] else "unknown" if unresolved or not complete("talents") else "not_met"
        return {**result, "result": state, "count": count, "unresolved_talents": unresolved,
                "reason": "Counted distinct locally mapped talent identities; no duplicates or guessed trees"}

    return visit(ast)
