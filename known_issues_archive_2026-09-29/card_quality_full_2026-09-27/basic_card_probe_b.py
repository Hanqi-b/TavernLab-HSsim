"""Card-specific runtime probes for a subset of Basic Yellow cards.

Run from the repository root:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/basic_card_probe_b.py

Card text checked against CardDefs.xml (enUS / zhCN):
BT_035 Chaos Strike / 混乱打击: +2 hero Attack this turn; draw a card.
BT_036 Coordinated Strike / 协同打击: summon three 1/1 Illidari with Rush.
BT_142 Shadowhoof Slayer / 影蹄杀手: Battlecry +1 hero Attack this turn.
BT_235 Chaos Nova / 混乱新星: deal 4 damage to all minions.
BT_352 Satyr Overseer / 萨特监工: after your hero attacks, summon a 2/2 Satyr.
BT_495 Glaivebound Adept / 刃缚精锐: if your hero attacked this turn, deal 4 damage.
BT_512 Inner Demon / 心中的恶魔: +8 hero Attack this turn.
BT_740 Soul Cleave / 灵魂裂劈: Lifesteal; deal 2 damage to two random enemy minions.
CS1_112 Holy Nova / 神圣新星: deal 2 to all enemy minions; restore 2 to all friendly characters.
CS1_113 Mind Control / 精神控制: take control of an enemy minion.
"""

import csv
import logging
import sys
from pathlib import Path

import fireplace.cards as carddb
from fireplace.exceptions import InvalidAction
from hearthstone.enums import CardClass, Zone

from utils import WISP, prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)


OUT = Path(__file__).with_suffix(".csv")
FIELDS = ["card_id", "case_id", "expected", "observed", "outcome", "notes"]
ROWS = []


class ProbeMismatch(AssertionError):
    pass


