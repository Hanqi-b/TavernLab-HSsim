"""Card-level regressions for the archived board-capacity findings.

Each test covers one collectible card and exercises the previously failing
board-capacity branch alongside a meaningful control branch.
"""

from hearthstone.enums import CardClass, CardType, Zone

from utils import FIREBALL, MOONFIRE, WISP, prepare_empty_game


def _game(card_class=CardClass.MAGE):
    game = prepare_empty_game(card_class, card_class)
    for player in game.players:
        player.max_mana = 10
        player.used_mana = 0
    while game.current_player is not game.player1:
        game.end_turn()
    return game


def _set_mana(player, amount=10):
    player.max_mana = amount
    player.used_mana = 0


def test_ex1_136_redemption_respects_dormant_full_board_and_resurrects_at_one():
    # Deathrattle fills Cairne's freed slot first; Redemption must stay set.
    game = _game()
    owner, opponent = game.player1, game.player2
    secret = owner.give("EX1_136").play()
    cairne = owner.summon("EX1_110")
    for _ in range(5):
        owner.summon(WISP)
    dormant = owner.summon("BT_934")
    assert dormant.dormant and len(owner.field) == 7
    game.end_turn()
    opponent.give(FIREBALL).play(target=cairne)

    baine = [m for m in owner.field if m.id == "EX1_110t"]
    assert cairne.zone == Zone.GRAVEYARD
    assert dormant in owner.field and len(owner.field) == 7
    assert len(baine) == 1 and (baine[0].atk, baine[0].health) == (4, 5)
    assert secret.zone == Zone.SECRET and secret in owner.secrets

    # On an open board the Secret copies the dead minion at 1 Health.
    game = _game()
    owner = game.player1
    secret = owner.give("EX1_136").play()
    footman = owner.give("CS1_042").play()
    game.end_turn()
    footman.destroy()
    resurrected = [m for m in owner.field if m.id == "CS1_042"]
    assert footman.zone == Zone.GRAVEYARD
    assert len(resurrected) == 1 and resurrected[0].health == 1
    assert secret.zone == Zone.GRAVEYARD and secret not in owner.secrets


def test_ex1_130_noble_sacrifice_keeps_secret_on_dormant_full_board():
    # With seven occupied slots the attacker hits the hero and the Secret stays.
    game = _game()
    owner, opponent = game.player1, game.player2
    secret = owner.give("EX1_130").play()
    for _ in range(6):
        owner.summon(WISP)
    dormant = owner.summon("BT_934")
    attacker = opponent.summon(WISP)
    assert dormant.dormant and len(owner.field) == 7
    game.end_turn()
    health = owner.hero.health
    attacker.attack(owner.hero)

    defenders = [m for m in owner.field if m.id == "EX1_130a"]
    assert owner.hero.health == health - 1
    assert attacker.zone == Zone.PLAY and not defenders
    assert dormant in owner.field and len(owner.field) == 7
    assert secret.zone == Zone.SECRET and secret in owner.secrets

    # On an open board Noble Sacrifice reveals and redirects the attack.
    game = _game()
    owner, opponent = game.player1, game.player2
    secret = owner.give("EX1_130").play()
    attacker = opponent.summon(WISP)
    game.end_turn()
    health = owner.hero.health
    attacker.attack(owner.hero)
    assert owner.hero.health == health
    assert attacker.zone == Zone.GRAVEYARD
    assert secret.zone == Zone.GRAVEYARD and secret not in owner.secrets
    defenders = [m for m in owner.graveyard if m.id == "EX1_130a"]
    assert len(defenders) == 1 and (defenders[0].atk, defenders[0].health) == (2, 1)

    # An attack at a friendly minion is redirected by the same Secret.
    game = _game()
    owner, opponent = game.player1, game.player2
    secret = owner.give("EX1_130").play()
    target = owner.summon(WISP)
    attacker = opponent.summon(WISP)
    game.end_turn()
    attacker.attack(target)
    defenders = [m for m in owner.graveyard if m.id == "EX1_130a"]
    assert target.zone == Zone.PLAY and target.health == 1
    assert attacker.zone == Zone.GRAVEYARD
    assert secret.zone == Zone.GRAVEYARD and len(defenders) == 1
    assert (defenders[0].atk, defenders[0].health) == (2, 1)


