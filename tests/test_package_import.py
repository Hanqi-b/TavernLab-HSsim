"""Package startup must not require setuptools at runtime."""

import subprocess
import sys
from pathlib import Path

import fireplace


def test_import_without_pkg_resources():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['pkg_resources'] = None; "
            "from importlib.metadata import version; import fireplace; "
            "assert fireplace.__version__ == version('fireplace')",
        ],
        cwd=Path(fireplace.__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