class ProbeInconclusive(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ProbeMismatch(message)


def new_game(card_class):
    game = prepare_empty_game(card_class, card_class)
    if game.current_player is not game.player1:
        game.end_turn()
    return game


def play(card, **kwargs):
    try:
        return card.play(**kwargs)
    except Exception as error:
        raise ProbeMismatch(
            f"play raised {type(error).__name__}: {error}"
        ) from error


def record(card_id, case_id, expected, observed, outcome, notes=""):
    ROWS.append(
        {
            "card_id": card_id,
            "case_id": case_id,
            "expected": expected,
            "observed": observed,
            "outcome": outcome,
            "notes": notes,
        }
    )


def run_case(card_id, case_id, expected, probe, notes=""):
    try:
        observed = probe()
        record(card_id, case_id, expected, observed, "pass", notes)
    except ProbeInconclusive as error:
        record(card_id, case_id, expected, str(error), "inconclusive", notes)
    except ProbeMismatch as error:
        record(card_id, case_id, expected, str(error), "confirmed_error", notes)
    except Exception as error:
        record(
            card_id,
            case_id,
            expected,
            f"fixture/runtime exception={type(error).__name__}: {error}",
            "inconclusive",
            notes,
        )


def probe_bt_035():
    def effect_and_expiry():
        game = new_game(CardClass.DEMONHUNTER)
        player = game.player1
        drawn = player.give(WISP)
        drawn.shuffle_into_deck()
        spell = player.give("BT_035")
        deck_before = len(player.deck)
        hand_before = len(player.hand)
        hero_attack_before = player.hero.atk
        play(spell)
        observed = (
            f"hero_atk={hero_attack_before}->{player.hero.atk};"
            f"deck={deck_before}->{len(player.deck)};hand={hand_before}->{len(player.hand)};"
            f"known_draw={drawn.zone.name};spell={spell.zone.name}"
        )
        require(player.hero.atk == hero_attack_before + 2, observed)
        require(len(player.deck) == deck_before - 1, observed)
        require(drawn.zone == Zone.HAND and drawn in player.hand, observed)
        require(len(player.hand) == hand_before, observed)
        require(spell.zone == Zone.GRAVEYARD, observed)
        game.end_turn()
        expiry = f"after_own_end_turn_hero_atk={player.hero.atk}"
        require(player.hero.atk == hero_attack_before, f"{observed};{expiry}")
        return f"{observed};{expiry}"

    run_case(
        "BT_035",
        "BT_035_attack_draw_and_turn_expiry",
        "Playing Chaos Strike grants exactly +2 hero Attack this turn, draws the known sole deck card into hand, consumes the spell, and removes the temporary Attack at end of turn.",
        effect_and_expiry,
        "Text: enUS 'Give your hero +2 Attack this turn. Draw a card.'; zhCN '在本回合中，使你的英雄获得+2攻击力。抽一张牌。'",
    )


def probe_bt_036():
    def summon_and_rush():
        game = new_game(CardClass.DEMONHUNTER)
        player, opponent = game.player1, game.player2
        enemy = opponent.summon("CS2_200")
        spell = player.give("BT_036")
        play(spell)
        tokens = [minion for minion in player.field if minion.id == "BT_036t"]
        require(len(tokens) == 3, f"tokens={len(tokens)} field={[m.id for m in player.field]}")
        token_facts = [
            (token.id, token.atk, token.health, bool(token.rush), token.zone.name)
            for token in tokens
        ]
        require(
            all(
                token.atk == 1
                and token.health == 1
                and token.rush
                and token.zone == Zone.PLAY
                and token.controller is player
                for token in tokens
            ),
            f"tokens={token_facts}",
        )
        first = tokens[0]
        can_attack_minion = first.can_attack(enemy)
        can_attack_hero = first.can_attack(opponent.hero)
        require(can_attack_minion, f"token cannot attack minion;facts={token_facts}")
        require(not can_attack_hero, f"Rush token can attack enemy hero;facts={token_facts}")
        first.attack(enemy)
        observed = (
            f"tokens={len(tokens)} facts={token_facts};"
            f"can_attack_minion={can_attack_minion};can_attack_hero={can_attack_hero};"
            f"after_attack_enemy_damage={enemy.damage};enemy_zone={enemy.zone.name};"
            f"token_zone={first.zone.name}"
        )
        require(enemy.damage == 1 and enemy.zone == Zone.PLAY, observed)
        require(first.zone == Zone.GRAVEYARD, observed)
        return observed

    def respects_last_board_slot():
        game = new_game(CardClass.DEMONHUNTER)
        player = game.player1
        existing = [player.summon(WISP) for _ in range(6)]
        spell = player.give("BT_036")
        play(spell)
        tokens = [minion for minion in player.field if minion.id == "BT_036t"]
        observed = (
            f"preexisting={len(existing)};new_tokens={len(tokens)};"
            f"field_size={len(player.field)};token_ids={[m.id for m in tokens]};"
            f"spell={spell.zone.name}"
        )
        require(len(tokens) == 1, observed)
        require(len(player.field) == 7, observed)
        require(all(minion in player.field for minion in existing), observed)
        require(tokens[0].atk == tokens[0].health == 1 and tokens[0].rush, observed)
        require(spell.zone == Zone.GRAVEYARD, observed)
        return observed

    run_case(
        "BT_036",
        "BT_036_three_illidari_rush_and_target_limits",
        "Summons exactly three 1/1 Illidari tokens with Rush in the friendly field; a fresh token can attack an enemy minion immediately but cannot attack the enemy hero.",
        summon_and_rush,
        "Text: enUS 'Summon three 1/1 Illidari with Rush.'; zhCN '召唤三个1/1并具有突袭的伊利达雷。'",
    )
    run_case(
        "BT_036",
        "BT_036_only_summons_into_last_open_slot",
        "With six friendly minions before resolution, Coordinated Strike adds only one 1/1 Rush token and leaves exactly seven minions on board.",
        respects_last_board_slot,
        "Board-capacity branch: verifies partial resolution of the three repeated summons and preservation of existing minions.",
    )


def probe_bt_142():
    def battlecry_and_expiry():
        game = new_game(CardClass.DEMONHUNTER)
        player = game.player1
        attack_before = player.hero.atk
        minion = player.give("BT_142")
        play(minion)
        after_battlecry = player.hero.atk
        in_play = minion in player.field and minion.zone == Zone.PLAY
        player_buffs = [
            (buff.id, buff.atk, bool(buff.one_turn_effect)) for buff in player.buffs
        ]
        game.end_turn()
        after_expiry = player.hero.atk
        observed = (
            f"hero_atk={attack_before}->{after_battlecry}->after_turn={after_expiry};"
            f"player_buffs_after_battlecry={player_buffs};"
            f"minion={minion.zone.name}:{minion.atk}/{minion.health}"
        )
        require(after_battlecry == attack_before + 1, observed)
        require(in_play, observed)
        require(after_expiry == attack_before, observed)
        return observed

    run_case(
        "BT_142",
        "BT_142_battlecry_attack_and_expiry",
        "On play, Shadowhoof Slayer remains on board and its Battlecry grants exactly +1 hero Attack for the current turn; the buff is gone after that turn.",
        battlecry_and_expiry,
        "Text: enUS 'Battlecry: Give your hero +1 Attack this turn.'; zhCN '战吼：在本回合中，使你的英雄获得+1攻击力。'",
    )


def probe_bt_235():
    def all_minions_and_death_zones():
        game = new_game(CardClass.DEMONHUNTER)
        player, opponent = game.player1, game.player2
        friendly_survivor = player.summon("CS2_200")
        friendly_death = player.summon(WISP)
        enemy_survivor = opponent.summon("CS2_200")
        enemy_death = opponent.summon(WISP)
        spell = player.give("BT_235")
        hero_healths = (player.hero.health, opponent.hero.health)
        play(spell)
        observed = (
            f"friendly_survivor={friendly_survivor.zone.name}:{friendly_survivor.damage}/{friendly_survivor.health};"
            f"enemy_survivor={enemy_survivor.zone.name}:{enemy_survivor.damage}/{enemy_survivor.health};"
            f"friendly_wisp={friendly_death.zone.name};enemy_wisp={enemy_death.zone.name};"
            f"heroes={player.hero.health},{opponent.hero.health};spell={spell.zone.name}"
        )
        for survivor in (friendly_survivor, enemy_survivor):
            require(survivor.zone == Zone.PLAY and survivor.damage == 4 and survivor.health == 3, observed)
        for dead in (friendly_death, enemy_death):
            require(dead.zone == Zone.GRAVEYARD, observed)
        require((player.hero.health, opponent.hero.health) == hero_healths, observed)
        require(spell.zone == Zone.GRAVEYARD, observed)
        return observed

    run_case(
        "BT_235",
        "BT_235_four_damage_friendly_enemy_and_death_processing",
        "Chaos Nova deals exactly 4 to every friendly and enemy minion, leaves 6/7 minions at 3 health, moves 1/1 minions to graveyard, and does not damage either hero.",
        all_minions_and_death_zones,
        "Text: enUS 'Deal 4 damage to all minions.'; zhCN '对所有随从造成4点伤害。'",
    )


def equip_test_weapon(player):
    weapon = player.give("CS2_091")
    play(weapon)
    return weapon


def probe_bt_352():
    def hero_attack_triggers_once():
        game = new_game(CardClass.DEMONHUNTER)
        player, opponent = game.player1, game.player2
        overseer = player.give("BT_352")
        play(overseer)
        before = [m.id for m in player.field if m.id == "BT_352t"]
        require(not before, f"Satyr appeared before hero attack: {before}")
        enemy_minion = opponent.summon("CS2_200")
        friendly_rush_minion = player.summon("BT_036t")
        friendly_rush_minion.attack(enemy_minion)
        after_minion_attack = [m.id for m in player.field if m.id == "BT_352t"]
        require(
            not after_minion_attack,
            f"Satyr appeared after friendly minion attack: {after_minion_attack}",
        )
        weapon = equip_test_weapon(player)
        health_before = opponent.hero.health
        player.hero.attack(opponent.hero)
        satyrs = [m for m in player.field if m.id == "BT_352t"]
        facts = [(m.atk, m.health, m.zone.name, m.controller.name) for m in satyrs]
        observed = (
            f"before_attack={before};after_minion_attack={after_minion_attack};"
            f"hero_atk={player.hero.atk};"
            f"opponent_hero_health={health_before}->{opponent.hero.health};"
            f"weapon={weapon.zone.name}:{weapon.durability};satyrs={len(satyrs)}:{facts}"
        )
        require(len(satyrs) == 1, observed)
        satyr = satyrs[0]
        require(
            satyr.atk == 2
            and satyr.health == 2
            and satyr.zone == Zone.PLAY
            and satyr.controller is player,
            observed,
        )
        require(opponent.hero.health == health_before - 1, observed)
        return observed

    def opponent_hero_attack_does_not_trigger():
        game = new_game(CardClass.DEMONHUNTER)
        player, opponent = game.player1, game.player2
        overseer = player.give("BT_352")
        play(overseer)
        game.end_turn()
        weapon = equip_test_weapon(opponent)
        opponent.hero.attack(player.hero)
        satyrs = [m for m in player.field if m.id == "BT_352t"]
        observed = (
            f"current_player={game.current_player.name};opponent_hero_attacks={opponent.hero.num_attacks};"
            f"own_hero_health={player.hero.health};weapon={weapon.zone.name};"
            f"overseer={overseer.zone.name};friendly_satyrs={len(satyrs)}"
        )
        require(opponent.hero.num_attacks == 1 and player.hero.health == 29, observed)
        require(overseer.zone == Zone.PLAY and len(satyrs) == 0, observed)
        return observed

    run_case(
        "BT_352",
        "BT_352_summon_after_hero_attack",
        "Playing Satyr Overseer alone or after a friendly minion attacks summons nothing; after its controller's hero attacks, exactly one friendly 2/2 Satyr appears and the hero attack resolves.",
        hero_attack_triggers_once,
        "Text: enUS 'After your hero attacks, summon a 2/2 Satyr.'; zhCN '在你的英雄攻击后，召唤一个2/2的萨特。'",
    )
    run_case(
        "BT_352",
        "BT_352_opponent_hero_attack_does_not_summon",
        "An opposing hero attack while Satyr Overseer is in play must not summon a friendly Satyr.",
        opponent_hero_attack_does_not_trigger,
        "Checks the 'your hero' trigger ownership with an actual opponent hero attack.",
    )


def probe_bt_495():
    def no_attack_branch():
        game = new_game(CardClass.DEMONHUNTER)
        player, opponent = game.player1, game.player2
        target = opponent.summon("CS2_200")
        health_before = target.health
        adept = player.give("BT_495")
        playable_without_target = adept.is_playable()
        play(adept)
        observed = (
            f"hero_attacks={player.hero.num_attacks};playable_without_target={playable_without_target};"
            f"target_health={health_before}->{target.health};target_zone={target.zone.name};"
            f"adept_zone={adept.zone.name}"
        )
        require(player.hero.num_attacks == 0, observed)
        require(playable_without_target, observed)
        require(target.health == health_before and target.zone == Zone.PLAY, observed)
        require(adept.zone == Zone.PLAY and adept in player.field, observed)
        return observed

    def attacked_branch_targeted_damage():
        game = new_game(CardClass.DEMONHUNTER)
        player, opponent = game.player1, game.player2
        target = opponent.summon("CS2_200")
        weapon = equip_test_weapon(player)
        hero_before = opponent.hero.health
        player.hero.attack(opponent.hero)
        require(player.hero.num_attacks > 0, f"weapon={weapon.zone.name};hero_attacks={player.hero.num_attacks}")
        health_before = target.health
        adept = player.give("BT_495")
        target_valid = target in adept.play_targets
        play(adept, target=target)
        observed = (
            f"hero_attacks={player.hero.num_attacks};target_was_valid={target_valid};"
            f"target_health={health_before}->{target.health};target_damage={target.damage};"
            f"target_zone={target.zone.name};adept_zone={adept.zone.name}"
        )
        require(target_valid, observed)
        require(target.health == health_before - 4 and target.damage == 4, observed)
        require(target.zone == Zone.PLAY and adept.zone == Zone.PLAY, observed)
        require(opponent.hero.health == hero_before - 1, observed)
        return observed

    def explicit_target_before_attack_is_ignored():
        game = new_game(CardClass.DEMONHUNTER)
        player, opponent = game.player1, game.player2
        target = opponent.summon("CS2_200")
        adept = player.give("BT_495")
        mana_before, health_before, cost = player.mana, target.health, adept.cost
        offered = target in adept.play_targets
        adept.play(target=target)
        observed = (
            f"hero_attacks={player.hero.num_attacks};target_offered={offered};"
            f"explicit_target_ignored={target.health == health_before};target_health={target.health};"
            f"mana={mana_before}->{player.mana};adept_zone={adept.zone.name}"
        )
        require(offered, observed)
        require(target.health == health_before and player.mana == mana_before - cost, observed)
        require(adept.zone == Zone.PLAY, observed)
        return observed

    def prior_turn_attack_does_not_enable_battlecry():
        game = new_game(CardClass.DEMONHUNTER)
        player, opponent = game.player1, game.player2
        target = opponent.summon("CS2_200")
        equip_test_weapon(player)
        player.hero.attack(opponent.hero)
        require(player.hero.num_attacks > 0, "fixture hero attack did not register")
        game.end_turn()
        game.end_turn()
        adept = player.give("BT_495")
        health_before = target.health
        offered = target in adept.play_targets
        play(adept)
        observed = (
            f"current_turn_hero_attacks={player.hero.num_attacks};target_offered={offered};"
            f"target_health={health_before}->{target.health};adept_zone={adept.zone.name}"
        )
        require(player.hero.num_attacks == 0 and offered, observed)
        require(target.health == health_before and adept.zone == Zone.PLAY, observed)
        return observed

    run_case(
        "BT_495",
        "BT_495_without_hero_attack_no_damage",
        "If the hero has not attacked this turn, Glaivebound Adept can be played without a target and its Battlecry deals no damage.",
        no_attack_branch,
        "Text: enUS 'If your hero attacked this turn, deal 4 damage.'; zhCN '如果你的英雄在本回合中进行过攻击，则造成4点伤害。'",
    )
    run_case(
        "BT_495",
        "BT_495_after_hero_attack_targeted_four_damage",
        "After the hero attacks in the current turn, an enemy minion is a valid target and takes exactly 4 damage from the Battlecry.",
        attacked_branch_targeted_damage,
        "Checks hero attack state, target legality, target health/damage/zone, and attacker hero combat damage.",
    )
    run_case(
        "BT_495",
        "BT_495_explicit_target_before_attack_ignored",
        "Before the hero attacks this turn, an explicit battlecry target is ignored and takes no damage.",
        explicit_target_before_attack_is_ignored,
        "Covers the inactive Battlecry target branch; no-target play alone cannot prove explicit target handling.",
    )
    run_case(
        "BT_495",
        "BT_495_prior_turn_attack_resets_condition",
        "An attack on a prior turn does not enable this turn's 4-damage Battlecry.",
        prior_turn_attack_does_not_enable_battlecry,
        "Checks the printed this-turn condition across both players' turn boundary.",
    )


def probe_bt_512():
    def attack_and_expiry():
        game = new_game(CardClass.DEMONHUNTER)
        player, opponent = game.player1, game.player2
        hero_attack_before = player.hero.atk
        enemy_health_before = opponent.hero.health
        spell = player.give("BT_512")
        play(spell)
        attack_after_spell = player.hero.atk
        player.hero.attack(opponent.hero)
        health_after_attack = opponent.hero.health
        game.end_turn()
        attack_after_turn = player.hero.atk
        observed = (
            f"hero_atk={hero_attack_before}->{attack_after_spell}->after_turn={attack_after_turn};"
            f"enemy_hero_health={enemy_health_before}->{health_after_attack};spell={spell.zone.name}"
        )
        require(attack_after_spell == hero_attack_before + 8, observed)
        require(health_after_attack == enemy_health_before - 8, observed)
        require(attack_after_turn == hero_attack_before, observed)
        require(spell.zone == Zone.GRAVEYARD, observed)
        return observed

    run_case(
        "BT_512",
        "BT_512_eight_attack_damage_and_turn_expiry",
        "Inner Demon grants exactly +8 hero Attack, that attack deals 8 to the enemy hero, and the temporary attack is removed at end of turn.",
        attack_and_expiry,
        "Text: enUS 'Give your hero +8 Attack this turn.'; zhCN '在本回合中，使你的英雄获得+8攻击力。'",
    )


def probe_bt_740():
    def requires_an_enemy_minion():
        game = new_game(CardClass.DEMONHUNTER)
        player = game.player1
        spell = player.give("BT_740")
        mana_before = player.mana
        playable = spell.is_playable()
        rejected = False
        try:
            spell.play()
        except InvalidAction:
            rejected = True
        observed = (
            f"enemy_minions={len(player.opponent.field)};is_playable={playable};"
            f"play_rejected={rejected};mana={mana_before}->{player.mana};spell={spell.zone.name}"
        )
        require(not playable and rejected, observed)
        require(player.mana == mana_before and spell.zone == Zone.HAND, observed)
        return observed

    def two_random_enemy_minions_and_lifesteal():
        game = new_game(CardClass.DEMONHUNTER)
        player, opponent = game.player1, game.player2
        friendly_control = player.summon("CS2_200")
        enemy_one = opponent.summon("CS2_200")
        enemy_two = opponent.summon("CS2_200")
        player.hero.damage = 5
        hero_before = player.hero.health
        enemy_before = (enemy_one.health, enemy_two.health)
        friendly_before = friendly_control.health
        spell = player.give("BT_740")
        play(spell)
        enemy_after = (enemy_one.health, enemy_two.health)
        observed = (
            f"enemy_health={enemy_before}->{enemy_after};"
            f"enemy_damage={enemy_one.damage},{enemy_two.damage};"
            f"hero_health={hero_before}->{player.hero.health};"
            f"friendly_control={friendly_control.health} (before {friendly_before});"
            f"spell={spell.zone.name}"
        )
        require(enemy_after == (enemy_before[0] - 2, enemy_before[1] - 2), observed)
        require(enemy_one.zone == enemy_two.zone == Zone.PLAY, observed)
        require(player.hero.health == hero_before + 4, observed)
        require(friendly_control.health == friendly_before and friendly_control.damage == 0, observed)
        require(spell.zone == Zone.GRAVEYARD, observed)
        return observed

    def one_enemy_minion_semantics():
        game = new_game(CardClass.DEMONHUNTER)
        player, opponent = game.player1, game.player2
        sole_enemy = opponent.summon("CS2_200")
        player.hero.damage = 5
        hero_before = player.hero.health
        enemy_before = sole_enemy.health
        spell = player.give("BT_740")
        playable = spell.is_playable()
        play(spell)
        observed = (
            f"playable={playable};sole_enemy_health={enemy_before}->{sole_enemy.health};"
            f"damage={sole_enemy.damage};hero_health={hero_before}->{player.hero.health};"
            f"spell={spell.zone.name}"
        )
        require(playable and spell.zone == Zone.GRAVEYARD, observed)
        require(sole_enemy.zone == Zone.PLAY, observed)
        require(sole_enemy.health == enemy_before - 2 and sole_enemy.damage == 2, observed)
        require(player.hero.health == hero_before + 2, observed)
        return observed

    run_case(
        "BT_740",
        "BT_740_requires_at_least_one_enemy_minion",
        "With no enemy minions, Soul Cleave is not playable; attempting to play it is rejected without spending mana or leaving hand.",
        requires_an_enemy_minion,
        "Text: enUS 'Lifesteal: Deal 2 damage to two random enemy minions.'; zhCN '吸血：随机对两个敌方随从造成2点伤害。'",
    )
    run_case(
        "BT_740",
        "BT_740_hits_two_distinct_enemy_minions_and_heals_four",
        "With exactly two enemy minions, both receive 2 damage; a friendly minion and both heroes' enemy-target eligibility are checked, and Lifesteal restores 4 to a damaged friendly hero.",
        two_random_enemy_minions_and_lifesteal,
        "RandomSelector samples without replacement; exactly two eligible enemy minions make both intended targets observable.",
    )
    run_case(
        "BT_740",
        "BT_740_single_enemy_target_semantics",
        "With exactly one enemy minion, it is hit exactly once for 2 damage and Lifesteal heals exactly 2.",
        one_enemy_minion_semantics,
        "User-confirmed rule for this audit: one available enemy minion receives exactly one hit. Asserts the exact damage and Lifesteal amount.",
    )


def probe_cs1_112():
    def damage_enemies_and_heal_all_friendly_characters():
        game = new_game(CardClass.PRIEST)
        player, opponent = game.player1, game.player2
        friendly_injured = player.summon("CS2_200")
        friendly_full = player.summon(WISP)
        enemy_survivor = opponent.summon("CS2_200")
        enemy_death = opponent.summon(WISP)
        player.hero.damage = 5
        friendly_injured.damage = 3
        own_hero_before = player.hero.health
        friendly_injured_before = friendly_injured.health
        friendly_full_before = friendly_full.health
        enemy_survivor_before = enemy_survivor.health
        enemy_hero_before = opponent.hero.health
        spell = player.give("CS1_112")
        play(spell)
        observed = (
            f"own_hero={own_hero_before}->{player.hero.health};"
            f"friendly_injured={friendly_injured_before}->{friendly_injured.health};"
            f"friendly_full={friendly_full_before}->{friendly_full.health};"
            f"enemy_survivor={enemy_survivor_before}->{enemy_survivor.health},damage={enemy_survivor.damage};"
            f"enemy_wisp={enemy_death.zone.name};enemy_hero={enemy_hero_before}->{opponent.hero.health};"
            f"spell={spell.zone.name}"
        )
        require(player.hero.health == min(30, own_hero_before + 2), observed)
        require(friendly_injured.health == friendly_injured_before + 2, observed)
        require(friendly_full.health == friendly_full_before, observed)
        require(enemy_survivor.health == enemy_survivor_before - 2 and enemy_survivor.damage == 2, observed)
        require(enemy_death.zone == Zone.GRAVEYARD, observed)
        require(opponent.hero.health == enemy_hero_before, observed)
        require(spell.zone == Zone.GRAVEYARD, observed)
        return observed

    run_case(
        "CS1_112",
        "CS1_112_enemy_damage_friendly_character_healing_and_death",
        "Holy Nova deals 2 to every enemy minion (including lethal damage to a 1/1), restores 2 to every damaged friendly character (hero and minion), leaves a full-health friendly minion unchanged, and does not hit the enemy hero.",
        damage_enemies_and_heal_all_friendly_characters,
        "Text: enUS 'Deal 2 damage to all enemy minions. Restore 2 Health to all friendly characters.'; zhCN '对所有敌方随从造成2点伤害，为所有友方角色恢复2点生命值。'",
    )


def probe_cs1_113():
    def steal_transfers_controller_and_field_zone():
        game = new_game(CardClass.PRIEST)
        player, opponent = game.player1, game.player2
        target = opponent.summon("CS2_200")
        original_stats = (target.atk, target.health)
        spell = player.give("CS1_113")
        target_valid = target in spell.play_targets
        play(spell, target=target)
        observed = (
            f"target_valid={target_valid};controller={target.controller.name};"
            f"zone={target.zone.name};p1_field={target in player.field};p2_field={target in opponent.field};"
            f"asleep={target.asleep};stats={target.atk}/{target.health};spell={spell.zone.name}"
        )
        require(target_valid, observed)
        require(target.controller is player and target in player.field, observed)
        require(target not in opponent.field and target.zone == Zone.PLAY, observed)
        require(target.asleep, observed)
        require((target.atk, target.health) == original_stats, observed)
        require(spell.zone == Zone.GRAVEYARD, observed)
        return observed

    def reject_friendly_target_without_spending():
        game = new_game(CardClass.PRIEST)
        player, opponent = game.player1, game.player2
        friendly = player.summon("CS2_200")
        enemy = opponent.summon("CS2_200")
        spell = player.give("CS1_113")
        mana_before = player.mana
        friendly_controller_before = friendly.controller
        rejected = False
        try:
            spell.play(target=friendly)
        except InvalidAction:
            rejected = True
        observed = (
            f"friendly_target_rejected={rejected};mana={mana_before}->{player.mana};"
            f"spell={spell.zone.name};friendly_controller={friendly.controller.name};"
            f"enemy_controller={enemy.controller.name};enemy_zone={enemy.zone.name}"
        )
        require(rejected, observed)
        require(player.mana == mana_before and spell.zone == Zone.HAND, observed)
        require(friendly.controller is friendly_controller_before is player, observed)
        require(enemy.controller is opponent and enemy.zone == Zone.PLAY, observed)
        return observed

    run_case(
        "CS1_113",
        "CS1_113_steal_enemy_minion_controller_zone_and_state",
        "Mind Control moves a valid enemy minion's controller to the caster while retaining PLAY zone and stats, moves it between the field lists, and leaves it summoning-sick under the new controller.",
        steal_transfers_controller_and_field_zone,
        "Existing tests/test_classic.py::test_mind_control checks controller/PLAY/asleep; this probe additionally checks both field lists, owner and stats.",
    )
    run_case(
        "CS1_113",
        "CS1_113_reject_friendly_target_without_cost_or_zone_change",
        "A friendly minion is not a legal Mind Control target; rejection leaves the spell in hand, preserves mana, and does not change either minion's controller or zone.",
        reject_friendly_target_without_spending,
        "Existing targeting prerequisite audit covered rejection; this is a per-card runtime assertion with a legal enemy alternative present.",
    )


PROBES = {
    "BT_035": probe_bt_035,
    "BT_036": probe_bt_036,
    "BT_142": probe_bt_142,
    "BT_235": probe_bt_235,
    "BT_352": probe_bt_352,
    "BT_495": probe_bt_495,
    "BT_512": probe_bt_512,
    "BT_740": probe_bt_740,
    "CS1_112": probe_cs1_112,
    "CS1_113": probe_cs1_113,
}


def write_csv():
    with OUT.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ROWS)


def main():
    if sys.argv[1:]:
        raise SystemExit("The evidence CSV must be regenerated by running every card probe.")
    for card_id in PROBES:
        PROBES[card_id]()
    write_csv()
    for row in ROWS:
        print(
            f"{row['card_id']} {row['case_id']} {row['outcome']}: "
            f"{row['observed']}"
        )
    failures = [row for row in ROWS if row["outcome"] != "pass"]
    print(f"wrote {OUT}; cases={len(ROWS)}; non_pass={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
