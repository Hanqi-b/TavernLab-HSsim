"""Targeted regressions for the Witchwood warlock and hunter red cards."""

from hearthstone.enums import CardClass, Zone

from utils import WISP, prepare_empty_game


def ready_game(player_class, opponent_class=CardClass.MAGE):
    game = prepare_empty_game(player_class, opponent_class)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def damage_own_hero(player):
    """Deal real damage this turn so DAMAGED_THIS_TURN is exercised."""
    player.give("CS2_029").play(target=player.hero)
    player.used_mana = 0
    assert player.hero.damaged_this_turn > 0


def test_duskbat_requires_actual_hero_damage_this_turn():
    _, owner, _ = ready_game(CardClass.WARLOCK)
    unpowered = owner.give("GIL_508")
    unpowered.play()
    assert unpowered.zone == Zone.PLAY
    assert not owner.field.filter(id="GIL_508t")

    _, owner, _ = ready_game(CardClass.WARLOCK)
    damage_own_hero(owner)
    powered = owner.give("GIL_508")
    powered.play()
    assert powered.zone == Zone.PLAY
    assert len(owner.field.filter(id="GIL_508t")) == 2


def test_deathweb_spider_only_gains_lifesteal_after_hero_damage():
    _, owner, _ = ready_game(CardClass.WARLOCK)
    unpowered = owner.give("GIL_565")
    unpowered.play()
    assert unpowered.zone == Zone.PLAY
    assert not unpowered.lifesteal

    _, owner, _ = ready_game(CardClass.WARLOCK)
    damage_own_hero(owner)
    powered = owner.give("GIL_565")
    powered.play()
    assert powered.zone == Zone.PLAY
    assert powered.lifesteal


def test_rat_trap_triggers_on_the_third_opponent_card_and_only_once():
    game, owner, opponent = ready_game(CardClass.HUNTER)
    secret = owner.give("GIL_577")
    secret.play()
    game.end_turn()

    for _ in range(2):
        opponent.give(WISP).play()
    assert secret in owner.secrets
    assert not owner.field.filter(id="GIL_577t")

    opponent.give(WISP).play()
    rats = owner.field.filter(id="GIL_577t")
    assert len(rats) == 1
    assert secret.zone == Zone.GRAVEYARD
    assert secret not in owner.secrets

    opponent.give(WISP).play()
    assert len(owner.field.filter(id="GIL_577t")) == 1


def test_rat_trap_waits_if_owners_board_is_full():
    game, owner, opponent = ready_game(CardClass.HUNTER)
    secret = owner.give("GIL_577")
    secret.play()
    for _ in range(7):
        owner.summon(WISP)
    game.end_turn()
    for _ in range(3):
        opponent.give(WISP).play()
    assert secret.zone == Zone.SECRET
    assert len(owner.field) == 7
    assert not owner.field.filter(id="GIL_577t")


def test_dire_frenzy_buffs_beast_and_shuffles_three_buffed_copies():
    _, owner, _ = ready_game(CardClass.HUNTER)
    beast = owner.give("CS2_172").play()
    ordinary = owner.summon(WISP)
    spell = owner.give("GIL_828")

    assert beast in spell.targets
    assert ordinary not in spell.targets
    spell.play(target=beast)

    assert beast.zone == Zone.PLAY
    assert (beast.atk, beast.max_health) == (6, 5)
    copies = [card for card in owner.deck if card.id == "CS2_172"]
    assert len(copies) == 3
    assert all((card.atk, card.max_health) == (6, 5) for card in copies)
    assert all(card.zone == Zone.DECK for card in copies)


def test_glinda_gives_echo_to_existing_and_new_hand_minions():
    _, owner, _ = ready_game(CardClass.WARLOCK)
    existing = owner.give(WISP)
    glinda = owner.give("GIL_618")
    glinda.play()
    assert existing.echo

    new_minion = owner.give("CS2_182")
    assert new_minion.echo

    existing.play()
    existing_copies = [card for card in owner.hand if card.id == WISP]
    assert len(existing_copies) == 1
    assert existing_copies[0].echo
    assert any(buff.id == "GIL_000" for buff in existing_copies[0].buffs)

    new_minion.play()
    new_copies = [card for card in owner.hand if card.id == "CS2_182"]
    assert len(new_copies) == 1
    assert new_copies[0].echo
    assert any(buff.id == "GIL_000" for buff in new_copies[0].buffs)
