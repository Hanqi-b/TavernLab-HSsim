"""Opt-in LAN binding checks for the standard-library Web GUI server."""

from __future__ import annotations

import json
import shutil
import socket
import ssl
import subprocess
import threading
from http.client import HTTPConnection
from http.client import HTTPSConnection

import pytest

from fireplace.web_gui.http_server import make_server
from fireplace.web_gui.server import WebGameManager


def _request(port: int, method: str, path: str, *, host: str, origin: str | None = None, body=None):
    connection = HTTPConnection("127.0.0.1", port, timeout=20)
    headers = {"Host": host}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if origin is not None:
        headers["Origin"] = origin
    connection.request(method, path, body=data, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response.status, json.loads(raw)


def test_nonlocal_bind_requires_an_exact_allow_list():
    game = WebGameManager(seed=3)
    with pytest.raises(ValueError, match="loopback"):
        make_server(game, host="0.0.0.0", port=0)
    game.close()

    game = WebGameManager(seed=3)
    with pytest.raises(ValueError, match="wildcard"):
        make_server(game, host="0.0.0.0", port=0, allowed_hosts=["*"])
    game.close()


def test_allowed_lan_host_is_exact_and_origin_is_scheme_bound():
    game = WebGameManager(seed=3)
    server = make_server(
        game,
        host="0.0.0.0",
        port=0,
        allowed_hosts=["lan.example"],
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        allowed = f"lan.example:{port}"
        status, state = _request(port, "GET", "/api/state", host=allowed)
        assert status == 200 and state["mode"] == "lobby"

        status, rejected = _request(
            port, "GET", "/api/state", host=f"other.example:{port}"
        )
        assert status == 403 and rejected["error"]

        body = {"nickname": "LAN", "locale": "enUS"}
        status, rejected = _request(
            port,
            "POST",
            "/api/start",
            host=allowed,
            origin=f"http://other.example:{port}",
            body=body,
        )
        assert status == 403 and rejected["error"]

        status, state = _request(
            port,
            "POST",
            "/api/start",
            host=allowed,
            origin=f"http://{allowed}",
            body=body,
        )
        assert status == 200 and state["mode"] == "match"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_https_pair_scheme_origin_and_secure_cookie(tmp_path):
    if shutil.which("openssl") is None:
        pytest.skip("openssl is required for the TLS integration check")
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert), "-days", "1",
            "-subj", "/CN=127.0.0.1",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    from fireplace.web_gui.account_game import AccountGameRegistry
    from fireplace.web_gui.accounts import AccountStore

    game = WebGameManager(seed=4)
    with pytest.raises(ValueError, match="provided together"):
        make_server(game, host="127.0.0.1", port=0, tls_cert=cert)
    game.close()

    accounts = AccountStore(tmp_path / "accounts.sqlite3")
    registry = AccountGameRegistry(
        accounts=accounts,
        data_root=tmp_path / "users",
        seed=4,
        legacy_decks=tmp_path / "missing-decks.json",
        legacy_arena=tmp_path / "missing-arena.json",
    )
    server = make_server(
        registry,
        host="127.0.0.1",
        port=0,
        tls_cert=cert,
        tls_key=key,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    context = ssl._create_unverified_context()
    idle_socket = None
    try:
        port = server.server_port
        host = f"127.0.0.1:{port}"
        # A raw TCP peer that never sends a ClientHello must not block the
        # listening loop while a normal HTTPS request is served.
        idle_socket = socket.create_connection(("127.0.0.1", port), timeout=5)
        connection = HTTPSConnection("127.0.0.1", port, timeout=20, context=context)
        body = json.dumps({"username": "TlsUser", "password": "local-password-123"}).encode()
        connection.request(
            "POST", "/api/account/register", body=body,
            headers={"Host": host, "Origin": f"https://{host}", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        cookie = response.getheader("Set-Cookie", "")
        assert "Secure" in cookie and "HttpOnly" in cookie
        connection.close()

        connection = HTTPSConnection("127.0.0.1", port, timeout=20, context=context)
        connection.request("GET", "/api/state", headers={"Host": host})
        response = connection.getresponse()
        assert response.status == 401
        response.read()
        connection.close()

        connection = HTTPSConnection("127.0.0.1", port, timeout=20, context=context)
        connection.request(
            "POST", "/api/account/login", body=body,
            headers={"Host": host, "Origin": f"http://{host}", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 403
        response.read()
        connection.close()

        connection = HTTPSConnection("127.0.0.1", port, timeout=20, context=context)
        connection.request("GET", "/api/account/session", headers={"Host": f"attacker:{port}"})
        response = connection.getresponse()
        assert response.status == 403
        response.read()
        connection.close()
    finally:
        if idle_socket is not None:
            idle_socket.close()
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()
