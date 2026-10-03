"""Standard-library HTTP adapter for the local Fireplace browser UI."""

from __future__ import annotations

import ipaddress
import json
import sqlite3
from http.cookies import SimpleCookie
from concurrent.futures import TimeoutError as FutureTimeout
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .assets import AssetService
from .catalog import CardCatalog
from .contracts import ASSET_PENDING, WebActionError, WebBackend, WebLifecycleError


_JSON_ERROR = object()
_STATIC_MIME_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "catalog.html": "text/html; charset=utf-8",
    "arena.html": "text/html; charset=utf-8",
    "collection.html": "text/html; charset=utf-8",
    "account.html": "text/html; charset=utf-8",
    "history.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "catalog_app.js": "text/javascript; charset=utf-8",
    "card_face.js": "text/javascript; charset=utf-8",
    "arena_app.js": "text/javascript; charset=utf-8",
    "collection_app.js": "text/javascript; charset=utf-8",
    "account_app.js": "text/javascript; charset=utf-8",
    "account_session.js": "text/javascript; charset=utf-8",
    "history_app.js": "text/javascript; charset=utf-8",
    "action_model.js": "text/javascript; charset=utf-8",
    "i18n.js": "text/javascript; charset=utf-8",
    "status_view.js": "text/javascript; charset=utf-8",
    "modifier_view.js": "text/javascript; charset=utf-8",
    "gui_localization.js": "text/javascript; charset=utf-8",
    "gui_state.js": "text/javascript; charset=utf-8",
    "gui_core.js": "text/javascript; charset=utf-8",
    "gui_utils.js": "text/javascript; charset=utf-8",
    "gui_sync.js": "text/javascript; charset=utf-8",
    "gui_feedback.js": "text/javascript; charset=utf-8",
    "gui_board.js": "text/javascript; charset=utf-8",
    "gui_cards.js": "text/javascript; charset=utf-8",
    "gui_decisions.js": "text/javascript; charset=utf-8",
    "gui_modal.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "style-catalog.css": "text/css; charset=utf-8",
    "style-arena.css": "text/css; charset=utf-8",
    "style-collection.css": "text/css; charset=utf-8",
    "style-card-face.css": "text/css; charset=utf-8",
    "style-account.css": "text/css; charset=utf-8",
    "style-history.css": "text/css; charset=utf-8",
    "style-base.css": "text/css; charset=utf-8",
    "style-board.css": "text/css; charset=utf-8",
    "style-cards.css": "text/css; charset=utf-8",
    "style-hand.css": "text/css; charset=utf-8",
    "style-presentation.css": "text/css; charset=utf-8",
    "gui_presentation.js": "text/javascript; charset=utf-8",
    "gui_effects.js": "text/javascript; charset=utf-8",
    "gui_hand_drag.js": "text/javascript; charset=utf-8",
    "style-decision.css": "text/css; charset=utf-8",
    "style-support.css": "text/css; charset=utf-8",
    "style-responsive.css": "text/css; charset=utf-8",
    "board-scene.webp": "image/webp",
}
_MAX_REQUEST_BYTES = 1 << 20
_SESSION_COOKIE = "fireplace_session"
_SESSION_AGE = 7 * 24 * 60 * 60


def _static_mime_type(name: str) -> str | None:
    """Return a MIME type for one safe file directly below the UI root."""

    if name != Path(name).name or name in {".", ".."}:
        return None
    return _STATIC_MIME_TYPES.get(name)


class WebGameHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying one complete :class:`WebBackend` instance."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        web_game: WebBackend,
        *,
        catalog: CardCatalog | None = None,
        catalog_assets: AssetService | None = None,
    ):
        if server_address[0] not in {"127.0.0.1", "localhost"}:
            raise ValueError("web GUI must bind to loopback")
        self.web_game = web_game
        self.account_games = web_game if hasattr(web_game, "for_account") and hasattr(web_game, "accounts") else None
        self.catalog = catalog if catalog is not None else getattr(web_game, "catalog", None) or CardCatalog()
        self.catalog_assets = catalog_assets if catalog_assets is not None else AssetService()
        super().__init__(server_address, _RequestHandler)

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            try:
                self.catalog_assets.close()
            finally:
                self.web_game.close()


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


