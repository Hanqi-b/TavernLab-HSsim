"""Run account-separated local TavernLab-HSsim games in a browser.

The entry point binds to loopback and can keep one human-vs-agent match per
signed-in account through the standard-library HTTP server.
"""

from __future__ import annotations

import argparse

from .server import make_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None, help="seed the game RNG")
    parser.add_argument("--port", type=int, default=8765, help="local HTTP port")
    args = parser.parse_args(argv)

    # Game construction is delayed until an authenticated user starts a match.
    # Regular battles choose Radical or MCTS; Arena always uses MCTS.
    # Account sessions and each account's Arena/deck/match manager are
    # created lazily by the server.  Keep loopback binding until a separate
    # TLS-enabled LAN deployment path is added.
    server = make_server(host="127.0.0.1", port=args.port, seed=args.seed)
    print(f"Open http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
