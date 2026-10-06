#!/usr/bin/env python3
"""Smoke-test an installed TavernLab Debian package using only stdlib tools.

Run this from an unprivileged account in a clean Debian/Ubuntu install. The
server is started from /tmp with isolated HOME/XDG paths; no browser or card-art
endpoint is used.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener


EXPECTED_SOURCE_SHA256 = (
    "5dc890666bc2782a0f7dca5a1d04d23c9260f7090cca6f3001bd14002988e048"
)
EXPECTED_HEARTHSTONE = "9.21.1"
EXPECTED_HEARTHSTONE_DATA = "251952.1"
EXPECTED_PYTHON = (3, 10)
PASSWORD = "deb-smoke-password"


def require(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def installed_facts(python: Path, env: dict[str, str]) -> dict[str, object]:
    code = r"""
import importlib.metadata as metadata
import json
import sys
from pathlib import Path

import fireplace
from fireplace import card_data
from fireplace.replay_state import code_signature
from fireplace.web_gui import http_server

gui = Path(http_server.__file__).resolve().parent
site_packages = Path(fireplace.__file__).resolve().parent.parent
facts = {
    "python": [sys.version_info.major, sys.version_info.minor],
    "prefix": sys.prefix,
    "gui_dir": str(gui),
    "site_packages": str(site_packages),
    "card_defs": str(card_data.DEFAULT_CARD_DEFS_PATH),
    "scholomance_defs": str(card_data.SCHOLOMANCE_CARD_DEFS_PATH),
    "quality_report": str(site_packages / "reports" / "card_quality_full_2026-09-27" / "card_quality.csv"),
    "signature": code_signature(),
    "hearthstone": metadata.version("hearthstone"),
    "hearthstone_data": metadata.version("hearthstone-data"),
    "codex_distributions": sorted(
        distribution.metadata.get("Name", "")
        for distribution in metadata.distributions()
        if "codex" in distribution.metadata.get("Name", "").lower()
    ),
    "codex_files": sorted(
        str(path.relative_to(Path(sys.prefix)))
        for path in Path(sys.prefix).rglob("*")
        if path.is_file()
        and (
            path.name.lower() in {"codex", "codex-cli", "codex.exe", "codex-cli.exe"}
            or path.name.lower().endswith((".whl", ".tar.gz"))
            and "codex" in path.name.lower()
        )
    ),
}
print(json.dumps(facts, sort_keys=True))
"""
    result = subprocess.run(
        [str(python), "-I", "-c", code],
        cwd="/tmp",
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    require(
        result.returncode == 0,
        "installed Python metadata probe failed:\n"
        + (result.stderr or result.stdout).strip(),
    )
    try:
        facts = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"installed Python returned invalid metadata: {result.stdout!r}") from exc

    require(
        tuple(facts["python"]) == EXPECTED_PYTHON,
        f"expected Python {EXPECTED_PYTHON[0]}.{EXPECTED_PYTHON[1]}, got {facts['python']}",
    )
    require(
        facts["hearthstone"] == EXPECTED_HEARTHSTONE,
        f"unexpected hearthstone version: {facts['hearthstone']}",
    )
    require(
        facts["hearthstone_data"] == EXPECTED_HEARTHSTONE_DATA,
        f"unexpected hearthstone-data version: {facts['hearthstone_data']}",
    )
    signature = facts["signature"]
    require(
        signature.get("source_sha256") == EXPECTED_SOURCE_SHA256,
        "installed code signature mismatch: expected "
        f"{EXPECTED_SOURCE_SHA256}, got {signature.get('source_sha256')!r}",
    )
    require(
        signature.get("hearthstone_version") == EXPECTED_HEARTHSTONE
        and signature.get("hearthstone_data_version") == EXPECTED_HEARTHSTONE_DATA,
        f"code signature dependency versions are unexpected: {signature!r}",
    )
    require(
        facts.get("codex_distributions") == [],
        f"the package unexpectedly bundles a Codex distribution: {facts.get('codex_distributions')!r}",
    )
    require(
        facts.get("codex_files") == [],
        f"the private runtime unexpectedly bundles Codex files or archives: {facts.get('codex_files')!r}",
    )

    gui_dir = Path(str(facts["gui_dir"]))
    expected_resources = {
        "index.html": gui_dir / "index.html",
        "catalog_app.js": gui_dir / "catalog_app.js",
        "style-catalog.css": gui_dir / "style-catalog.css",
        "codex_connection.js": gui_dir / "codex_connection.js",
        "style-codex-connection.css": gui_dir / "style-codex-connection.css",
        "board-scene.webp": gui_dir / "board-scene.webp",
        "CardDefs.xml": Path(str(facts["card_defs"])),
        "Scholomance.xml": Path(str(facts["scholomance_defs"])),
        "card_quality.csv": Path(str(facts["quality_report"])),
    }
    for label, path in expected_resources.items():
        require(path.is_file() and path.stat().st_size > 0, f"missing installed resource {label}: {path}")
    print(
        "Installed runtime: Python 3.10, hearthstone 9.21.1, "
        "hearthstone-data 251952.1; source signature matches."
    )
    print("Installed data and UI resources are present.")
    return facts


def isolated_environment(root: Path) -> dict[str, str]:
    home = root / "home"
    paths = {
        "HOME": home,
        "XDG_STATE_HOME": root / "state",
        "XDG_CACHE_HOME": root / "cache",
        "XDG_CONFIG_HOME": root / "config",
        "XDG_DATA_HOME": root / "data",
        "XDG_RUNTIME_DIR": root / "runtime",
    }
    for path in paths.values():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)

    env = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "TAVERNLAB_ACCOUNT_STATE",
        "FIREPLACE_ACCOUNT_STATE",
        "TAVERNLAB_ACCOUNT_DATA_ROOT",
        "FIREPLACE_ACCOUNT_DATA_ROOT",
        "TAVERNLAB_DECK_STATE",
        "FIREPLACE_DECK_STATE",
        "TAVERNLAB_ARENA_STATE",
        "FIREPLACE_ARENA_STATE",
        "TAVERNLAB_MATCH_ARCHIVE_ROOT",
        "FIREPLACE_MATCH_ARCHIVE_ROOT",
        "FIREPLACE_ASSET_CACHE",
        "TAVERNLAB_CODEX_HOME",
        "TAVERNLAB_CODEX_BINARY",
        "TAVERNLAB_CODEX_MODEL",
        "TAVERNLAB_CODEX_TIMEOUT",
        "CODEX_HOME",
    ):
        env.pop(name, None)
    env.update({name: str(path) for name, path in paths.items()})
    # Keep the status probe deterministic even if the account running this
    # check has a Codex executable elsewhere on its normal PATH.  The probe is
    # passive and must not be allowed to discover or invoke that executable.
    empty_bin = root / "empty-bin"
    empty_bin.mkdir(mode=0o700)
    env["PATH"] = str(empty_bin)
    env["PYTHONNOUSERSITE"] = "1"
    return env


class LocalBrowser:
    def __init__(self) -> None:
        self.cookies = CookieJar()
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.cookies))

    def request(
        self,
        base: str,
        path: str,
        payload: object | None = None,
        *,
        origin: bool = False,
        timeout: float = 25.0,
    ) -> tuple[int, object, object]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers: dict[str, str] = {}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if origin:
            headers["Origin"] = base
        request = Request(base + path, data=data, headers=headers)
        try:
            response = self.opener.open(request, timeout=timeout)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
            if content_type.startswith("application/json"):
                parsed: object = json.loads(body.decode("utf-8"))
            else:
                parsed = body
            return response.getcode(), response.headers, parsed


def unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class RunningServer:
    def __init__(self, launcher: Path, env: dict[str, str], log_path: Path) -> None:
        self.launcher = launcher
        self.env = env
        self.log_path = log_path
        self.process: subprocess.Popen[bytes] | None = None

    def _log_tail(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")[-5000:]
        except OSError:
            return ""

    def start(self) -> str:
        port = unused_loopback_port()
        log = self.log_path.open("wb")
        try:
            self.process = subprocess.Popen(
                [str(self.launcher), "--port", str(port)],
                cwd="/tmp",
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log.close()
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 35.0
        while time.monotonic() < deadline:
            require(self.process is not None, "server process was not created")
            return_code = self.process.poll()
            if return_code is not None:
                raise RuntimeError(
                    f"installed server exited during startup ({return_code}):\n{self._log_tail()}"
                )
            try:
                status, _headers, body = LocalBrowser().request(base, "/", timeout=1.0)
                if status == 200 and isinstance(body, bytes) and body:
                    return base
            except (OSError, URLError, TimeoutError):
                pass
            time.sleep(0.1)
        raise RuntimeError(f"installed server did not become ready:\n{self._log_tail()}")

    def stop(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            process.send_signal(signal.SIGINT)
            process.wait(timeout=15.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)
            raise RuntimeError(
                f"installed server did not stop after SIGINT:\n{self._log_tail()}"
            )
        require(
            process.returncode == 0,
            f"installed server exited with status {process.returncode}:\n{self._log_tail()}",
        )


def check_http_resources(browser: LocalBrowser, base: str) -> None:
    for path, media in (
        ("/", "text/html"),
        ("/catalog_app.js", "text/javascript"),
        ("/style-catalog.css", "text/css"),
        ("/codex_connection.js", "text/javascript"),
        ("/style-codex-connection.css", "text/css"),
        ("/board-scene.webp", "image/webp"),
    ):
        status, headers, body = browser.request(base, path)
        require(status == 200, f"GET {path} returned HTTP {status}")
        require(
            str(headers.get("Content-Type", "")).startswith(media),
            f"GET {path} returned unexpected Content-Type {headers.get('Content-Type')!r}",
        )
        require(isinstance(body, bytes) and body, f"GET {path} returned an empty body")
        if path == "/board-scene.webp":
            require(body.startswith(b"RIFF") and body[8:12] == b"WEBP", "board-scene.webp has invalid WEBP bytes")
    print("Installed index, catalog/Codex JavaScript, CSS, and WEBP responses passed.")


def check_catalog(browser: LocalBrowser, base: str) -> None:
    status, _headers, payload = browser.request(
        base,
        "/api/catalog?set=SCHOLOMANCE&q=SCH_199&scope=all&page_size=10",
        timeout=30.0,
    )
    require(status == 200 and isinstance(payload, dict), f"Scholomance catalog query returned HTTP {status}: {payload!r}")
    items = payload.get("items")
    require(isinstance(items, list), "Scholomance catalog response has no item list")
    card = next((item for item in items if isinstance(item, dict) and item.get("id") == "SCH_199"), None)
    require(card is not None, "installed catalog did not return SCH_199")
    require(card.get("catalog_set") == "SCHOLOMANCE", f"SCH_199 has unexpected set data: {card!r}")
    require(card.get("quality_status") == "YELLOW", f"SCH_199 quality label is missing or wrong: {card!r}")
    status, _headers, detail = browser.request(base, "/api/catalog/cards/SCH_199?locale=enUS", timeout=30.0)
    require(status == 200 and isinstance(detail, dict), f"SCH_199 detail returned HTTP {status}: {detail!r}")
    require(detail.get("name") == "Transfer Student", f"SCH_199 English card data is unexpected: {detail!r}")
    require(detail.get("quality_status") == "YELLOW", f"SCH_199 detail quality label is wrong: {detail!r}")
    print("Installed catalog returned SCH_199 data with the YELLOW quality label.")


def check_codex_status(browser: LocalBrowser, base: str, state_home: Path) -> None:
    """Check the passive status route only with an authenticated game cookie."""

    status, _headers, payload = browser.request(base, "/api/codex/status", timeout=10.0)
    require(
        status == 200 and isinstance(payload, dict),
        f"authenticated Codex status probe returned HTTP {status}: {payload!r}",
    )
    require(payload.get("available") is False, f"clean status unexpectedly found Codex: {payload!r}")
    require(payload.get("connected") is False, f"clean status unexpectedly had a Codex account: {payload!r}")
    require(payload.get("login_pending") is False, f"passive status unexpectedly started login: {payload!r}")
    require(payload.get("shared_login") is True, "default connection did not select the existing CLI profile")
    require(
        not (state_home / "fireplace" / "codex").exists(),
        "passive Codex status probe created the dedicated Codex state directory",
    )
    require(
        not (state_home.parent / "home" / ".codex").exists(),
        "passive Codex status probe initialized the CLI auth directory",
    )
    print("Authenticated passive Codex status reported unavailable without starting a child.")


def check_account_restart(
    browser: LocalBrowser,
    first_base: str,
    first_server: RunningServer,
    second_server: RunningServer,
    state_home: Path,
) -> None:
    status, _headers, registration = browser.request(
        first_base,
        "/api/account/register",
        {"username": "deb-smoke", "password": PASSWORD},
        origin=True,
    )
    require(
        status == 200 and isinstance(registration, dict) and registration.get("authenticated") is True,
        f"account registration with Origin failed: HTTP {status}, {registration!r}",
    )
    account = registration.get("account")
    require(isinstance(account, dict) and isinstance(account.get("id"), str), f"registration returned no account identity: {registration!r}")
    account_id = account["id"]
    check_codex_status(browser, first_base, state_home)
    status, _headers, arena = browser.request(first_base, "/api/arena/state")
    require(
        status == 200 and isinstance(arena, dict)
        and arena.get("format_id") == "wild_2016_09_02"
        and (arena.get("max_wins"), arena.get("max_losses")) == (12, 3),
        f"new installed Arena did not default to the historical format: {arena!r}",
    )
    print("New installed Arena defaults to the 2016 historical format (12 wins/3 losses).")

    status, _headers, saved = browser.request(
        first_base,
        "/api/decks/save",
        {"name": "Deb package smoke", "hero_id": "HERO_08", "card_ids": []},
        origin=True,
    )
    require(status == 200 and isinstance(saved, dict), f"temporary deck save failed: HTTP {status}, {saved!r}")
    saved_id = saved.get("saved_id")
    decks = saved.get("decks")
    require(isinstance(saved_id, str) and isinstance(decks, list), f"deck save response was incomplete: {saved!r}")
    require(any(isinstance(deck, dict) and deck.get("id") == saved_id for deck in decks), "saved deck was absent from the immediate response")

    state_dir = state_home / "fireplace"
    account_db = state_dir / "accounts.sqlite3"
    deck_file = state_dir / "users" / account_id / "decks.json"
    require(account_db.is_file() and account_db.stat().st_size > 0, f"isolated account database was not created: {account_db}")
    require(deck_file.is_file() and deck_file.stat().st_size > 0, f"isolated saved-deck file was not created: {deck_file}")

    first_server.stop()
    second_base = second_server.start()
    status, _headers, session = browser.request(second_base, "/api/account/session")
    require(
        status == 200 and isinstance(session, dict)
        and session.get("authenticated") is True
        and session.get("account", {}).get("id") == account_id,
        f"login session did not survive server restart: HTTP {status}, {session!r}",
    )
    status, _headers, restored = browser.request(second_base, "/api/decks")
    require(status == 200 and isinstance(restored, dict), f"deck list after restart failed: HTTP {status}, {restored!r}")
    restored_decks = restored.get("decks")
    require(
        isinstance(restored_decks, list)
        and any(isinstance(deck, dict) and deck.get("id") == saved_id for deck in restored_decks),
        f"saved deck did not survive server restart: {restored!r}",
    )
    print("An isolated account, login session, and saved deck survived server restart.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", type=Path, default=Path("/usr/bin/tavernlab-web"))
    parser.add_argument("--python", type=Path, default=Path("/opt/venvs/tavernlab/bin/python"))
    args = parser.parse_args()

    require(hasattr(os, "geteuid") and os.geteuid() != 0, "run this smoke test as an unprivileged user")
    launcher = args.launcher.resolve()
    # Keep the venv executable path: resolving its symlink would select the
    # system interpreter and bypass the installed private site-packages.
    python = args.python.absolute()
    require(launcher.is_file() and os.access(launcher, os.X_OK), f"installed launcher is missing or not executable: {launcher}")
    require(python.is_file() and os.access(python, os.X_OK), f"installed Python is missing or not executable: {python}")

    with tempfile.TemporaryDirectory(prefix="tavernlab-deb-smoke-", dir="/tmp") as temporary:
        root = Path(temporary)
        env = isolated_environment(root)
        installed_facts(python, env)
        state_home = Path(env["XDG_STATE_HOME"])
        browser = LocalBrowser()
        first_server = RunningServer(launcher, env, root / "server-first.log")
        second_server = RunningServer(launcher, env, root / "server-restart.log")
        try:
            first_base = first_server.start()
            check_http_resources(browser, first_base)
            check_catalog(browser, first_base)
            check_account_restart(browser, first_base, first_server, second_server, state_home)
            second_server.stop()
        finally:
            first_server.stop()
            second_server.stop()
    print("Installed-package smoke test passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
