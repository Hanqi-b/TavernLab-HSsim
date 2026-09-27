"""Small contracts shared by the web-game application and HTTP adapter."""

from __future__ import annotations

from typing import Any, Protocol


ASSET_PENDING = object()


class WebActionError(ValueError):
    """An HTTP action failure with its current, privacy-filtered snapshot."""

    def __init__(self, message: str, status_code: int, snapshot: dict[str, Any]):
        super().__init__(message)
        self.status_code = int(status_code)
        self.snapshot = snapshot


class WebLifecycleError(ValueError):
    """An HTTP failure while changing between lobby and match modes."""

    def __init__(self, message: str, status_code: int, snapshot: dict[str, Any]):
        super().__init__(message)
        self.status_code = int(status_code)
        self.snapshot = snapshot


class WebBackend(Protocol):
    """The complete application contract expected by the HTTP adapter."""

    def snapshot(self) -> dict[str, Any]: ...

    def error_payload(self, message: str) -> dict[str, Any]: ...

    def handle_action(self, payload: object) -> dict[str, Any]: ...

    def concede(self, payload: object) -> dict[str, Any]: ...

    def start_match(self, payload: object) -> dict[str, Any]: ...

    def return_to_lobby(self, payload: object) -> dict[str, Any]: ...

    def asset(
        self, kind: str, card_id: str
    ) -> tuple[bytes, str, bool] | object | None: ...

    def close(self) -> None: ...


__all__ = [
    "ASSET_PENDING",
    "WebActionError",
    "WebBackend",
    "WebLifecycleError",
]
