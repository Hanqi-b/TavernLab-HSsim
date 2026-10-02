import pytest

from hearthstone.enums import CardClass, CardType, Zone

from fireplace import cards
from utils import (
    GOLDSHIRE_FOOTMAN,
    MOONFIRE,
    THE_COIN,
    prepare_empty_game,
)


SHADOW_IDS = (
    "SCH_120",
    "SCH_126",
    "SCH_135",
    "SCH_136",
    "SCH_137",
    "SCH_138",
    "SCH_139",
    "SCH_140",
    "SCH_141",
    "SCH_147",
    "SCH_149",
    "SCH_158",
    "SCH_159",
    "SCH_181",
    "SCH_233",
    "SCH_247",
    "SCH_250",
    "SCH_252",
    "SCH_253",
    "SCH_276",
    "SCH_302",
    "SCH_307",
    "SCH_343",
    "SCH_354",
    "SCH_355",
    "SCH_356",
    "SCH_357",
    "SCH_422",
    "SCH_512",
    "SCH_513",
    "SCH_514",
    "SCH_517",
    "SCH_532",
    "SCH_603",
    "SCH_700",
    "SCH_701",
    "SCH_702",
    "SCH_703",
    "SCH_704",
    "SCH_705",
    "SCH_712",
)


def game_with_empty_hands():
    game = prepare_empty_game(CardClass.PRIEST, CardClass.PRIEST)
    return game, game.player1, game.player2


def refill(player):
    """Reset the sandbox player's spendable mana between independent checks."""
    player.used_mana = 0
    player.temp_mana = 0
    player.overloaded = 0
    player.overload_locked = 0


@pytest.mark.parametrize("card_id", SHADOW_IDS)
def test_every_shadow_card_has_a_runtime_script(card_id):
    card = cards.db[card_id]
    assert card.scripts is not None
    assert cards.get_script_definition(card_id, card) is not None


def test_shadow_spellburst_and_cost_adjustments():
    game, player, opponent = game_with_empty_hands()

    target = opponent.summon(GOLDSHIRE_FOOTMAN)
    acolyte = player.summon("SCH_120")
    player.give(MOONFIRE).play(target=target)
    assert target.controller is player
    assert acolyte in player.field

    freshman = player.give("SCH_137").play()
    assert freshman.atk == 1

    own_minion = player.summon(GOLDSHIRE_FOOTMAN)
    player.give(MOONFIRE).play(target=own_minion)
    pupil = player.give("SCH_139")
    assert pupil.cost == 5

    player.hero.set_current_health(29)
    giant = player.give("SCH_140")
    assert giant.cost == 7

    alura = player.summon("SCH_141")
    spell = player.give(MOONFIRE)
    spell.shuffle_into_deck()
    player.give(THE_COIN).play()
    assert alura.damage == 1
    assert spell.zone == Zone.GRAVEYARD

    goody = player.summon("SCH_532")
    goody.divine_shield = False
    player.give(THE_COIN).play()
    assert goody.divine_shield


