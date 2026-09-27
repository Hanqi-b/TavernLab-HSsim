"""Static index of card definitions re-exported by the card set packages.

The normal card database imports every card module and evaluates the game DSL.
The web catalog only needs to answer whether a card has a Python definition,
so this module deliberately reads source files with :mod:`ast` instead.  The
index is lazy and contains only names defined by modules imported from a
``fireplace.cards.<set>.__init__`` file.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from threading import RLock


_CARD_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _assignment_names(target: ast.AST) -> set[str]:
    """Return simple names introduced by one assignment target."""

    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.List, ast.Tuple)):
        names: set[str] = set()
        for element in target.elts:
            names.update(_assignment_names(element))
        return names
    return set()


def _has_meaningful_class_body(node: ast.ClassDef) -> bool:
    """Whether a class contributes a definition of its own.

    Empty subclasses still inherit the card behavior from their base class,
    which is why a class with bases counts even when its body is ``pass``.
    A bare ``class CARD: pass`` has no runtime script and is intentionally
    omitted.  This also avoids advertising the few placeholder classes in the
    adventure data as implemented effects.
    """

    if node.bases:
        return True
    for statement in node.body:
        if isinstance(statement, ast.Pass):
            continue
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        return True
    return False


def _defined_names(module_path: Path) -> set[str]:
    """Extract top-level class, function, and assignment names."""

    try:
        tree = ast.parse(
            module_path.read_text(encoding="utf-8"), filename=str(module_path)
        )
    except (OSError, SyntaxError, UnicodeError):
        # A broken optional card module must not make the read-only catalog
        # unavailable.  It simply contributes no statically known scripts.
        return set()

    names: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.ClassDef):
            if _has_meaningful_class_body(statement):
                names.add(statement.name)
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(statement.name)
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                names.update(_assignment_names(target))
        elif isinstance(statement, ast.AnnAssign):
            names.update(_assignment_names(statement.target))
    return {name for name in names if _CARD_ID_RE.fullmatch(name)}


def _reexported_modules(package_init: Path) -> tuple[Path, ...]:
    """Resolve local modules imported by one card set's ``__init__.py``."""

    try:
        tree = ast.parse(
            package_init.read_text(encoding="utf-8"), filename=str(package_init)
        )
    except (OSError, SyntaxError, UnicodeError):
        return ()

    modules: set[Path] = set()
    for statement in tree.body:
        if not isinstance(statement, ast.ImportFrom):
            continue
        # ``from .mage import *`` is the card-set convention.  Imports from
        # ``..utils`` and other parent packages are deliberately excluded.
        if statement.level != 1 or not statement.module:
            continue
        relative = Path(*statement.module.split("."))
        module_path = package_init.parent / relative.with_suffix(".py")
        if module_path.is_file():
            modules.add(module_path)
            continue
        package_path = package_init.parent / relative / "__init__.py"
        if package_path.is_file():
            modules.add(package_path)
    return tuple(sorted(modules))


class PythonScriptIndex:
    """Lazily index statically declared card definitions below ``cards_root``."""

    def __init__(self, cards_root: Path):
        self.cards_root = Path(cards_root)
        self._lock = RLock()
        self._ids: frozenset[str] | None = None

    def _load(self) -> frozenset[str]:
        current = self._ids
        if current is not None:
            return current
        with self._lock:
            current = self._ids
            if current is not None:
                return current
            ids: set[str] = set()
            if self.cards_root.is_dir():
                for package_init in sorted(self.cards_root.glob("*/__init__.py")):
                    for module_path in _reexported_modules(package_init):
                        ids.update(_defined_names(module_path))
            current = frozenset(ids)
            self._ids = current
            return current

    def has_definition(self, card_id: str) -> bool:
        """Return whether ``card_id`` has a statically visible definition."""

        return card_id in self._load()


__all__ = ["PythonScriptIndex"]
