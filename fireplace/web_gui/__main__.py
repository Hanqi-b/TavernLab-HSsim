"""Run local and opt-in LAN TavernLab-HSsim battles in a browser.

Choose human versus Codex, Codex versus MCTS, Codex versus Codex, or a
two-player human room. The server binds to loopback by default; LAN access
requires an explicit host allowlist.
"""

from __future__ import annotations

import argparse

from .server import make_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None, help="seed the game RNG")
    parser.add_argument("--port", type=int, default=8765, help="local HTTP port")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (loopback by default)")
    parser.add_argument(
        "--allow-host", action="append", default=[],
        help="exact Host name or address accepted for LAN requests (repeatable)",
    )
    parser.add_argument(
        "--advertised-host", default=None,
        help="the public Host name printed for a LAN deployment",
    )
    parser.add_argument("--tls-cert", default=None, help="TLS certificate PEM path")
    parser.add_argument("--tls-key", default=None, help="TLS private key PEM path")
    args = parser.parse_args(argv)

    # Game construction is delayed until an authenticated user starts a match.
    # Regular battles also support Codex; Arena always uses MCTS.
    # Account sessions and each account's Arena/deck/match manager are
    # created lazily by the server.  LAN access remains opt-in through an
    # exact allow-list and can be paired with TLS.
    server = make_server(
        host=args.host,
        port=args.port,
        seed=args.seed,
        allowed_hosts=args.allow_host or None,
        advertised_host=args.advertised_host,
        tls_cert=args.tls_cert,
        tls_key=args.tls_key,
    )
    print(
        f"Open {server.scheme}://{server.advertised_host}:{server.server_port}/",
        flush=True,
    )
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
