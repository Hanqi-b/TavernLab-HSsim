"""Narrow compatibility checks for replay logs across engine revisions.

Replay metadata carries more than one source digest: the Python/runtime and
installed card-data versions are part of the deterministic boundary too.
Legacy logs are accepted only for the two audited predecessor-to-current source
paths: the original predecessor and the current source immediately before the
RNG/card fix.  Every other signature field must be byte-for-byte equivalent to
the running process.

This module is intentionally absent from ``replay_state._REPLAY_SOURCE_FILES``.
Changing the compatibility policy therefore does not change the digest it is
used to validate, and adding the helper cannot create a self-hash cycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .replay_state import code_signature


# Generated from the original predecessor commit
# f2204ae6ab13f56902869db0b828950ce58a118f using an explicit PYTHONPATH and a
# separate subprocess.  This path covers archives created before the replay
# compatibility work landed.
PREDECESSOR_SOURCE_SHA256 = (
    "401bfd4796bbeac4f581e4f944de3d4f1ce2e079df775b0be6fa82429596a8d4"
)
# Generated from the source immediately before the powered_up/RNG fix.  This
# path covers archives made after the compatibility work but before that fix;
# the source change was audited to preserve replay behavior for these logs.
PRE_RNG_FIX_SOURCE_SHA256 = (
    "7e6ef8bc4fd6b4404c4972ca8e065545b5fbf23e15204cc19c494f5bb14e7b07"
)
# Pinned from the post-fix source tree.  Keep this explicit so an unexpected
# source change cannot silently widen the migration policy.
CURRENT_SOURCE_SHA256 = (
    "5dc890666bc2782a0f7dca5a1d04d23c9260f7090cca6f3001bd14002988e048"
)
ALLOWED_SOURCE_PAIRS = frozenset(
    {
        (PREDECESSOR_SOURCE_SHA256, CURRENT_SOURCE_SHA256),
        (PRE_RNG_FIX_SOURCE_SHA256, CURRENT_SOURCE_SHA256),
    }
)


def _exact_equal(left: object, right: object) -> bool:
    """Compare JSON-like signature values without bool/int coercion."""

    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        if not isinstance(right, Mapping) or set(left) != set(right):
            return False
        return all(_exact_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _exact_equal(item, other) for item, other in zip(left, right)
        )
    return left == right


def signature_is_compatible(
    recorded: object,
    current: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether recorded replay metadata is safe for this process.

    A current signature is accepted exactly.  Either audited predecessor
    signature is accepted only through ``ALLOWED_SOURCE_PAIRS``; all remaining
    top-level and nested metadata must exactly match the current signature.
    """

    if current is None:
        current = code_signature()
    if not isinstance(recorded, Mapping) or not isinstance(current, Mapping):
        return False
    if set(recorded) != set(current):
        return False
    recorded_source = recorded.get("source_sha256")
    current_source = current.get("source_sha256")
    if not isinstance(recorded_source, str) or not isinstance(current_source, str):
        return False
    for key in current:
        if key == "source_sha256":
            continue
        if not _exact_equal(recorded.get(key), current.get(key)):
            return False
    if recorded_source == current_source:
        return True
    return (recorded_source, current_source) in ALLOWED_SOURCE_PAIRS


def current_signature() -> dict[str, Any]:
    """Return a detached current signature for repaired archive metadata."""

    value = code_signature()
    if not isinstance(value, dict):  # pragma: no cover - defensive boundary
        raise TypeError("code_signature() must return a dictionary")
    return dict(value)


__all__ = [
    "ALLOWED_SOURCE_PAIRS",
    "CURRENT_SOURCE_SHA256",
    "PREDECESSOR_SOURCE_SHA256",
    "PRE_RNG_FIX_SOURCE_SHA256",
    "current_signature",
    "signature_is_compatible",
]
