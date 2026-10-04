#!/usr/bin/env python3
"""Isolated real-engine fixture for the Sleepy Dragon live-stat browser check."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fireplace import cards
from fireplace.agents import HeuristicAgent
from fireplace.controller import GameSession
from fireplace.game import Game
from fireplace.player import Player
from fireplace.web_gui.server import WebGame, make_server


_SLEEPY_ID = "LOOT_137"
_HISTORIAN_ID = "KAR_062"
_DRAGON_OPTIONS = ("LOOT_137", "AT_123", "BRM_030")
_CACHED_RENDER = Path.home() / ".cache/card_assets/LOOT_137.render.zhCN.png"
_STALE_FALLBACK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="450" height="650" viewBox="0 0 450 650">
<defs><linearGradient id="g" x2="0" y2="1"><stop stop-color="#284866"/><stop offset="1" stop-color="#141d2e"/></linearGradient></defs>
<rect width="450" height="650" rx="32" fill="url(#g)" stroke="#d8bd75" stroke-width="10"/>
<text x="225" y="105" text-anchor="middle" fill="#f7e7be" font-size="38" font-family="serif">Sleepy Dragon</text>
<path d="M96 405 Q135 205 225 205 Q320 225 352 405Z" fill="#66819c" stroke="#d8bd75" stroke-width="8"/>
<text x="73" y="540" text-anchor="middle" dominant-baseline="central" fill="white" font-size="64" font-weight="bold">6</text>
<text x="377" y="540" text-anchor="middle" dominant-baseline="central" fill="white" font-size="64" font-weight="bold">12</text>
<text x="72" y="110" text-anchor="middle" dominant-baseline="central" fill="white" font-size="60" font-weight="bold">9</text>
</svg>"""


class StaleSleepyRender:
    """Serve a local, fixed card render and no external card assets."""

    def __init__(self, root: Path, locale: str):
        self.locale = locale
        cached = _CACHED_RENDER
        if locale == "zhCN" and cached.is_file():
            self.path = root / "LOOT_137.render.zhCN.png"
            shutil.copyfile(cached, self.path)
            self.media_type = "image/png"
            self.origin = "local-card-cache"
        else:
            self.path = root / "LOOT_137.render.svg"
            self.path.write_text(_STALE_FALLBACK_SVG, encoding="utf-8")
            self.media_type = "image/svg+xml"
            self.origin = "fixed-stale-svg"

    def describe(self, card_id: str, *, locale: str = "zhCN"):
        del locale
        if card_id != _SLEEPY_ID:
            return None
        # Card names and printed text already come from the local card DB.
        return None

    def resolve(self, card_id: str, *, kind: str = "render", locale: str = "zhCN"):
        del locale
        if card_id != _SLEEPY_ID or kind != "render":
            return None
        return SimpleNamespace(
            path=self.path,
            media_type=self.media_type,
            locale=self.locale,
            is_placeholder=False,
        )


class DiscoverStatsGame(WebGame):
    """Keep the actual user choice; add only a display-test enchantment after it."""

    def __init__(self, *args, **kwargs):
        self._fixture_ready = False
        super().__init__(*args, **kwargs)

    def handle_action(self, payload: object) -> dict[str, object]:
        response = super().handle_action(payload)
        action = payload.get("action") if isinstance(payload, dict) else None
        if not isinstance(action, dict):
            return response

        if not self._fixture_ready and action.get("type") == "MULLIGAN":
            with self.lock:
                human = self.human
                human.max_mana = 10
                human.used_mana = 0
                human.hand.clear()
                human.give(_HISTORIAN_ID)
                human.give(_SLEEPY_ID)  # Activates Historian's real Dragon condition.
                self._fixture_ready = True
                self._revision += 1
                response = self.snapshot()
        elif self._fixture_ready and action.get("type") == "CHOOSE":
            with self.lock:
                entity_id = action.get("choice_entity_id")
                chosen = next(
                    (card for card in self.human.hand if card.entity_id == entity_id),
                    None,
                )
                if chosen is not None and chosen.id == _SLEEPY_ID:
                    # Reuse the engine's real Sand Breath enchantment solely
                    # for hand-stat presentation coverage. Historian has no
                    # +1/+2 rule, and the browser assertion makes no such claim.
                    chosen.buff(chosen, "DRG_233e")
                    self._revision += 1
                    response = self.snapshot()
        return response


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--locale", choices=("zhCN", "enUS"), default="zhCN")
    args = parser.parse_args()

    cards.db.initialize()
    import fireplace.utils

    real_weighted_card_choice = fireplace.utils.weighted_card_choice

    def deterministic_historian_choice(source, weights, card_sets, count):
        """Use the real Discover and Dragon pool, fixing only its RNG."""
        if getattr(source, "id", None) != _HISTORIAN_ID:
            return real_weighted_card_choice(source, weights, card_sets, count)
        pool = {card_id for card_set in card_sets for card_id in card_set}
        assert set(_DRAGON_OPTIONS).issubset(pool), "fixture options must belong to the real Dragon pool"
        return [source.controller.card(card_id, source=source)
                for card_id in _DRAGON_OPTIONS[:count]]

    fireplace.utils.weighted_card_choice = deterministic_historian_choice
    root = Path(tempfile.mkdtemp(prefix="fireplace-discover-stats-"))
    asset_resolver = StaleSleepyRender(root, args.locale)
    human = Player("Discover Stats", ["CS2_231"] * 30, "HERO_04", is_standard=False)
    opponent = Player("Local Fixture", ["CS2_231"] * 30, "HERO_01", is_standard=False)
    session = GameSession(Game((human, opponent), seed=137), {})
    game = DiscoverStatsGame(
        session,
        human,
        HeuristicAgent(),
        asset_resolver=asset_resolver,
        locale=args.locale,
    )
    server = make_server(game, host="127.0.0.1", port=args.port)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stop.set())
    print(json.dumps({
        "url": f"http://127.0.0.1:{server.server_port}/",
        "locale": args.locale,
        "render_origin": asset_resolver.origin,
        "render_media_type": asset_resolver.media_type,
        "render_path": str(asset_resolver.path),
    }), flush=True)
    try:
        stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        game.close()
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
