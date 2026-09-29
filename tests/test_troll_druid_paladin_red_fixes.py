"""Focused behavior tests for the four remaining TROLL red cards in Druid/Paladin."""

from hearthstone.enums import CardClass, Zone

from fireplace.exceptions import InvalidAction

from utils import MOONFIRE, WISP, prepare_empty_game


def ready_game(owner_class):
    game = prepare_empty_game(owner_class, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
        player.temp_mana = 0
    return game, game.player1, game.player2


def test_savage_striker_uses_hero_attack_and_has_no_target_at_zero_attack():
    _, owner, opponent = ready_game(CardClass.DRUID)
    target = opponent.summon("CS2_182")
    owner.hero.atk = 3
    striker = owner.give("TRL_240")
    assert striker.targets == [target]
    striker.play(target=target)
    assert target.zone == Zone.PLAY
    assert target.health == 2
    assert striker.zone == Zone.PLAY

    zero_game, zero_owner, zero_opponent = ready_game(CardClass.DRUID)
    zero_target = zero_opponent.summon("CS2_182")
    zero_striker = zero_owner.give("TRL_240")
    assert zero_owner.hero.atk == 0
    assert not zero_striker.requires_target()
    zero_striker.play()
    assert zero_target.zone == Zone.PLAY
    assert zero_target.health == 5
    assert zero_striker.zone == Zone.PLAY


def test_gonk_grants_the_hero_one_more_attack_only_after_a_kill():
    game, owner, opponent = ready_game(CardClass.DRUID)
    gonk = owner.give("TRL_241").play()
    owner.give("TRL_243").play()
    victim = opponent.summon(WISP)
    assert owner.hero.can_attack(victim)
    owner.hero.attack(victim)
    assert victim.zone == Zone.GRAVEYARD
    assert gonk.zone == Zone.PLAY
    assert owner.hero.can_attack(opponent.hero)
    assert owner.hero.num_attacks == 0


def test_gonk_does_not_grant_an_attack_when_the_minion_survives():
    _, owner, opponent = ready_game(CardClass.DRUID)
    owner.give("TRL_241").play()
    owner.give("TRL_243").play()
    victim = opponent.summon("CS2_182")
    owner.hero.attack(victim)
    assert victim.zone == Zone.PLAY
    assert owner.hero.num_attacks == 1
    assert not owner.hero.can_attack(opponent.hero)


def test_time_out_protects_hero_from_spell_and_combat_until_next_turn():
    game, owner, opponent = ready_game(CardClass.PALADIN)
    owner.give("TRL_302").play()
    assert owner.hero.immune
    assert owner.hero.cant_be_damaged
    assert owner.hero not in opponent.hero.attack_targets

    game.end_turn()
    before_health = owner.hero.health
    before_mana = opponent.mana
    spell = opponent.give(MOONFIRE)
    try:
        spell.play(target=owner.hero)
    except InvalidAction:
        pass
    else:
        raise AssertionError("an opposing spell must not target a Time Out hero")
    assert spell.zone == Zone.HAND
    assert opponent.mana == before_mana
    assert owner.hero.health == before_health
    try:
        opponent.hero.attack(owner.hero)
    except InvalidAction:
        pass
    else:
        raise AssertionError("an opposing hero must not attack a Time Out hero")
    assert owner.hero.health == before_health

    game.end_turn()
    assert not owner.hero.immune
    assert not owner.hero.cant_be_damaged
    assert owner.hero in opponent.hero.attack_targets

    game.end_turn()
    weapon = opponent.give("CS2_091").play()
    before_attack = owner.hero.health
    opponent.hero.attack(owner.hero)
    assert owner.hero.health == before_attack - weapon.atk
    assert weapon.durability == 3


def test_zandalari_templar_gains_taunt_after_ten_actual_healing():
    _, owner, _ = ready_game(CardClass.PALADIN)
    owner.hero.hit(10)
    restores = [owner.give("TRL_128").play(target=owner.hero) for _ in range(4)]
    templar = owner.give("TRL_545").play()
    assert owner.hero.health == 30
    assert all(card.zone == Zone.GRAVEYARD for card in restores)
    assert (templar.atk, templar.health) == (8, 8)
    assert templar.taunt
    assert templar.zone == Zone.PLAY


def test_zandalari_templar_stays_base_without_ten_actual_healing():
    _, owner, _ = ready_game(CardClass.PALADIN)
    owner.hero.hit(10)
    restores = [owner.give("TRL_128").play(target=owner.hero) for _ in range(3)]
    templar = owner.give("TRL_545").play()
    assert owner.hero.health == 29
    assert all(card.zone == Zone.GRAVEYARD for card in restores)
    assert (templar.atk, templar.health) == (4, 4)
    assert not templar.taunt
    assert templar.zone == Zone.PLAY
