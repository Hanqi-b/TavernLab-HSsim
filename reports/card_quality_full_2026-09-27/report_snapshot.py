"""Fingerprint executable card rules and XML for report freshness checks."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def source_files():
    paths = [ROOT / "fireplace/cards/CardDefs.xml"]
    paths.extend((ROOT / "fireplace").glob("*.py"))
    paths.extend((ROOT / "fireplace/cards").rglob("*.py"))
    paths.extend((ROOT / "fireplace/dsl").rglob("*.py"))
    return sorted(set(paths))


def source_snapshot():
    digest = hashlib.sha256()
    files = source_files()
    for path in files:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), len(files), max(path.stat().st_mtime_ns for path in files)