def test_gandling_attack_buffs_and_battlecries():
    game, player, opponent = game_with_empty_hands()

    gandling = player.summon("SCH_126")
    player.give(GOLDSHIRE_FOOTMAN).play()
    assert not player.field.filter(id=GOLDSHIRE_FOOTMAN)
    assert player.field.filter(id="SCH_126t")
    assert gandling in player.field

    turalyon = player.summon("SCH_135")
    defender = opponent.summon(GOLDSHIRE_FOOTMAN)
    turalyon.turns_in_play = 1
    turalyon.attack(defender)
    assert (defender.atk, defender.max_health) == (3, 3)

    feast_target = player.summon(GOLDSHIRE_FOOTMAN)
    feast_target.hit(1)
    player.give("SCH_136").play(target=feast_target)
    assert (feast_target.atk, feast_target.max_health) == (3, 4)
    game.end_turn()
    assert feast_target.health == feast_target.max_health

    authority_target = player.summon(GOLDSHIRE_FOOTMAN)
    game.end_turn()
    refill(player)
    player.give("SCH_138").play(target=authority_target)
    assert (authority_target.atk, authority_target.max_health) == (9, 10)
    assert authority_target.cannot_attack_heroes
    game.end_turn()
    assert not authority_target.cannot_attack_heroes

    game.end_turn()
    refill(player)
    egg = player.give("SCH_147").play()
    egg.discard()
    assert len(player.field.filter(id="SCH_147t")) == 2

    for card in player.field[:]:
        card.destroy()
    player.summon("CS2_182")
    refill(player)
    braggart = player.give("SCH_149").play()
    assert (braggart.atk, braggart.max_health) == (4, 5)

    hunter = player.summon("SCH_276")
    silenced = opponent.summon(GOLDSHIRE_FOOTMAN)
    hunter.turns_in_play = 1
    hunter.attack(silenced)
    assert silenced.silenced


def test_studies_willow_and_illucia_temporarily_move_cards():
    game, player, opponent = game_with_empty_hands()

    player.give("SCH_158").play()
    assert player.choice
    demon_option = next(card for card in player.choice.cards if card.races)
    player.choice.choose(demon_option)
    assert demon_option in player.hand
    assert demon_option.cost == max(0, cards.db[demon_option.id].cost - 1)

    player.give("SCH_233").play()
    assert player.choice
    dragon_option = next(card for card in player.choice.cards if card.races)
    player.choice.choose(dragon_option)
    assert dragon_option in player.hand
    assert dragon_option.cost == max(0, cards.db[dragon_option.id].cost - 1)

    demon_in_hand = player.give("EX1_301")
    demon_in_deck = player.give("EX1_598")
    demon_in_deck.shuffle_into_deck()
    refill(player)
    willow = player.give("SCH_181").play()
    assert willow in player.field
    assert len(player.field.filter(races=15)) >= 2

    player.give("CS2_008")
    player.give("CS2_029")
    opponent.give("CS2_008")
    opponent.give("CS2_029")
    old_player_hand = [card.id for card in player.hand]
    old_opponent_hand = [card.id for card in opponent.hand]
    old_player_deck = [card.id for card in player.deck]
    old_opponent_deck = [card.id for card in opponent.deck]
    refill(player)
    player.give("SCH_159").play()
    assert [card.id for card in player.hand] == old_opponent_hand
    assert [card.id for card in opponent.hand] == old_player_hand
    game.end_turn()
    assert [card.id for card in player.hand] == old_opponent_hand
    game.end_turn()
    assert [card.id for card in player.hand] == old_player_hand
    assert [card.id for card in opponent.hand] == old_opponent_hand
    assert [card.id for card in player.deck] == old_player_deck
    assert [card.id for card in opponent.deck] == old_opponent_deck