def test_ung_111_living_mana_preserves_crystals_when_dormant_board_is_full():
    # Six minions plus a Dormant occupant is a full board: no crystals convert.
    game = _game(CardClass.DRUID)
    player = game.player1
    _set_mana(player, 8)
    for _ in range(6):
        player.summon(WISP)
    dormant = player.summon("UNG_065t")
    assert dormant.dormant and len(player.field) == 7
    spell = player.give("UNG_111").play()
    assert spell.zone == Zone.GRAVEYARD
    assert len(player.field) == 7 and dormant in player.field
    assert not [m for m in player.field if m.id == "UNG_111t1"]
    assert player.max_mana == 8 and player.mana == 3

    # On an open board eight crystals become seven Treants; a death restores one.
    game = _game(CardClass.DRUID)
    player = game.player1
    _set_mana(player, 8)
    spell = player.give("UNG_111").play()
    treants = [m for m in player.field if m.id == "UNG_111t1"]
    assert spell.zone == Zone.GRAVEYARD and len(treants) == 7
    assert all((m.atk, m.health, m.max_health) == (2, 2, 2) for m in treants)
    assert player.max_mana == 1 and player.mana == 1
    treants[0].destroy()
    assert treants[0].zone == Zone.GRAVEYARD
    assert player.max_mana == 2 and player.mana == 1

    # With exactly five crystals, the card converts all five crystals to Treants.
    game = _game(CardClass.DRUID)
    player = game.player1
    _set_mana(player, 5)
    spell = player.give("UNG_111").play()
    treants = [m for m in player.field if m.id == "UNG_111t1"]
    assert spell.zone == Zone.GRAVEYARD and len(treants) == 5
    assert all((m.atk, m.health) == (2, 2) for m in treants)
    assert player.max_mana == 0 and player.mana == 0


def test_icc_200_bear_trap_dormant_full_board_and_open_slot_branches():
    # A Dormant occupant makes the seven-slot board full, so the Secret stays.
    game = _game(CardClass.HUNTER)
    owner, opponent = game.player1, game.player2
    target = owner.summon("EX1_399")
    for _ in range(5):
        owner.summon(WISP)
    dormant = owner.summon("BT_009")
    secret = owner.give("ICC_200").play()
    attacker = opponent.summon(WISP)
    assert dormant.dormant and len(owner.field) == 7
    game.end_turn()
    attacker.attack(target)
    assert target.damage == 1 and target.zone == Zone.PLAY
    assert dormant in owner.field and len(owner.field) == 7
    assert not [m for m in owner.field if m.id == "EX1_170"]
    assert secret.zone == Zone.SECRET and secret in owner.secrets

    # One open slot permits a 2/3 Poisonous Cobra and consumes the Secret.
    game = _game(CardClass.HUNTER)
    owner, opponent = game.player1, game.player2
    target = owner.summon("EX1_399")
    for _ in range(4):
        owner.summon(WISP)
    dormant = owner.summon("BT_009")
    secret = owner.give("ICC_200").play()
    attacker = opponent.summon(WISP)
    assert dormant.dormant and len(owner.field) == 6
    game.end_turn()
    attacker.attack(target)
    cobras = [m for m in owner.field if m.id == "EX1_170"]
    assert target.damage == 1 and len(owner.field) == 7
    assert len(cobras) == 1 and (cobras[0].atk, cobras[0].health) == (2, 3)
    assert cobras[0].poisonous and cobras[0].controller is owner
    assert secret.zone == Zone.GRAVEYARD and secret not in owner.secrets


