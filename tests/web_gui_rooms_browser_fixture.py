#!/usr/bin/env python3
"""Real authenticated HTTP boundary for the human room browser test.

The fixture deliberately does not emulate room state.  AccountGameRegistry
constructs its production RoomRegistry, and the browser talks to the same
account/session and room endpoints used by the LAN server.  The temporary
roots keep the acceptance run isolated from any local account data.
"""

from __future__ import annotations

import argparse
import json
import shutil
import signal
import tempfile
import threading
from pathlib import Path

from fireplace import cards
from fireplace.web_gui.account_game import AccountGameRegistry
from fireplace.web_gui.accounts import AccountStore
from fireplace.web_gui.server import make_server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    cards.db.initialize()
    data_root = Path(tempfile.mkdtemp(prefix="fireplace-room-browser-"))
    accounts = AccountStore(data_root / "accounts.sqlite3")
    registry = AccountGameRegistry(
        accounts=accounts,
        data_root=data_root / "users",
        seed=71,
        legacy_decks=data_root / "missing-legacy-decks.json",
        legacy_arena=data_root / "missing-legacy-arena.json",
    )
    server = make_server(registry, host="127.0.0.1", port=args.port)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stop.set())
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/"}), flush=True)
    try:
        stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        shutil.rmtree(data_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