def test_school_spells_weapons_and_board_wipes():
    game, player, opponent = game_with_empty_hands()

    player.give("SCH_247").play()
    assert len(player.hand) == 2
    assert all(card.cost == 1 for card in player.hand)

    wave_target = opponent.summon("CS2_182")
    refill(player)
    player.give("SCH_250").play()
    assert wave_target.atk == 1
    game.end_turn()
    game.end_turn()
    assert wave_target.atk == 4

    player.give("SCH_252").play()
    assert len(player.deck.filter(id="SCH_307t")) == 2

    victim_one = opponent.summon(GOLDSHIRE_FOOTMAN)
    victim_two = opponent.summon(GOLDSHIRE_FOOTMAN)
    refill(player)
    player.give("SCH_253").play()
    assert victim_one.zone == Zone.GRAVEYARD
    assert victim_two.zone == Zone.GRAVEYARD
    assert len(player.field.filter(id="SCH_253t")) == 2

    luminance_target = player.summon(GOLDSHIRE_FOOTMAN)
    player.give("SCH_302").play(target=luminance_target)
    assert luminance_target.divine_shield
    assert len(player.field.filter(id=GOLDSHIRE_FOOTMAN)) == 2
    assert any(card.atk == 1 and card.max_health == 1 for card in player.field)

    spirit_target = opponent.summon(GOLDSHIRE_FOOTMAN)
    refill(player)
    player.give("SCH_307").play()
    assert spirit_target.zone == Zone.GRAVEYARD
    assert len(player.deck.filter(id="SCH_307t")) == 4

    void_drinker = player.give("SCH_343")
    fragments_before_void_drinker = len(player.deck.filter(id="SCH_307t"))
    fragment = player.give("SCH_307t")
    fragment.shuffle_into_deck()
    void_drinker.play()
    assert (void_drinker.atk, void_drinker.health) == (7, 8)
    assert len(player.deck.filter(id="SCH_307t")) == fragments_before_void_drinker

    hound = player.summon("SCH_354")
    hound_target = opponent.summon(GOLDSHIRE_FOOTMAN)
    game.end_turn()
    assert hound.atk == 11
    assert hound_target.atk == 0

    game.end_turn()
    mystic_target = opponent.summon(GOLDSHIRE_FOOTMAN)
    fragment = player.give("SCH_307t")
    fragment.shuffle_into_deck()
    player.give("SCH_355").play()
    assert mystic_target.zone == Zone.GRAVEYARD
    assert not player.deck.filter(id="SCH_307t")


def test_cycle_and_initiation_use_death_history_when_deathrattles_move_cards():
    game, player, opponent = game_with_empty_hands()

    malorne = opponent.summon("GVG_035")
    malorne.hit(6)
    player.give("SCH_253").play()
    assert malorne.zone == Zone.DECK
    assert len(player.field.filter(id="SCH_253t")) == 1

    target = opponent.summon("GVG_035")
    target.hit(3)
    refill(player)
    player.give("SCH_512").play(target=target)
    assert target.zone == Zone.DECK
    assert player.field.filter(id="GVG_035")
    assert player.field[-1].damage == 0


def test_raise_dead_uses_minions_that_deathrattles_moved_out_of_graveyard():
    game, player, opponent = game_with_empty_hands()

    malorne = player.summon("GVG_035")
    malorne.destroy()
    assert malorne.zone == Zone.DECK
    refill(player)
    player.give("SCH_514").play()
    assert player.hand.filter(id="GVG_035")


def test_void_hound_snapshots_actual_attack_and_health_to_steal():
    game, player, opponent = game_with_empty_hands()

    hound = player.summon("SCH_354")
    zero_attack = opponent.summon("CS2_231")
    zero_attack.atk = 0
    positive_attack = opponent.summon(GOLDSHIRE_FOOTMAN)
    game.end_turn()

    assert hound.atk == 11
    assert hound.health == 12
    assert zero_attack.zone == Zone.GRAVEYARD
    assert positive_attack.atk == 0
    assert positive_attack.health == 1


