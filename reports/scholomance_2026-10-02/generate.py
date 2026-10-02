#!/usr/bin/env python3
"""Generate the launch-era Scholomance collectible behavior coverage map.

The inventory comes from the checked-in Scholomance card-data overlay.  Script
ownership is resolved through the running card database, while test references
are found by walking test ASTs so this report does not mistake a generic
database smoke test for a card behavior test.
"""

from __future__ import annotations

import argparse
import ast
import csv
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = Path(__file__).resolve().parent
COLLECTIBLE_COUNT = 135
METADATA_MODULES = {"tests/test_scholomance_data.py"}
METADATA_TEST_NAMES = {"test_every_shadow_card_has_a_runtime_script"}
TRANSFER_MODULE = "tests/test_scholomance_transfer_student.py"
CSV_FIELDS = (
    "card_id",
    "enUS_name",
    "profession",
    "script_file",
    "script_class",
    "behavior_test_references",
)


@dataclass(frozen=True)
class TestSpec:
    """A test function and its module-level assignment context."""

    path: str
    qualified_name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    assignments: dict[str, ast.AST]

    @property
    def base_nodeid(self) -> str:
        return f"{self.path}::{self.qualified_name}"


def _string_constants(node: ast.AST) -> set[str]:
    return {
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }


def _resolve_name(node: ast.AST, assignments: dict[str, ast.AST]) -> ast.AST:
    seen: set[str] = set()
    while isinstance(node, ast.Name) and node.id in assignments and node.id not in seen:
        seen.add(node.id)
        node = assignments[node.id]
    return node


def _module_assignments(tree: ast.Module) -> dict[str, ast.AST]:
    assignments: dict[str, ast.AST] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            if statement.value is not None:
                assignments[statement.target.id] = statement.value
    return assignments


def _is_parametrize_decorator(decorator: ast.AST) -> ast.Call | None:
    if not isinstance(decorator, ast.Call):
        return None
    function = decorator.func
    if isinstance(function, ast.Attribute) and function.attr == "parametrize":
        return decorator
    return None


def _parametrize_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    return [
        call
        for decorator in node.decorator_list
        if (call := _is_parametrize_decorator(decorator)) is not None
    ]


def _param_rows(call: ast.Call, assignments: dict[str, ast.AST]) -> list[ast.AST]:
    if len(call.args) < 2:
        return []
    values = _resolve_name(call.args[1], assignments)
    if isinstance(values, (ast.List, ast.Tuple, ast.Set)):
        return list(values.elts)
    return []


def _param_card_references(spec: TestSpec, card_ids: set[str]) -> set[str]:
    """Find card IDs in parametrization rows without inventing pytest IDs.

    A function-level nodeid runs every parameter row and remains valid when
    pytest changes the display ID for an enum, object, or generated value.
    """

    references: set[str] = set()
    for call in _parametrize_calls(spec.node):
        for row in _param_rows(call, spec.assignments):
            references.update(_string_constants(row) & card_ids)
    return references


class _TestCollector(ast.NodeVisitor):
    def __init__(self, path: str, assignments: dict[str, ast.AST]):
        self.path = path
        self.assignments = assignments
        self.class_stack: list[str] = []
        self.specs: list[TestSpec] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if node.name.startswith("test"):
            qualified = "::".join((*self.class_stack, node.name))
            self.specs.append(TestSpec(self.path, qualified, node, self.assignments))
        # Nested test functions are not collected by pytest, so do not recurse
        # into a test body and accidentally report a local helper as a test.

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function