def test_icc_054_spreading_plague_stops_at_last_dormant_board_slot():
    # One open slot behind Dormant: summon exactly one Scarab, then terminate.
    game = _game(CardClass.DRUID)
    player, opponent = game.player1, game.player2
    for _ in range(5):
        player.summon(WISP)
    dormant = player.summon("BT_934")
    for _ in range(7):
        opponent.summon(WISP)
    _set_mana(player)
    spell = player.give("ICC_054").play()
    scarabs = [m for m in player.field if m.id == "ICC_832t4"]
    assert spell.zone == Zone.GRAVEYARD
    assert dormant in player.field and len(player.field) == 7
    assert len(scarabs) == 1
    assert (scarabs[0].atk, scarabs[0].health, scarabs[0].taunt) == (1, 5, True)
    assert len(opponent.field) == 7 and player.mana == 4

    # With room and two enemy minions, it repeats twice and stops at equality.
    game = _game(CardClass.DRUID)
    player, opponent = game.player1, game.player2
    spell = player.give("ICC_054").play()
    scarabs = [m for m in player.field if m.id == "ICC_832t4"]
    assert spell.zone == Zone.GRAVEYARD and len(scarabs) == 1
    assert len(player.field) == 1 and len(opponent.field) == 0

    # With room and two enemy minions, it repeats twice and stops at equality.
    game = _game(CardClass.DRUID)
    player, opponent = game.player1, game.player2
    for _ in range(2):
        opponent.summon(WISP)
    _set_mana(player)
    spell = player.give("ICC_054").play()
    scarabs = [m for m in player.field if m.id == "ICC_832t4"]
    assert spell.zone == Zone.GRAVEYARD and len(scarabs) == 2
    assert len(player.field) == len(opponent.field) == 2
    assert all((m.atk, m.health, m.taunt) == (1, 5, True) for m in scarabs)

    # Dormant enemy minions still count for the repeat condition.
    game = _game(CardClass.DRUID)
    player, opponent = game.player1, game.player2
    dormant_enemies = [opponent.summon("BT_934") for _ in range(2)]
    assert all(m.dormant for m in dormant_enemies)
    _set_mana(player)
    spell = player.give("ICC_054").play()
    scarabs = [m for m in player.field if m.id == "ICC_832t4"]
    assert spell.zone == Zone.GRAVEYARD and len(scarabs) == 2
    assert all(m in opponent.field for m in dormant_enemies)
    assert len(player.field) == len(opponent.field) == 2


def test_ex1_116_leeroy_summons_for_opponent_and_obeys_opponent_cap():
    # Leeroy itself fills the friendly board; two Whelps still go to the enemy.
    game = _game()
    owner, opponent = game.player1, game.player2
    for _ in range(6):
        owner.summon(WISP)
    for _ in range(5):
        opponent.summon(WISP)
    leeroy = owner.give("EX1_116").play()
    whelps = [m for m in opponent.field if m.id == "EX1_116t"]
    assert leeroy in owner.field and len(owner.field) == 7
    assert leeroy.can_attack() and (leeroy.atk, leeroy.health) == (6, 2)
    assert len(opponent.field) == 7 and len(whelps) == 2
    assert all(m.controller is opponent and (m.atk, m.health) == (1, 1) for m in whelps)

    # A full enemy board blocks both tokens without changing either board cap.
    game = _game()
    owner, opponent = game.player1, game.player2
    existing = [opponent.summon(WISP) for _ in range(7)]
    leeroy = owner.give("EX1_116").play()
    assert leeroy in owner.field and leeroy.zone == Zone.PLAY
    assert len(opponent.field) == 7 and all(m in opponent.field for m in existing)
    assert not [m for m in opponent.field if m.id == "EX1_116t"]


