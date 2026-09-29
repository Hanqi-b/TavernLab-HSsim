"""Targeted regressions for six Kobolds & Catacombs collectible cards."""

from hearthstone.enums import CardClass, CardType, Race, Zone
from fireplace.exceptions import InvalidAction

from utils import FIREBALL, MOONFIRE, WISP, prepare_empty_game


def ready_game(hero_class=CardClass.MAGE):
    game = prepare_empty_game(hero_class, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_elven_minstrel_combo_draws_two_minions_and_only_with_combo():
    game, owner, opponent = ready_game(CardClass.ROGUE)
    spell = owner.card(FIREBALL, zone=Zone.DECK)
    first = owner.card(WISP, zone=Zone.DECK)
    second = owner.card("EX1_399", zone=Zone.DECK)
    minstrel = owner.give("LOOT_211")

    # The Combo branch is inactive without a prior card play.
    minstrel.play()
    assert minstrel.zone == Zone.PLAY
    assert first.zone == Zone.DECK and second.zone == Zone.DECK
    assert spell.zone == Zone.DECK

    owner.used_mana = 0
    owner.give(MOONFIRE).play(target=opponent.hero)
    second_minstrel = owner.give("LOOT_211")
    second_minstrel.play()

    assert second_minstrel.zone == Zone.PLAY
    assert first.zone == Zone.HAND and second.zone == Zone.HAND
    assert spell.zone == Zone.DECK
    assert [card.type for card in owner.hand].count(CardType.MINION) == 2


def test_evasion_reveals_and_consumes_secret_then_expires_immunity():
    game, owner, opponent = ready_game()
    secret = owner.give("LOOT_214")
    secret.play()
    attacker = opponent.summon("EX1_399")
    second_attacker = opponent.summon("EX1_399")

    game.end_turn()
    attacker.attack(owner.hero)
    assert secret.zone == Zone.GRAVEYARD
    assert secret not in owner.secrets
    assert owner.hero.health == 28
    assert owner.hero.immune

    # The consumed secret cannot trigger again during the same turn.
    try:
        second_attacker.attack(owner.hero)
    except InvalidAction:
        pass
    else:
        raise AssertionError("an immune hero must not be a legal attack target")
    assert owner.hero.health == 28

    game.end_turn()
    assert not owner.hero.immune
    game.end_turn()
    second_attacker.attack(owner.hero)
    assert owner.hero.health == 26


def _draw_elixir(owner, seed):
    owner.game.random.seed(seed)
    source = owner.card("LOOT_278", zone=Zone.DECK)
    prior = {id(card) for card in owner.hand}
    drawn = owner.draw()
    added = [card for card in owner.hand if id(card) not in prior]
    variants = {"LOOT_278t1", "LOOT_278t2", "LOOT_278t3", "LOOT_278t4"}
    result = [card for card in added if card.id in variants]
    assert drawn is source and source.zone == Zone.SETASIDE
    assert len(result) == 1 and result[0].zone == Zone.HAND
    return result[0]


def test_unidentified_elixir_exercises_all_four_bonus_variants():
    seen = set()
    samples = {}
    for seed in range(3000, 3048):
        _, owner, _ = ready_game(CardClass.PRIEST)
        card = _draw_elixir(owner, seed)
        seen.add(card.id)
        target = owner.summon(WISP)
        card.play(target=target)

        assert target.atk == 3 and target.max_health == 3
        if card.id == "LOOT_278t1":
            assert target.lifesteal
        elif card.id == "LOOT_278t2":
            assert target.divine_shield
        elif card.id == "LOOT_278t3":
            copies = [minion for minion in owner.field if minion.id == WISP and minion is not target]
            assert len(copies) == 1
            assert (copies[0].atk, copies[0].max_health) == (1, 1)
        elif card.id == "LOOT_278t4":
            target.destroy()
            assert target.zone == Zone.HAND
            assert not any(minion.id == WISP for minion in owner.field)
        else:
            raise AssertionError(card.id)
        samples.setdefault(card.id, seed)

    assert seen == {"LOOT_278t1", "LOOT_278t2", "LOOT_278t3", "LOOT_278t4"}, samples


def test_kobold_illusionist_summons_a_one_one_copy_and_keeps_source_in_hand():
    _, owner, _ = ready_game(CardClass.ROGUE)
    original = owner.give("CS2_182")
    owner.give(MOONFIRE)
    illusionist = owner.give("LOOT_412")

    illusionist.play()
    illusionist.destroy()

    copies = [minion for minion in owner.field if minion.id == original.id]
    assert illusionist.zone == Zone.GRAVEYARD
    assert original.zone == Zone.HAND
    assert len(copies) == 1
    assert (copies[0].atk, copies[0].max_health) == (1, 1)


def test_skull_of_the_manari_summons_a_demon_from_hand_only_on_owners_turn():
    game, owner, _ = ready_game(CardClass.WARLOCK)
    skull = owner.give("LOOT_420")
    skull.play()
    demon = owner.give("EX1_310")
    non_demon = owner.give(WISP)
    assert not owner.field

    game.end_turn()
    assert not owner.field
    game.end_turn()

    summoned = [minion for minion in owner.field if Race.DEMON in minion.races]
    assert len(summoned) == 1
    assert summoned[0] is demon
    assert demon.zone == Zone.PLAY
    assert non_demon.zone == Zone.HAND
    assert skull.zone == Zone.PLAY


def test_onyx_spellstone_upgrades_after_three_and_six_deathrattle_cards():
    _, owner, opponent = ready_game(CardClass.ROGUE)
    stone = owner.give("LOOT_503")

    # Ordinary cards do not advance the spellstone.
    owner.give(WISP).play()
    assert stone.id == "LOOT_503" and stone.zone == Zone.HAND

    for _ in range(3):
        owner.used_mana = 0
        owner.give("LOOT_413").play()
    two_form = next(card for card in owner.hand if card.id.startswith("LOOT_503"))
    assert two_form.id == "LOOT_503t"

    enemies = [opponent.summon(WISP) for _ in range(3)]
    two_form.play()
    assert sum(minion.zone == Zone.GRAVEYARD for minion in enemies) == 2

    # A fresh stone verifies the second upgrade independently of the first cast.
    _, owner, _ = ready_game(CardClass.ROGUE)
    stone = owner.give("LOOT_503")
    for _ in range(6):
        owner.used_mana = 0
        owner.give("LOOT_413").play()
    greater = next(card for card in owner.hand if card.id.startswith("LOOT_503"))
    assert greater.id == "LOOT_503t2"