def _test_specs(root: Path) -> list[TestSpec]:
    specs: list[TestSpec] = []
    tests_root = root / "tests"
    for path in sorted(tests_root.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(root).as_posix()
        collector = _TestCollector(rel, _module_assignments(tree))
        collector.visit(tree)
        specs.extend(collector.specs)
    return specs


def _behavior_references(root: Path, card_ids: set[str]) -> dict[str, set[str]]:
    references: dict[str, set[str]] = {card_id: set() for card_id in card_ids}
    transfer_refs: set[str] = set()
    for spec in _test_specs(root):
        test_name = spec.qualified_name.rsplit("::", 1)[-1]
        if (
            spec.path in METADATA_MODULES
            or test_name in METADATA_TEST_NAMES
            or "metadata" in spec.qualified_name.lower()
        ):
            continue
        nodeid = spec.base_nodeid
        param_card_refs = _param_card_references(spec, card_ids)
        body_hits = {
            card_id
            for statement in spec.node.body
            for card_id in (_string_constants(statement) & card_ids)
        }
        decorator_hits = _string_constants(spec.node) & card_ids
        if body_hits:
            for card_id in body_hits:
                references[card_id].add(nodeid)
        for card_id in param_card_refs:
            references[card_id].add(nodeid)
        # A card may occur only in a non-parametrize decorator (for example a
        # custom pytest id); retain that explicit test reference as well.
        for card_id in decorator_hits - param_card_refs:
            references[card_id].add(nodeid)
        if spec.path == TRANSFER_MODULE:
            transfer_refs.add(nodeid)

    # Transfer Student's board matrix is intentionally a module-level fixture:
    # every test in that behavior module exercises the generated variant.
    if "SCH_199" in references:
        references["SCH_199"].update(transfer_refs)
    return references


def _script_ast_index(root: Path) -> dict[tuple[str, str], ast.ClassDef]:
    index: dict[tuple[str, str], ast.ClassDef] = {}
    cards_root = root / "fireplace" / "cards"
    for path in sorted(cards_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                index[(rel, node.name)] = node
    return index


def _is_pass_only(node: ast.ClassDef) -> bool:
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr):
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            body.pop(0)
    return not body or all(isinstance(statement, ast.Pass) for statement in body)


def _script_location(root: Path, card_id: str, database, script_index):
    card = database[card_id]
    script_class = next(
        (candidate for candidate in card.scripts.__mro__[1:] if candidate.__name__ == card_id),
        None,
    )
    if script_class is None:
        raise AssertionError(f"{card_id} has no real Python script class")
    module = importlib.import_module(script_class.__module__)
    module_file = Path(module.__file__).resolve()
    script_file = module_file.relative_to(root).as_posix()
    ast_class = script_index.get((script_file, script_class.__name__))
    if ast_class is None:
        raise AssertionError(f"{card_id} script class is not in {script_file}")
    if _is_pass_only(ast_class):
        raise AssertionError(f"{card_id} has a pass-only script")
    return script_file, script_class.__name__


def _load_inventory() -> list:
    """Load collectible SCH records from the checked-in metadata overlay."""

    from fireplace.card_data import load_card_data

    cards, provenance = load_card_data(locale="enUS")
    collectible = [
        card
        for card in cards.values()
        if getattr(card.card_set, "name", None) == "SCHOLOMANCE" and card.collectible
    ]
    if provenance.overlay_collectible != COLLECTIBLE_COUNT:
        raise AssertionError(
            "checked-in Scholomance overlay reports "
            f"{provenance.overlay_collectible} collectibles, expected {COLLECTIBLE_COUNT}"
        )
    if len(collectible) != COLLECTIBLE_COUNT:
        raise AssertionError(
            f"expected {COLLECTIBLE_COUNT} collectibles, found {len(collectible)}"
        )
    return sorted(collectible, key=lambda card: card.id)


def build_rows(root: Path) -> list[dict[str, str]]:
    inventory = _load_inventory()
    card_ids = {card.id for card in inventory}
    references = _behavior_references(root, card_ids)

    from fireplace import cards as card_registry

    card_registry.db.initialize()
    script_index = _script_ast_index(root)
    rows: list[dict[str, str]] = []
    for card in inventory:
        card_id = card.id
        classes = list(getattr(card, "classes", ()) or ())
        if not classes:
            classes = [card.card_class]
        professions = "/".join(
            getattr(card_class, "name", str(card_class)) for card_class in classes
        )
        script_file, script_class = _script_location(
            root, card_id, card_registry.db, script_index
        )
        test_refs = sorted(references[card_id])
        if not test_refs:
            raise AssertionError(f"{card_id} has no behavior test reference")
        rows.append(
            {
                "card_id": card_id,
                "enUS_name": card.name,
                "profession": professions,
                "script_file": script_file,
                "script_class": script_class,
                "behavior_test_references": ";".join(test_refs),
            }
        )

    if len(rows) != COLLECTIBLE_COUNT or len({row["card_id"] for row in rows}) != COLLECTIBLE_COUNT:
        raise AssertionError("coverage report does not contain exactly 135 unique collectibles")
    if any(not row["script_file"] or not row["script_class"] for row in rows):
        raise AssertionError("coverage report contains a missing script location")
    if any(not row["behavior_test_references"] for row in rows):
        raise AssertionError("coverage report contains an unreferenced collectible")
    return rows


def write_report(rows: Iterable[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPORT_DIR / "card_coverage.csv")
    args = parser.parse_args(argv)
    rows = build_rows(ROOT)
    write_report(rows, args.output)
    print(f"wrote {len(rows)} rows to {args.output}")
    print(f"script files: {len({row['script_file'] for row in rows})}")
    print(f"behavior test references: {sum(bool(row['behavior_test_references']) for row in rows)}/{len(rows)}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
