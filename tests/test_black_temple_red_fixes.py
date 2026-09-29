"""Individual behavior tests for Ashes of Outland collectible red cards."""

from hearthstone.enums import CardClass, Zone

from utils import WISP, prepare_empty_game


def ready_game(hero_class=CardClass.MAGE):
    game = prepare_empty_game(hero_class, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_corsair_cache_draws_weapon_from_deck_and_adds_durability():
    _, owner, _ = ready_game(CardClass.WARRIOR)
    weapon = owner.card("CS2_091", zone=Zone.DECK)
    other = owner.card(WISP, zone=Zone.DECK)
    base = weapon.durability
    owner.give("BT_124").play()
    assert weapon.zone == Zone.HAND and weapon.durability == base + 1
    assert other.zone == Zone.DECK


def test_terrorguard_escapee_summons_three_tokens_for_opponent():
    _, owner, opponent = ready_game()
    body = owner.give("BT_159").play()
    tokens = [m for m in opponent.field if m.id == "BT_159t"]
    assert body.zone == Zone.PLAY and body in owner.field
    assert len(tokens) == 3
    assert all((m.atk, m.health, m.zone, m.controller) == (1, 1, Zone.PLAY, opponent) for m in tokens)


def test_kelidan_held_from_prior_turn_destroys_only_selected_minion():
    _, owner, opponent = ready_game(CardClass.WARLOCK)
    ally = owner.summon(WISP)
    target = opponent.summon("CS2_182")
    bystander = opponent.summon(WISP)
    kelidan = owner.give("BT_196").play(target=target)
    assert kelidan.zone == ally.zone == bystander.zone == Zone.PLAY
    assert target.zone == Zone.GRAVEYARD


def test_kelidan_drawn_this_turn_destroys_all_other_minions_without_target():
    _, owner, opponent = ready_game(CardClass.WARLOCK)
    ally = owner.summon("CS2_182")
    enemies = [opponent.summon(WISP), opponent.summon("CS2_182")]
    kelidan = owner.card("BT_196", zone=Zone.DECK)
    owner.draw()
    assert kelidan.zone == Zone.HAND and kelidan.drawn_this_turn
    kelidan.play()
    assert kelidan.zone == Zone.PLAY
    assert ally.zone == Zone.GRAVEYARD
    assert all(m.zone == Zone.GRAVEYARD for m in enemies)


def test_psyche_split_buffs_target_and_summons_buffed_copy():
    _, owner, _ = ready_game(CardClass.PRIEST)
    target = owner.summon(WISP)
    spell = owner.give("BT_253").play(target=target)
    wisps = [m for m in owner.field if m.id == WISP]
    assert spell.zone == Zone.GRAVEYARD and len(wisps) == 2
    assert target in wisps
    assert all((m.atk, m.health, m.max_health) == (2, 3, 3) for m in wisps)


def test_ashtongue_slayer_temporary_buff_expires_after_turn():
    game, owner, _ = ready_game(CardClass.ROGUE)
    target = owner.summon("EX1_522")
    assert target.stealthed
    base = target.atk
    owner.give("BT_702").play(target=target)
    assert target.atk == base + 3 and target.immune
    game.end_turn()
    assert target.atk == base and not target.immune


def test_bonechewer_vanguard_gains_two_attack_per_damage_event():
    _, owner, _ = ready_game()
    body = owner.give("BT_716").play()
    base = body.atk
    body.hit(1)
    assert body.atk == base + 2 and body.zone == Zone.PLAY
    body.hit(1)
    assert body.atk == base + 4 and body.taunt


def test_infectious_sporeling_transforms_damaged_minion_but_not_hero():
    game, owner, opponent = ready_game()
    spore = owner.give("BT_731").play()
    victim = opponent.summon("CS2_182")
    game.end_turn()
    game.end_turn()
    spore.attack(victim)
    transformed = [m for m in opponent.field if m.id == "BT_731"]
    assert len(transformed) == 1 and victim.zone != Zone.PLAY

    second = owner.give("BT_731").play()
    game.end_turn()
    game.end_turn()
    second.attack(opponent.hero)
    assert opponent.hero.zone == Zone.PLAY
    assert opponent.hero.health == 29
    assert len([m for m in opponent.field if m.id == "BT_731"]) == 1