class _RequestHandler(BaseHTTPRequestHandler):
    """HTTP adapter with no Fireplace entity traversal."""

    server_version = "FireplaceWeb/1.0"

    @property
    def web_game(self) -> WebBackend:
        return getattr(self, "_request_game", None) or self.server.web_game  # type: ignore[attr-defined]

    @property
    def account_games(self):
        return self.server.account_games  # type: ignore[attr-defined]

    @property
    def catalog(self) -> CardCatalog:
        return self.server.catalog  # type: ignore[attr-defined]

    @property
    def catalog_assets(self) -> AssetService:
        return self.server.catalog_assets  # type: ignore[attr-defined]

    def _send_bytes(
        self,
        status: int,
        data: bytes,
        content_type: str,
        *,
        placeholder: bool | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if placeholder is not None:
            self.send_header("X-Asset-Placeholder", "1" if placeholder else "0")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: int, payload: object, *, headers: dict[str, str] | None = None) -> None:
        try:
            data = _json_bytes(payload)
        except (TypeError, ValueError):
            status = int(HTTPStatus.INTERNAL_SERVER_ERROR)
            data = _json_bytes({"error": "server produced a non-JSON response"})
        self._send_bytes(status, data, "application/json; charset=utf-8", headers=headers)

    def _session_token(self) -> str | None:
        raw = self.headers.get("Cookie", "")
        if len(raw) > 4096:
            return None
        try:
            cookies = SimpleCookie()
            cookies.load(raw)
            item = cookies.get(_SESSION_COOKIE)
            return item.value if item is not None else None
        except Exception:
            return None

    @staticmethod
    def _account_payload(account: object) -> dict[str, str]:
        if isinstance(account, dict):
            return {"id": str(account["id"]), "username": str(account["username"])}
        return {"id": str(account.id), "username": str(account.username)}

    def _current_account(self):
        if self.account_games is None:
            return None
        token = self._session_token()
        return self.account_games.accounts.authenticate(token) if token else None

    def _require_account(self) -> bool:
        if self.account_games is None:
            return True
        try:
            account = self._current_account()
        except (OSError, sqlite3.Error):
            self._send_json(int(HTTPStatus.SERVICE_UNAVAILABLE), {"error": "account storage is unavailable"})
            return False
        except ValueError as exc:
            self._send_json(int(HTTPStatus.CONFLICT), {"error": str(exc)})
            return False
        if account is None:
            self._send_json(int(HTTPStatus.UNAUTHORIZED), {"error": "login required"})
            return False
        try:
            account_id = self._account_payload(account)["id"]
            self._request_game = self.account_games.acquire(account_id)
            self._leased_account_id = account_id
        except (OSError, sqlite3.Error):
            self._send_json(int(HTTPStatus.SERVICE_UNAVAILABLE), {"error": "account storage is unavailable"})
            return False
        except ValueError as exc:
            # AccountGameRegistry acquires the account archive/Arena owner
            # lock here.  A second process serving the same account is a
            # client-visible conflict, rather than a dropped connection.
            self._send_json(int(HTTPStatus.CONFLICT), {"error": str(exc)})
            return False
        return True

    def _release_account(self) -> None:
        account_id = getattr(self, "_leased_account_id", None)
        self._leased_account_id = None
        if account_id is not None:
            self.account_games.release(account_id)

    def _account_session(self) -> None:
        try:
            account = self._current_account()
            available = self.account_games.legacy_available(
                self._account_payload(account)["id"] if account is not None else None
            )
        except (OSError, sqlite3.Error):
            self._send_json(int(HTTPStatus.SERVICE_UNAVAILABLE), {"error": "account storage is unavailable"})
            return
        payload: dict[str, object] = {"authenticated": account is not None}
        if account is not None:
            payload["account"] = self._account_payload(account)
            payload["legacy_available"] = available
        self._send_json(int(HTTPStatus.OK), payload)

    def _account_post(self, path: str, payload: object) -> None:
        from .accounts import AccountAuthError, AccountConflict
        from .account_game import LegacyImportError

        if not isinstance(payload, dict):
            self._send_json(int(HTTPStatus.BAD_REQUEST), {"error": "request body must be a JSON object"})
            return
        store = self.account_games.accounts
        try:
            if path == "/api/account/register":
                store.register(payload.get("username"), payload.get("password"))
                account, token = store.login(payload.get("username"), payload.get("password"))
            elif path == "/api/account/login":
                account, token = store.login(payload.get("username"), payload.get("password"))
            elif path == "/api/account/logout":
                token = self._session_token()
                if token:
                    store.logout(token)
                self._send_json(int(HTTPStatus.OK), {"authenticated": False}, headers={
                    "Set-Cookie": f"{_SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0",
                })
                return
            elif path == "/api/account/import-legacy":
                account = self._current_account()
                if account is None:
                    self._send_json(int(HTTPStatus.UNAUTHORIZED), {"error": "login required"})
                    return
                account_id = self._account_payload(account)["id"]
                if payload.get("account_id") != account_id:
                    self._send_json(int(HTTPStatus.CONFLICT), {"error": "account changed; reload this page"})
                    return
                imported = self.account_games.import_legacy(account_id)
                self._send_json(int(HTTPStatus.OK), {"imported": imported, "legacy_available": False})
                return
            else:
                self._not_found()
                return
        except AccountConflict as exc:
            self._send_json(int(HTTPStatus.CONFLICT), {"error": str(exc)})
            return
        except AccountAuthError:
            self._send_json(int(HTTPStatus.UNAUTHORIZED), {"error": "invalid username or password"})
            return
        except LegacyImportError as exc:
            self._send_json(int(HTTPStatus.CONFLICT), {"error": str(exc)})
            return
        except ValueError as exc:
            self._send_json(int(HTTPStatus.BAD_REQUEST), {"error": str(exc)})
            return
        except (OSError, sqlite3.Error):
            self._send_json(int(HTTPStatus.SERVICE_UNAVAILABLE), {"error": "account storage is unavailable"})
            return
        self._send_json(int(HTTPStatus.OK), {
            "authenticated": True,
            "account": self._account_payload(account),
            "legacy_available": self.account_games.legacy_available(self._account_payload(account)["id"]),
        }, headers={
            "Set-Cookie": f"{_SESSION_COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={_SESSION_AGE}",
        })

    def _not_found(self) -> None:
        self._send_json(int(HTTPStatus.NOT_FOUND), {"error": "not found"})

    def _send_asset(self, asset: tuple[bytes, str, bool] | object | None) -> None:
        if asset is ASSET_PENDING:
            self._send_bytes(
                int(HTTPStatus.ACCEPTED), b"", "application/octet-stream"
            )
        elif asset is None:
            self._not_found()
        else:
            self._send_bytes(
                int(HTTPStatus.OK), asset[0], asset[1], placeholder=asset[2]
            )

    def _query(self, allowed: set[str]) -> dict[str, str]:
        """Read one value per known query key; reject ambiguous parameters."""

        parsed = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        if set(parsed) - allowed or any(len(values) != 1 for values in parsed.values()):
            raise ValueError("invalid catalog query parameters")
        return {key: values[0] for key, values in parsed.items()}

    def _catalog_locale(self) -> str:
        query = self._query({"locale"})
        locale = query.get("locale", "zhCN")
        if locale not in {"zhCN", "enUS"}:
            raise ValueError("locale must be zhCN or enUS")
        return locale

    def _local_host(self) -> str | None:
        """Reject DNS rebinding names before serving private game state."""

        host = self.headers.get("Host", "").lower()
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed.update({"127.0.0.1", "localhost"})
        return host if host in allowed else None

    def _reject_untrusted_request(self) -> bool:
        try:
            local_peer = ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            local_peer = False
        if local_peer and self._local_host() is not None:
            return False
        self._send_json(int(HTTPStatus.FORBIDDEN), {"error": "local host required"})
        return True

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._request_game = None
        self._leased_account_id = None
        try:
            self._do_GET()
        finally:
            self._release_account()

    def _do_GET(self) -> None:
        self._request_game = None
        if self._reject_untrusted_request():
            return
        path = urlsplit(self.path).path
        if path == "/api/account/session" and self.account_games is not None:
            self._account_session()
            return
        if (
            path in {
                "/api/state",
                "/api/decks",
                "/api/arena/state",
                "/api/matches",
                "/api/matches/detail",
                "/api/matches/download",
            }
            or path.startswith("/assets/")
        ) and not self._require_account():
            return
        if path == "/api/matches":
            try:
                query = self._query({"offset", "limit"})
                offset = int(query.get("offset", "0"))
                limit = int(query.get("limit", "50"))
                state = self.web_game.matches_list(offset=offset, limit=limit)
            except WebLifecycleError as exc:
                response = dict(exc.snapshot)
                response["error"] = str(exc)
                self._send_json(exc.status_code, response)
                return
            except (ValueError, TypeError) as exc:
                self._send_json(int(HTTPStatus.BAD_REQUEST), {"error": str(exc)})
                return
            self._send_json(int(HTTPStatus.OK), state)
            return
        if path in {"/api/matches/detail", "/api/matches/download"}:
            try:
                query = self._query({"game_id"})
                game_id = query.get("game_id")
                if not game_id:
                    raise ValueError("game_id is required")
                if path.endswith("/detail"):
                    payload = self.web_game.match_detail(game_id)
                    self._send_json(int(HTTPStatus.OK), payload)
                    return
                _game_id, log = self.web_game.match_download(game_id)
                self._send_bytes(
                    int(HTTPStatus.OK),
                    _json_bytes(log),
                    "application/json; charset=utf-8",
                    headers={
                        "Content-Disposition": 'attachment; filename="match-%s.json"' % _game_id
                    },
                )
                return
            except WebLifecycleError as exc:
                response = dict(exc.snapshot)
                response["error"] = str(exc)
                self._send_json(exc.status_code, response)
                return
            except (ValueError, TypeError) as exc:
                self._send_json(int(HTTPStatus.BAD_REQUEST), {"error": str(exc)})
                return
        if path == "/api/arena/state":
            handler = getattr(self.web_game, "arena_state", None)
            if handler is None:
                self._not_found()
                return
            try:
                query = self._query({"locale"})
                state = handler(locale=query.get("locale", "zhCN"))
            except WebLifecycleError as exc:
                response = dict(exc.snapshot)
                response["error"] = str(exc)
                self._send_json(exc.status_code, response)
                return
            except ValueError as exc:
                self._send_json(int(HTTPStatus.BAD_REQUEST), {"error": str(exc)})
                return
            self._send_json(int(HTTPStatus.OK), state)
            return
        if path == "/api/state":
            self._send_json(int(HTTPStatus.OK), self.web_game.snapshot())
            return
        if path == "/api/decks":
            handler = getattr(self.web_game, "decks_state", None)
            if handler is None:
                self._not_found()
                return
            try:
                query = self._query({"locale"})
                state = handler(locale=query.get("locale", "zhCN"))
            except WebLifecycleError as exc:
                response = dict(exc.snapshot)
                response["error"] = str(exc)
                self._send_json(exc.status_code, response)
                return
            except ValueError as exc:
                self._send_json(int(HTTPStatus.BAD_REQUEST), {"error": str(exc)})
                return
            self._send_json(int(HTTPStatus.OK), state)
            return
        if path == "/api/catalog":
            self._catalog_list()
            return
        if path.startswith("/api/catalog/cards/"):
            parts = path.split("/")
            if len(parts) == 5:
                self._catalog_detail(unquote(parts[4]))
            else:
                self._not_found()
            return
        if path.startswith("/catalog/assets/"):
            parts = path.split("/")
            if len(parts) == 5:
                self._catalog_asset(unquote(parts[3]), unquote(parts[4]))
            else:
                self._not_found()
            return
        if path == "/":
            self._serve_static("index.html")
            return
        if path == "/cards":
            self._serve_static("catalog.html")
            return
        if path == "/arena":
            self._serve_static("arena.html")
            return
        if path == "/collection":
            self._serve_static("collection.html")
            return
        if path == "/account":
            self._serve_static("account.html")
            return
        if path == "/history":
            self._serve_static("history.html")
            return
        if path.startswith("/") and path.count("/") == 1:
            name = unquote(path[1:])
            if _static_mime_type(name) is not None:
                self._serve_static(name)
                return
        if path.startswith("/assets/"):
            parts = path.split("/")
            if len(parts) == 4:
                kind = unquote(parts[2])
                card_id = unquote(parts[3])
                # Card ids in the asset contract are a single URL segment.
                if "/" not in card_id and "\\" not in card_id:
                    self._send_asset(self.web_game.asset(kind, card_id))
                    return
            self._not_found()
            return
        self._not_found()

    def _catalog_list(self) -> None:
        try:
            query = self._query(
                {"locale", "set", "class", "q", "scope", "sort", "page", "page_size"}
            )
            page = int(query.get("page", "1"))
            page_size = int(query.get("page_size", "48"))
            payload = self.catalog.list_cards(
                locale=query.get("locale", "zhCN"),
                card_set=query.get("set") or None,
                card_class=query.get("class") or None,
                query=query.get("q", ""),
                scope=query.get("scope", "collectible"),
                sort=query.get("sort", "name"),
                page=page,
                page_size=page_size,
            )
        except ValueError as exc:
            self._send_json(int(HTTPStatus.BAD_REQUEST), {"error": str(exc)})
            return
        self._send_json(int(HTTPStatus.OK), payload)

    def _catalog_detail(self, card_id: str) -> None:
        if "/" in card_id or "\\" in card_id:
            self._not_found()
            return
        try:
            card = self.catalog.get_card(card_id, locale=self._catalog_locale())
        except ValueError as exc:
            self._send_json(int(HTTPStatus.BAD_REQUEST), {"error": str(exc)})
            return
        if card is None:
            self._not_found()
        else:
            self._send_json(int(HTTPStatus.OK), card)

    def _catalog_asset(self, kind: str, card_id: str) -> None:
        if "/" in kind or "\\" in kind or "/" in card_id or "\\" in card_id:
            self._not_found()
            return
        try:
            locale = self._catalog_locale()
            if not self.catalog.contains(card_id):
                self._not_found()
                return
            future = self.catalog_assets.request_asset(card_id, kind, locale=locale)
            try:
                asset = future.result(timeout=0.05)
            except FutureTimeout:
                self._send_asset(ASSET_PENDING)
                return
            except Exception:
                self._not_found()
                return
        except ValueError as exc:
            self._send_json(int(HTTPStatus.BAD_REQUEST), {"error": str(exc)})
            return
        if asset is None:
            self._not_found()
        else:
            self._send_asset((asset.data, asset.media_type, asset.is_placeholder))

    def _serve_static(self, name: str) -> None:
        root = Path(__file__).resolve().parent
        path = root / name
        content_type = _static_mime_type(name)
        if content_type is None or not path.is_file():
            self._not_found()
            return
        try:
            data = path.read_bytes()
        except OSError:
            self._not_found()
            return
        self._send_bytes(int(HTTPStatus.OK), data, content_type)

    def _check_origin(self) -> bool:
        origin = self.headers.get("Origin")
        local_host = self._local_host()
        expected = "http://" + str(local_host)
        if (self.account_games is not None and origin != expected) or (
            self.account_games is None and origin is not None and origin != expected
        ):
            self._send_json(
                int(HTTPStatus.FORBIDDEN),
                self.web_game.error_payload("cross-origin request rejected"),
            )
            return False
        return True

    def _read_json(self) -> object:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._send_json(
                int(HTTPStatus.UNSUPPORTED_MEDIA_TYPE),
                self.web_game.error_payload("JSON content type required"),
            )
            return _JSON_ERROR
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except (TypeError, ValueError):
            length = -1
        if length < 0 or length > _MAX_REQUEST_BYTES:
            self._send_json(
                int(HTTPStatus.BAD_REQUEST),
                self.web_game.error_payload("invalid request body length"),
            )
            return _JSON_ERROR
        try:
            body = self.rfile.read(length)
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._send_json(
                int(HTTPStatus.BAD_REQUEST),
                self.web_game.error_payload("request body must be valid JSON"),
            )
            return _JSON_ERROR

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        self._request_game = None
        self._leased_account_id = None
        try:
            self._do_POST()
        finally:
            self._release_account()

    def _do_POST(self) -> None:
        self._request_game = None
        if self._reject_untrusted_request():
            return
        path = urlsplit(self.path).path
        account_routes = {
            "/api/account/register", "/api/account/login", "/api/account/logout",
            "/api/account/import-legacy",
        } if self.account_games is not None else set()
        arena_routes = {
            "/api/arena/start": "arena_start",
            "/api/arena/hero": "arena_choose_hero",
            "/api/arena/pick": "arena_choose_card",
            "/api/arena/battle": "arena_start_battle",
            "/api/arena/retire": "arena_retire",
            "/api/arena/reset": "arena_reset",
        }
        match_routes = {
            "/api/matches/resume": "resume_match",
            "/api/matches/abandon": "abandon_match",
        }
        deck_routes = {
            "/api/decks/save": "decks_save",
            "/api/decks/delete": "decks_delete",
        }
        if path not in {"/api/action", "/api/concede", "/api/start", "/api/return"} | set(arena_routes) | set(deck_routes) | set(match_routes) | account_routes:
            self._not_found()
            return
        if not self._check_origin():
            return
        if path not in account_routes and not self._require_account():
            return
        if path in arena_routes and not hasattr(self.web_game, arena_routes[path]):
            self._not_found()
            return
        if path in deck_routes and not hasattr(self.web_game, deck_routes[path]):
            self._not_found()
            return
        if path in match_routes and not hasattr(self.web_game, match_routes[path]):
            self._not_found()
            return
        if path == "/api/concede" and not hasattr(self.web_game, "concede"):
            self._not_found()
            return
        payload = self._read_json()
        if payload is _JSON_ERROR:
            return
        if path in account_routes:
            self._account_post(path, payload)
            return
        try:
            if path == "/api/action":
                response = self.web_game.handle_action(payload)
            elif path == "/api/concede":
                response = self.web_game.concede(payload)
            elif path == "/api/start":
                response = self.web_game.start_match(payload)
            elif path in arena_routes:
                response = getattr(self.web_game, arena_routes[path])(payload)
            elif path in deck_routes:
                response = getattr(self.web_game, deck_routes[path])(payload)
            elif path in match_routes:
                response = getattr(self.web_game, match_routes[path])(payload)
            else:
                response = self.web_game.return_to_lobby(payload)
        except (WebActionError, WebLifecycleError) as exc:
            response = dict(exc.snapshot)
            response["error"] = str(exc)
            self._send_json(exc.status_code, response)
            return
        self._send_json(int(HTTPStatus.OK), response)

    def log_message(self, format: str, *args: object) -> None:
        super().log_message(format, *args)


def make_server(
    web_game: WebBackend | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    seed: int | None = None,
    opponent: str = "radical",
    catalog: CardCatalog | None = None,
    catalog_assets: AssetService | None = None,
) -> WebGameHTTPServer:
    """Create a local threaded HTTP server for a game or a fresh lobby."""

    if web_game is None:
        from .accounts import AccountStore
        from .account_game import AccountGameRegistry

        web_game = AccountGameRegistry(accounts=AccountStore(), seed=seed)
    return WebGameHTTPServer(
        (host, int(port)), web_game,
        catalog=catalog, catalog_assets=catalog_assets,
    )


create_server = make_server


def serve(
    web_game: WebBackend | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    seed: int | None = None,
    opponent: str = "radical",
) -> None:
    """Run a server until interrupted, closing its listening socket."""

    server = make_server(web_game, host=host, port=port, seed=seed, opponent=opponent)
    try:
        server.serve_forever()
    finally:
        server.server_close()


__all__ = [
    "WebGameHTTPServer",
    "create_server",
    "make_server",
    "serve",
]