def test_ex1_577_the_beast_deathrattle_uses_opponent_capacity():
    # Owner's board is full; an open enemy slot receives exactly one Finkle.
    game = _game()
    owner, opponent = game.player1, game.player2
    for _ in range(6):
        owner.summon(WISP)
    beast = owner.give("EX1_577").play()
    enemies = [opponent.summon(WISP) for _ in range(6)]
    assert len(owner.field) == 7 and beast in owner.field
    game.end_turn()
    opponent.give(FIREBALL).play(target=beast)
    opponent.give(MOONFIRE).play(target=beast)
    finkles = [m for m in opponent.field if m.id == "EX1_finkle"]
    assert beast.zone == Zone.GRAVEYARD and all(m in opponent.field for m in enemies)
    assert len(opponent.field) == 7 and len(finkles) == 1
    assert finkles[0].controller is opponent and (finkles[0].atk, finkles[0].health) == (3, 3)

    # A full opponent board suppresses the Deathrattle summon.
    game = _game()
    owner, opponent = game.player1, game.player2
    beast = owner.give("EX1_577").play()
    enemies = [opponent.summon(WISP) for _ in range(7)]
    game.end_turn()
    opponent.give(FIREBALL).play(target=beast)
    opponent.give(MOONFIRE).play(target=beast)
    assert beast.zone == Zone.GRAVEYARD
    assert len(opponent.field) == 7 and all(m in opponent.field for m in enemies)
    assert not [m for m in opponent.field if m.id == "EX1_finkle"]


def test_fp1_019_poison_seeds_replaces_full_boards_for_each_controller():
    game = _game(CardClass.DRUID)
    owner, opponent = game.player1, game.player2
    original_owner = [owner.summon("CS2_182") for _ in range(7)]
    original_opponent = [opponent.summon("CS2_182") for _ in range(7)]
    spell = owner.give("FP1_019").play()

    owner_treants = [m for m in owner.field if m.id == "FP1_019t"]
    opponent_treants = [m for m in opponent.field if m.id == "FP1_019t"]
    assert spell.zone == Zone.GRAVEYARD
    assert all(m.zone == Zone.GRAVEYARD for m in original_owner + original_opponent)
    assert len(owner.field) == len(opponent.field) == 7
    assert len(owner_treants) == len(opponent_treants) == 7
    assert all((m.atk, m.health, m.controller) == (2, 2, owner) for m in owner_treants)
    assert all((m.atk, m.health, m.controller) == (2, 2, opponent) for m in opponent_treants)
    assert owner.mana == 6

    # Unequal, smaller boards keep their respective replacement counts.
    game = _game(CardClass.DRUID)
    owner, opponent = game.player1, game.player2
    originals = [owner.summon(WISP) for _ in range(2)] + [opponent.summon(WISP)]
    spell = owner.give("FP1_019").play()
    assert spell.zone == Zone.GRAVEYARD and all(m.zone == Zone.GRAVEYARD for m in originals)
    assert len([m for m in owner.field if m.id == "FP1_019t"]) == 2
    assert len([m for m in opponent.field if m.id == "FP1_019t"]) == 1


def test_ung_926_cornered_sentry_summons_for_opponent_and_caps_at_seven():
    # Friendly Sentry fills its controller's board but opponent gets all three.
    game = _game(CardClass.WARRIOR)
    owner, opponent = game.player1, game.player2
    for _ in range(6):
        owner.summon(WISP)
    for _ in range(4):
        opponent.summon(WISP)
    sentry = owner.give("UNG_926").play()
    raptors = [m for m in opponent.field if m.id == "UNG_076t1"]
    assert sentry in owner.field and sentry.taunt and len(owner.field) == 7
    assert len(opponent.field) == 7 and len(raptors) == 3
    assert all(m.controller is opponent and (m.atk, m.health) == (1, 1) for m in raptors)

    # A full enemy board receives no Raptor and remains within its cap.
    game = _game(CardClass.WARRIOR)
    owner, opponent = game.player1, game.player2
    enemies = [opponent.summon(WISP) for _ in range(7)]
    sentry = owner.give("UNG_926").play()
    assert sentry in owner.field and sentry.taunt
    assert len(opponent.field) == 7 and all(m in opponent.field for m in enemies)
    assert not [m for m in opponent.field if m.id == "UNG_076t1"]

    # A single remaining enemy slot accepts only one of the three Raptors.
    game = _game(CardClass.WARRIOR)
    owner, opponent = game.player1, game.player2
    for _ in range(6):
        opponent.summon(WISP)
    sentry = owner.give("UNG_926").play()
    raptors = [m for m in opponent.field if m.id == "UNG_076t1"]
    assert sentry in owner.field and len(opponent.field) == 7
    assert len(raptors) == 1 and (raptors[0].atk, raptors[0].health) == (1, 1)