def test_outcast_and_health_condition_cards():
    game, player, opponent = game_with_empty_hands()

    for card_id in (MOONFIRE, "CS2_029", "CS2_008", "CS1_042"):
        player.give(card_id)
    glide = player.give("SCH_356")
    player.hand.remove(glide)
    player.hand.insert(0, glide)
    for card_id in (MOONFIRE, "CS2_029", "CS2_008", "CS1_042"):
        player.give(card_id).shuffle_into_deck()
    opponent.discard_hand()
    for card_id in (MOONFIRE, "CS2_029", "CS2_008", "CS1_042"):
        opponent.give(card_id).shuffle_into_deck()
    glide.play()
    assert len(player.hand) == 4
    assert len(opponent.hand) == 4

    guardians = player.give("SCH_357")
    dead_minion = player.summon(GOLDSHIRE_FOOTMAN)
    dead_minion.destroy()
    assert guardians.cost == 6
    guardians.play()
    assert len(player.field.filter(id="SCH_357t")) == 3

    player.discard_hand()
    outcast_card = player.give("SCH_422")
    outcast_source = player.give("SCH_356")
    outcast_source.shuffle_into_deck()
    refill(player)
    outcast_card.play()
    assert outcast_source in player.hand

    initiation_target = opponent.summon(GOLDSHIRE_FOOTMAN)
    initiation_target.hit(1)
    player.give("SCH_512").play(target=initiation_target)
    assert initiation_target.zone == Zone.GRAVEYARD
    assert player.field.filter(id=GOLDSHIRE_FOOTMAN)
    assert player.field[-1].damage == 0

    player.hero.set_current_health(29)
    destroyer_target = opponent.summon(GOLDSHIRE_FOOTMAN)
    refill(player)
    player.give("SCH_513").play(target=destroyer_target)
    assert destroyer_target.zone == Zone.GRAVEYARD

    dead = player.summon(GOLDSHIRE_FOOTMAN)
    dead.destroy()
    health_before = player.hero.health
    player.give("SCH_514").play()
    assert player.hero.health == health_before - 3
    assert GOLDSHIRE_FOOTMAN in [card.id for card in player.hand]

    scholar_target = opponent.summon(GOLDSHIRE_FOOTMAN)
    fragment = player.give("SCH_307t")
    fragment.shuffle_into_deck()
    player.give("SCH_517").play(target=scholar_target)
    assert scholar_target.zone == Zone.GRAVEYARD
    assert not player.deck.filter(id="SCH_307t")


def test_stelina_and_soul_fragment_cards():
    game, player, opponent = game_with_empty_hands()

    for card_id in (MOONFIRE, "CS2_029", "CS2_008"):
        opponent.give(card_id)
    stelina = player.give("SCH_603")
    player.hand.remove(stelina)
    player.hand.insert(0, stelina)
    stelina.play()
    assert player.choice
    chosen = player.choice.cards[0]
    player.choice.choose(chosen)
    assert chosen.zone == Zone.DECK

    player.give("SCH_700").play()
    assert len(player.deck.filter(id="SCH_307t")) == 2

    soul_shear_target = opponent.summon(GOLDSHIRE_FOOTMAN)
    player.give("SCH_701").play(target=soul_shear_target)
    assert soul_shear_target.zone == Zone.GRAVEYARD
    assert len(player.deck.filter(id="SCH_307t")) == 4

    demon = player.give("EX1_301")
    demon.buff(demon, "SCH_702e")
    felosophy = player.give("SCH_702")
    player.hand.remove(felosophy)
    player.hand.insert(0, felosophy)
    felosophy.play()
    copies = player.hand.filter(id="EX1_301")
    assert len(copies) == 2
    assert all(card.atk == 5 and card.max_health == 7 for card in copies)

    for card in player.field[:]:
        card.destroy()
    for _ in range(2):
        player.give("SCH_307t").shuffle_into_deck()
    refill(player)
    player.give("SCH_703").play()
    assert len(player.field.filter(id="SCH_703t")) == 6

    for card in player.field[:]:
        card.destroy()
    fragments_before_lapidary = len(player.deck.filter(id="SCH_307t"))
    fragment = player.give("SCH_307t")
    fragment.shuffle_into_deck()
    refill(player)
    lapidary = player.give("SCH_704").play()
    assert player.hero.atk == 5
    assert lapidary in player.field
    assert len(player.deck.filter(id="SCH_307t")) == fragments_before_lapidary

    refill(player)
    trainer = player.give("SCH_705")
    player.hand.remove(trainer)
    player.hand.insert(0, trainer)
    trainer.play()
    assert len(player.field.filter(id="SCH_705t")) == 2

    refill(player)
    junior = player.give("SCH_712").play()
    assert junior.lifesteal
