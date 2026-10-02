"""Record completed hero Health changes, excluding armor-only damage."""
from hearthstone.enums import CardType, Zone


def record_hero_health_change(target, previous_health):
    if (
        target.type != CardType.HERO
        or target.zone != Zone.PLAY
        or previous_health == target.health
    ):
        return
    player = target.controller
    player.hero_health_changed_turn = target.game.turn
    if player is target.game.current_player:
        player.hero_health_changes_on_own_turn += 1