def test_loot_154_gravelsnout_knight_summon_uses_enemy_capacity():
    # Battlecry still summons a random 1-Cost minion as its own board fills.
    game = _game()
    owner, opponent = game.player1, game.player2
    for _ in range(6):
        owner.summon(WISP)
    existing = [opponent.summon(WISP) for _ in range(6)]
    knight = owner.give("LOOT_154").play()
    summoned = [m for m in opponent.field if m not in existing]
    assert knight in owner.field and len(owner.field) == 7
    assert len(opponent.field) == 7 and len(summoned) == 1
    assert summoned[0].controller is opponent and summoned[0].zone == Zone.PLAY
    assert CardType(summoned[0].type) == CardType.MINION and summoned[0].cost == 1

    # With no enemy slot, no random minion is added.
    game = _game()
    owner, opponent = game.player1, game.player2
    existing = [opponent.summon(WISP) for _ in range(7)]
    knight = owner.give("LOOT_154").play()
    assert knight in owner.field and knight.zone == Zone.PLAY
    assert len(opponent.field) == 7 and all(m in opponent.field for m in existing)


def test_loot_357_marin_summons_chest_for_opponent_and_obeys_capacity():
    game = _game()
    owner, opponent = game.player1, game.player2
    for _ in range(6):
        owner.summon(WISP)
    for _ in range(6):
        opponent.summon(WISP)
    marin = owner.give("LOOT_357").play()
    chests = [m for m in opponent.field if m.id == "LOOT_357l"]
    assert marin in owner.field and len(owner.field) == 7
    assert len(opponent.field) == 7 and len(chests) == 1
    assert chests[0].controller is opponent and (chests[0].atk, chests[0].health) == (0, 8)
    chests[0].destroy()
    treasures = [m for m in owner.hand if m.id in {"LOOT_998h", "LOOT_998j", "LOOT_998l", "LOOT_998k"}]
    assert chests[0].zone == Zone.GRAVEYARD and len(treasures) == 1
    assert treasures[0].zone == Zone.HAND
    assert not [m for m in opponent.hand if m.id in {"LOOT_998h", "LOOT_998j", "LOOT_998l", "LOOT_998k"}]

    # A full enemy board blocks only the Chest summon; Marin remains in play.
    game = _game()
    owner, opponent = game.player1, game.player2
    existing = [opponent.summon(WISP) for _ in range(7)]
    marin = owner.give("LOOT_357").play()
    assert marin in owner.field and marin.zone == Zone.PLAY
    assert len(opponent.field) == 7 and all(m in opponent.field for m in existing)
    assert not [m for m in opponent.field if m.id == "LOOT_357l"]


def test_loot_383_hungry_ettin_summon_uses_enemy_capacity():
    # Ettin fills the friendly seventh slot and gives one legal 2-Cost minion.
    game = _game()
    owner, opponent = game.player1, game.player2
    for _ in range(6):
        owner.summon(WISP)
    existing = [opponent.summon(WISP) for _ in range(6)]
    ettin = owner.give("LOOT_383").play()
    summoned = [m for m in opponent.field if m not in existing]
    assert ettin in owner.field and len(owner.field) == 7
    assert (ettin.atk, ettin.health, ettin.taunt) == (4, 10, True)
    assert len(opponent.field) == 7 and len(summoned) == 1
    assert summoned[0].controller is opponent and summoned[0].zone == Zone.PLAY
    assert CardType(summoned[0].type) == CardType.MINION and summoned[0].cost == 2

    # A full opponent board prevents the Battlecry from making an eighth minion.
    game = _game()
    owner, opponent = game.player1, game.player2
    existing = [opponent.summon(WISP) for _ in range(7)]
    ettin = owner.give("LOOT_383").play()
    assert ettin in owner.field and ettin.taunt
    assert len(opponent.field) == 7 and all(m in opponent.field for m in existing)
