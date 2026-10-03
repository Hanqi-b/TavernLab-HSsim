"""Temporary account-backed HTTP server for the history browser smoke test.

The test runner writes ``RESTART`` to stdin to retire all live account managers
while leaving the server and its temporary account files in place.  This
exercises the same archive restore path as a local server restart.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from fireplace.web_gui.account_game import AccountGameRegistry
from fireplace.web_gui.accounts import AccountStore
from fireplace.web_gui.server import make_server


def main() -> int:
    root = Path(sys.argv[1])
    root.mkdir(parents=True, exist_ok=True)
    accounts = AccountStore(root / "accounts.sqlite3")
    registry = AccountGameRegistry(
        accounts=accounts,
        data_root=root / "users",
        seed=31,
        legacy_decks=root / "missing-legacy-decks.json",
        legacy_arena=root / "missing-legacy-arena.json",
    )
    server = make_server(registry, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"READY http://127.0.0.1:{server.server_port}", flush=True)
    try:
        for command in sys.stdin:
            command = command.strip()
            if command == "RESTART":
                registry.close()
                print("RESTARTED", flush=True)
            elif command == "STOP":
                break
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        registry.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
