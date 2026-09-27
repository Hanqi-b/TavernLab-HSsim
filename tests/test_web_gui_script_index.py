"""Focused tests for the metadata-only Python card definition index."""

from __future__ import annotations

from pathlib import Path

from fireplace.web_gui.script_index import PythonScriptIndex


def test_index_reads_only_reexported_modules_and_does_not_execute_source(
    tmp_path: Path,
):
    card_set = tmp_path / "example"
    card_set.mkdir()
    (card_set / "__init__.py").write_text(
        "from .cards import *\n", encoding="utf-8"
    )
    (card_set / "cards.py").write_text(
        """
class CARD_A:
    play = ()

class CARD_B(BASE_CARD):
    pass

class EMPTY:
    pass

CARD_C = object()

def CARD_D():
    pass
""",
        encoding="utf-8",
    )
    # If this module were imported, the test would fail.  It is not reachable
    # through the package __init__ and therefore must not be scanned.
    (card_set / "ignored.py").write_text(
        "raise RuntimeError('source must never be executed')\n",
        encoding="utf-8",
    )

    index = PythonScriptIndex(tmp_path)
    assert index.has_definition("CARD_A")
    assert index.has_definition("CARD_B")
    assert index.has_definition("CARD_C")
    assert index.has_definition("CARD_D")
    assert not index.has_definition("EMPTY")
    assert not index.has_definition("IGNORED")

    # Loading is cached after the first query.
    assert index._ids is not None
    assert index.has_definition("CARD_A")
