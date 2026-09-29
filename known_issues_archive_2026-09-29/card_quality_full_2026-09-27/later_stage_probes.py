"""Phase 3-5 representative runtime probes for card quality audit.

Run from the repository root with:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/later_stage_probes.py

These probes assert specific observable effects and state transitions. A pass is
evidence for the tested scenario only; it does not establish correctness for
every card sharing the mechanic.
"""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


FIELDS = ["case_id", "mechanism", "card_ids", "expected", "observed", "outcome"]
ROWS = []


def record(case_id, mechanism, card_ids, expected, observed, outcome):
    ROWS.append(
        dict(
            case_id=case_id,
            mechanism=mechanism,
            card_ids=card_ids,
            expected=expected,
            observed=observed,
            outcome=outcome,
        )
    )


def new_game():
    return prepare_empty_game(CardClass.MAGE, CardClass.MAGE)


def make_current(game, player):
    """Advance naturally until player owns the active turn."""
    if game.current_player is not player:
        game.end_turn()
    return game.current_player is player


def run_case(case_id, mechanism, card_ids, expected, probe):
    try:
        observed, passed = probe()
        outcome = "pass" if passed else "confirmed_error"
    except Exception as error:  # Preserve the complete runtime failure in CSV.
        observed = f"exception={type(error).__name__}: {error}"
        outcome = "confirmed_error"
    record(case_id, mechanism, card_ids, expected, observed, outcome)


def battlecry_probe():
    game = new_game()
    player = game.player1
    make_current(game, player)
    wisp = player.summon("CS2_231")
    before = wisp.atk
    sergeant = player.give("CS2_188")
    legal_target = wisp in sergeant.targets
    sergeant.play(target=wisp)
    buffed = wisp.atk
    game.end_turn()
    observed = (
        f"legal_target={legal_target};wisp_atk={before}->{buffed}->"
        f"{wisp.atk};sergeant_zone={sergeant.zone.name}"
    )
    return observed, legal_target and buffed == before + 2 and wisp.atk == before


def spell_probe():
    game = new_game()
    player, opponent = game.player1, game.player2
    fireball = player.give("CS2_029")
    before = opponent.hero.health
    legal_target = opponent.hero in fireball.targets
    fireball.play(target=opponent.hero)
    observed = (
        f"legal_target={legal_target};enemy_hero={before}->{opponent.hero.health};"
        f"spell_zone={fireball.zone.name};in_graveyard={fireball in player.graveyard}"
    )
    return observed, (
        legal_target
        and opponent.hero.health == before - 6
        and fireball.zone == Zone.GRAVEYARD
        and fireball in player.graveyard
    )


def summon_probe(board_filled=False):
    game = new_game()
    player = game.player1
    if board_filled:
        for _ in range(5):
            player.summon("CS2_231")
    before = len(player.field)
    spell = player.give("BT_173")
    spell.play()
    tokens = [card for card in player.field if card.id == "BT_036t"]
    expected_new = 2 if board_filled else 6
    observed = (
        f"field={before}->{len(player.field)};illidari={len(tokens)};"
        f"all_rush={all(card.rush for card in tokens)};"
        f"all_1_1={all((card.atk, card.health) == (1, 1) for card in tokens)};spell_zone={spell.zone.name}"
    )
    return observed, (
        len(tokens) == expected_new
        and len(player.field) == min(7, before + 6)
        and all(card.rush for card in tokens)
        and all((card.atk, card.health) == (1, 1) for card in tokens)
        and spell.zone == Zone.GRAVEYARD
    )


def draw_probe():
    game = new_game()
    player = game.player1
    # Make the draw contents deterministic while retaining the regular draw path.
    for card_id in ("CS2_231", "CS1_042"):
        player.give(card_id).shuffle_into_deck()
    before_hand = len(player.hand)
    before_deck = len(player.deck)
    spell = player.give("CS2_023")
    spell.play()
    drawn_ids = [card.id for card in player.hand if card.id in {"CS2_231", "CS1_042"}]
    observed = (
        f"hand={before_hand}->{len(player.hand)};deck={before_deck}->{len(player.deck)};"
        f"drawn={sorted(drawn_ids)};spell_zone={spell.zone.name}"
    )
    return observed, (
        len(player.hand) == before_hand + 2
        and len(player.deck) == before_deck - 2
        and sorted(drawn_ids) == ["CS1_042", "CS2_231"]
        and spell.zone == Zone.GRAVEYARD
    )


def discard_probe():
    game = new_game()
    player, opponent = game.player1, game.player2
    minion = opponent.summon("CS1_042")
    spare = player.give("CS2_231")
    spell = player.give("EX1_308")
    before_health = minion.health
    legal_target = minion in spell.targets
    spell.play(target=minion)
    damage_game = new_game()
    damage_owner, damage_opponent = damage_game.player1, damage_game.player2
    damage_spell = damage_owner.give("EX1_308")
    hero_before = damage_opponent.hero.health
    damage_spell.play(target=damage_opponent.hero)
    hero_damage = hero_before - damage_opponent.hero.health
    observed = (
        f"legal_target={legal_target};target_zone={minion.zone.name};"
        f"target_health={before_health}->{minion.health};spare_zone={spare.zone.name};"
        f"spell_zone={spell.zone.name};remaining_hand={[card.id for card in player.hand]};"
        f"hero_damage_control={hero_damage};damage_spell_zone={damage_spell.zone.name}"
    )
    return observed, (
        legal_target
        and minion.zone == Zone.GRAVEYARD
        # Fireplace models discarded cards as removed from game, rather than
        # putting them in the graveyard collection.
        and spare.zone == Zone.REMOVEDFROMGAME
        and spell.zone == Zone.GRAVEYARD
        and len(player.hand) == 0
        and hero_damage == 4
        and damage_spell.zone == Zone.GRAVEYARD
    )


def silence_probe():
    game = new_game()
    player, opponent = game.player1, game.player2
    target = opponent.summon("CS1_042")
    spell = player.give("EX1_332")
    legal_target = target in spell.targets
    before = target.taunt
    spell.play(target=target)
    observed = (
        f"legal_target={legal_target};taunt={before}->{target.taunt};"
        f"target_zone={target.zone.name};silenced={target.silenced};spell_zone={spell.zone.name}"
    )
    return observed, (
        legal_target
        and before
        and not target.taunt
        and target.zone == Zone.PLAY
        and target.silenced
        and spell.zone == Zone.GRAVEYARD
    )


def choose_one_probe(branch):
    game = new_game()
    player = game.player1
    friend = player.summon("CS2_231") if branch == "buff" else None
    spell = player.give("EX1_160")
    choices = [card.id for card in spell.choose_cards]
    choice_id = "EX1_160b" if branch == "buff" else "EX1_160a"
    spell.play(choose=choice_id)
    if branch == "buff":
        effect = f"wisp={friend.atk}/{friend.health}"
        branch_ok = friend.atk == 2 and friend.health == 2
        summoned = 0
    else:
        summons = [card for card in player.field if card.id == "EX1_160t"]
        effect = f"panthers={len(summons)};stats={[f'{c.atk}/{c.health}' for c in summons]}"
        branch_ok = len(summons) == 1 and summons[0].atk == 3 and summons[0].health == 2
        summoned = len(summons)
    observed = (
        f"choices={choices};selected={choice_id};effect={effect};"
        f"pending_choice={player.choice is not None};spell_zone={spell.zone.name}"
    )
    return observed, (
        set(choices) == {"EX1_160a", "EX1_160b"}
        and branch_ok
        and player.choice is None
        and spell.zone == Zone.GRAVEYARD
        and (branch == "buff" or summoned == 1)
    )


def trigger_probe():
    game = new_game()
    player, opponent = game.player1, game.player2
    make_current(game, player)
    wyrm = player.summon("NEW1_012")
    base_atk = wyrm.atk
    own_coin = player.give("GAME_005")
    own_coin.play()
    after_own = wyrm.atk
    make_current(game, opponent)
    enemy_coin = opponent.give("GAME_005")
    enemy_coin.play()
    after_enemy = wyrm.atk
    make_current(game, player)
    silence = player.give("EX1_332")
    silence.play(target=wyrm)
    silenced = wyrm.silenced
    after_silence = wyrm.atk
    after_silence_coin = player.give("GAME_005")
    after_silence_coin.play()
    observed = (
        f"atk={base_atk}->{after_own}->{after_enemy};after_silence={after_silence};"
        f"after_silenced_own_spell={wyrm.atk};"
        f"own_coin_zone={own_coin.zone.name};enemy_coin_zone={enemy_coin.zone.name};"
        f"silenced={silenced};silence_zone={silence.zone.name}"
    )
    return observed, (
        after_own == base_atk + 1
        and after_enemy == after_own
        and silenced
        and after_silence == base_atk
        and wyrm.atk == after_silence
        and all(card.zone == Zone.GRAVEYARD for card in (own_coin, enemy_coin, silence))
    )


def aura_probe():
    game = new_game()
    player = game.player1
    left = player.summon("CS2_231")
    left_base_atk = left.atk
    wolf = player.summon("EX1_162")
    left_during = left.atk
    right = player.summon("CS2_231")
    far = player.summon("CS2_231")
    during = (left.atk, right.atk)
    far_during = far.atk
    order_before_remove = [card.id for card in player.field]
    wolf.destroy()
    after = (left.atk, right.atk)
    far_after = far.atk
    observed = (
        f"positions_before_remove={order_before_remove};"
        f"neighbors_atk=({left_base_atk},{left_base_atk})->"
        f"({left_during},{during[1]})->{during}->{after};"
        f"nonadjacent_atk={far_during}->{far_after};wolf_zone={wolf.zone.name}"
    )
    return observed, (
        left_base_atk == 1
        and during == (2, 2)
        and after == (1, 1)
        and far_during == far_after == 1
        and wolf.zone == Zone.GRAVEYARD
    )


def at073_probe():
    game = new_game()
    player = game.player1
    make_current(game, player)
    secret = player.give("AT_073")
    secret.play()
    wisp = player.summon("CS2_231")
    before = (wisp.atk, wisp.health)
    game.end_turn()
    game.end_turn()
    after = (wisp.atk, wisp.health)
    observed = (
        f"secret_zone={secret.zone.name};in_secrets={secret in player.secrets};"
        f"wisp={before}->{after};turn={game.turn};current_player={game.current_player.name}"
    )
    return observed, (
        secret.zone == Zone.GRAVEYARD
        and secret not in player.secrets
        and after == (before[0] + 1, before[1] + 1)
    )


def counterspell_probe():
    game = new_game()
    player, opponent = game.player1, game.player2
    make_current(game, player)
    secret = player.give("EX1_287")
    secret.play()
    placed = secret.zone == Zone.SECRET and secret in player.secrets
    game.end_turn()
    target = player.hero
    before = target.health
    spell = opponent.give("CS2_008")
    spell.play(target=target)
    observed = (
        f"placed={placed};secret_zone={secret.zone.name};secret_active={secret in player.secrets};"
        f"target_health={before}->{target.health};opponent_spell_zone={spell.zone.name}"
    )
    return observed, (
        placed
        and secret.zone == Zone.GRAVEYARD
        and secret not in player.secrets
        and target.health == before
        and spell.zone == Zone.GRAVEYARD
    )


def cost_modification_probe():
    game = new_game()
    player = game.player1
    make_current(game, player)
    fireball = player.give("CS2_029")
    before = fireball.cost
    emperor = player.give("BRM_028")
    emperor.play()
    game.end_turn()
    after = fireball.cost
    observed = (
        f"fireball_cost={before}->{after};emperor_zone={emperor.zone.name};"
        f"fireball_zone={fireball.zone.name};player_turn={player.current_player}"
    )
    return observed, before == 4 and after == 3 and emperor.zone == Zone.PLAY


def weapon_probe():
    game = new_game()
    player, opponent = game.player1, game.player2
    make_current(game, player)
    weapon = player.give("CS2_091")
    weapon.play()
    durability_before = weapon.durability
    hero_attack = player.hero.atk
    target_health = opponent.hero.health
    target_legal = opponent.hero in player.hero.attack_targets
    player.hero.attack(opponent.hero)
    observed = (
        f"equipped={player.weapon is weapon};weapon_zone={weapon.zone.name};"
        f"durability={durability_before}->{weapon.durability};hero_atk={hero_attack};"
        f"enemy_health={target_health}->{opponent.hero.health};hero_attacks={player.hero.num_attacks}"
    )
    return observed, (
        player.weapon is weapon
        and weapon.zone == Zone.PLAY
        and durability_before == 4
        and weapon.durability == 3
        and hero_attack == 1
        and opponent.hero.health == target_health - 1
        and target_legal
    )


def hero_power_probe():
    game = new_game()
    player, opponent = game.player1, game.player2
    make_current(game, player)
    target = opponent.summon("CS2_182")
    power = player.hero.power
    legal_target = target in power.targets
    before = target.health
    power.use(target=target)
    observed = (
        f"power={power.id};legal_target={legal_target};target_health={before}->{target.health};"
        f"target_zone={target.zone.name};power_exhausted={power.exhausted}"
    )
    return observed, (
        power.id == "HERO_08bp"
        and legal_target
        and target.health == before - 1
        and target.zone == Zone.PLAY
        and power.exhausted
    )


def combo_probe():
    game = new_game()
    player, opponent = game.player1, game.player2
    make_current(game, player)
    target = opponent.summon("CS2_182")
    agent = player.give("EX1_134")
    needs_target_before = agent.requires_target()
    coin = player.give("GAME_005")
    coin.play()
    needs_target_after = agent.requires_target()
    legal_target = target in agent.targets
    before_health = target.health
    agent.play(target=target)
    observed = (
        f"combo={player.combo};requires_target={needs_target_before}->{needs_target_after};"
        f"legal_target={legal_target};target_health={before_health}->{target.health};"
        f"target_zone={target.zone.name};agent_zone={agent.zone.name};coin_zone={coin.zone.name}"
    )
    return observed, (
        needs_target_before is False
        and needs_target_after is True
        and player.combo
        and legal_target
        and target.zone == Zone.PLAY
        and target.health == before_health - 2
        and agent.zone == Zone.PLAY
        and coin.zone == Zone.GRAVEYARD
    )


def rush_probe():
    game = new_game()
    player, opponent = game.player1, game.player2
    make_current(game, player)
    target = opponent.summon("CS2_231")
    minion = player.give("GIL_113")
    minion.play()
    hero_blocked = not minion.can_attack(opponent.hero)
    minion_target_legal = minion.can_attack(target)
    attack_targets = [card.id for card in minion.attack_targets]
    minion.attack(target)
    observed = (
        f"rush={minion.rush};hero_blocked={hero_blocked};"
        f"minion_target_legal={minion_target_legal};attack_targets={attack_targets};"
        f"target_zone={target.zone.name};enemy_hero_health={opponent.hero.health}"
    )
    return observed, (
        minion.rush
        and hero_blocked
        and minion_target_legal
        and target.zone == Zone.GRAVEYARD
        and opponent.hero.health == 30
    )


def lifesteal_probe():
    game = new_game()
    player, opponent = game.player1, game.player2
    make_current(game, player)
    player.hero.set_current_health(25)
    target = opponent.summon("CS2_231")
    minion = player.give("GIL_143")
    minion.play()
    has_lifesteal = minion.lifesteal
    before = player.hero.health
    target_legal = minion.can_attack(target)
    minion.attack(target)
    observed = (
        f"lifesteal={has_lifesteal};hero_health={before}->{player.hero.health};"
        f"target_zone={target.zone.name};minion_zone={minion.zone.name};"
        f"minion_rush={minion.rush}"
    )
    return observed, (
        has_lifesteal
        and minion.rush
        and target_legal
        and player.hero.health == before + 1
        and target.zone == Zone.GRAVEYARD
        and minion.zone == Zone.PLAY
    )


def poisonous_probe():
    game = new_game()
    player, opponent = game.player1, game.player2
    make_current(game, player)
    cobra = player.give("EX1_170")
    cobra.play()
    game.end_turn()
    target = opponent.summon("EX1_396")  # 1/7 Taunt, survives ordinary 2 damage.
    game.end_turn()
    before_health = target.health
    poisonous = cobra.poisonous
    target_legal = cobra.can_attack(target)
    cobra.attack(target)
    observed = (
        f"poisonous={poisonous};target_health={before_health}->{target.health};"
        f"target_zone={target.zone.name};cobra_zone={cobra.zone.name};"
        f"cobra_health={cobra.health};target_legal={target_legal}"
    )
    return observed, (
        poisonous
        and target_legal
        and target.zone == Zone.GRAVEYARD
        and cobra.zone == Zone.PLAY
    )


def outcast_probe():
    # Leftmost play must use the Outcast slot; a true middle card must not.
    left_game = new_game()
    left_player = left_game.player1
    left_player.discard_hand()
    for card_id in ("CS2_231", "CS1_042"):
        left_player.give(card_id).shuffle_into_deck()
    left_spell = left_player.give("BT_491")
    left_player.give("GVG_093")
    left_deck_before = len(left_player.deck)
    left_spell.play()
    left_drawn = left_deck_before - len(left_player.deck)
    left_zone = left_spell.zone.name

    middle_game = new_game()
    middle_player = middle_game.player1
    middle_player.discard_hand()
    for card_id in ("CS2_231", "CS1_042"):
        middle_player.give(card_id).shuffle_into_deck()
    middle_player.give("GVG_093")
    middle_spell = middle_player.give("BT_491")
    middle_player.give("EX1_396")
    middle_deck_before = len(middle_player.deck)
    middle_spell.play()
    middle_drawn = middle_deck_before - len(middle_player.deck)
    middle_zone = middle_spell.zone.name
    observed = (
        f"leftmost_draws={left_drawn};left_spell_zone={left_zone};"
        f"middle_draws={middle_drawn};middle_spell_zone={middle_zone};"
        f"left_hand={[card.id for card in left_player.hand]};"
        f"middle_hand={[card.id for card in middle_player.hand]}"
    )
    return observed, (
        left_drawn == 2
        and middle_drawn == 1
        and left_spell.zone == Zone.GRAVEYARD
        and middle_spell.zone == Zone.GRAVEYARD
    )


def weapon_lifesteal_probe():
    game = new_game()
    player, opponent = game.player1, game.player2
    make_current(game, player)
    player.hero.set_current_health(25)
    weapon = player.give("BT_921")
    weapon.play()
    before_health = player.hero.health
    before_durability = weapon.durability
    before_enemy_health = opponent.hero.health
    lifesteal = weapon.lifesteal
    player.hero.attack(opponent.hero)
    observed = (
        f"lifesteal={lifesteal};hero_health={before_health}->{player.hero.health};"
        f"enemy_hero={before_enemy_health}->{opponent.hero.health};"
        f"durability={before_durability}->{weapon.durability};weapon_zone={weapon.zone.name}"
    )
    return observed, (
        lifesteal
        and before_health == 25
        and player.hero.health == before_health + 2
        and opponent.hero.health == before_enemy_health - 2
        and before_durability == 2
        and weapon.durability == 1
        and weapon.zone == Zone.PLAY
    )


def spell_damage_probe():
    game = new_game()
    player, opponent = game.player1, game.player2
    make_current(game, player)
    squallhunter = player.give("DRG_211")
    squallhunter.play()
    moonfire = player.give("CS2_008")
    before = opponent.hero.health
    moonfire.play(target=opponent.hero)
    damage = before - opponent.hero.health
    observed = (f"spellpower={squallhunter.spellpower};moonfire_damage={damage};"
                f"squallhunter_zone={squallhunter.zone.name};moonfire_zone={moonfire.zone.name}")
    return observed, (squallhunter.spellpower == 2 and damage == 3
                      and squallhunter.zone == Zone.PLAY and moonfire.zone == Zone.GRAVEYARD)


def reborn_probe():
    game = new_game()
    player = game.player1
    minion = player.summon("ULD_205")
    has_reborn = minion.reborn
    minion.destroy()
    copies = [card for card in player.field if card.id == "ULD_205"]
    observed = (
        f"has_reborn={has_reborn};original_zone={minion.zone.name};"
        f"copy_count={len(copies)};copies={[f'{card.health}hp/reborn={card.reborn}' for card in copies]}"
    )
    return observed, (
        has_reborn
        and minion.zone == Zone.GRAVEYARD
        and len(copies) == 1
        and copies[0].health == 1
        and not copies[0].reborn
    )


def main():
    probes = [
        ("BATTLE-01", "Battlecry", "CS2_188|CS2_231", "targeted +2 Attack Battlecry applies then expires at turn end", battlecry_probe),
        ("SPELL-01", "Spell resolution", "CS2_029", "legal enemy hero target takes 6 damage; spell moves to graveyard", spell_probe),
        ("SUMMON-01", "Summon", "BT_173|BT_036t", "six 1/1 Rush Illidari enter field; spell moves to graveyard", lambda: summon_probe(False)),
        ("SUMMON-02", "Summon / board cap", "BT_173|BT_036t", "with five minions, only two tokens enter and field remains capped at seven", lambda: summon_probe(True)),
        ("DRAW-01", "Draw", "CS2_023|CS2_231|CS1_042", "draw two known deck cards; hand/deck counts change by +2/-2", draw_probe),
        ("DISCARD-01", "Discard / targeting", "EX1_308|CS1_042|CS2_231", "target takes 4; sole other hand card is discarded; spell/target zones resolve", discard_probe),
        ("SILENCE-01", "Silence / targeting", "EX1_332|CS1_042", "Taunt is removed; target remains on field and spell enters graveyard", silence_probe),
        ("CHOICE-01", "Choose One", "EX1_160|EX1_160a|EX1_160t", "summon branch resolves to one 3/2 Panther and clears choice", lambda: choose_one_probe("summon")),
        ("CHOICE-02", "Choose One", "EX1_160|EX1_160b|EX1_160be", "buff branch gives existing friendly minion +1/+1 and clears choice", lambda: choose_one_probe("buff")),
        ("TRIGGER-01", "Trigger / Silence", "NEW1_012|GAME_005|EX1_332", "own spell buffs Mana Wyrm; opponent spell does not; Silence stops later trigger", trigger_probe),
        ("AURA-01", "Aura", "EX1_162|CS2_231", "adjacent minions gain +1 Attack while aura source is present and revert after it dies", aura_probe),
        ("SECRET-01", "Secret / own-turn trigger", "AT_073|AT_073e|CS2_231", "Competitive Spirit triggers at own next turn start, buffs minion, leaves secret zone", at073_probe),
        ("SECRET-02", "Secret / spell counter", "EX1_287|CS2_008", "Counterspell is consumed; opponent spell resolves to graveyard without damaging hero", counterspell_probe),
        ("COST-01", "Cost modification / turn trigger", "BRM_028|CS2_029", "Emperor Thaurissan reduces positive-cost card in own hand by one at end turn", cost_modification_probe),
        ("WEAPON-01", "Weapon / attack / durability", "CS2_091", "equipped weapon adds 1 attack; hero attack deals 1 and durability drops by one", weapon_probe),
        ("HPOWER-01", "Hero Power / targeting", "HERO_08bp|CS2_231", "Fireblast deals 1 to legal minion target and exhausts hero power", hero_power_probe),
        ("COMBO-01", "Combo / target prerequisite", "EX1_134|GAME_005|CS2_231", "Coin activates Combo; SI:7 Agent target becomes legal and receives 2 damage", combo_probe),
        ("KEYWORD-01", "Rush", "GIL_113|CS2_231", "new Rush minion can attack enemy minion immediately but not enemy hero", rush_probe),
        ("KEYWORD-02", "Lifesteal / Rush", "GIL_143|CS2_231", "Rush minion damages a minion and heals hero for damage dealt", lifesteal_probe),
        ("KEYWORD-03", "Poisonous", "EX1_170|EX1_396", "Poisonous attacker kills 1/7 Taunt despite dealing only 2 Attack", poisonous_probe),
        ("KEYWORD-04", "Reborn / death processing", "ULD_205", "first death leaves exactly one 1-health copy without Reborn", reborn_probe),
        ("OUTCAST-01", "Outcast / Draw", "BT_491|CS2_231|CS1_042", "leftmost Spectral Sight draws two; middle position draws only one", outcast_probe),
        ("WEAPON-02", "Weapon / Lifesteal", "BT_921", "2/2 Lifesteal weapon heals hero for 2 after attacking enemy hero", weapon_lifesteal_probe),
        ("SPELLPOWER-01", "Spell Damage", "DRG_211|CS2_008", "Squallhunter Spell Damage +2 raises Moonfire from 1 to 3", spell_damage_probe),
    ]
    for case in probes:
        run_case(*case)

    output = Path(__file__).with_name("later_stage_probes.csv")
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ROWS)
    for row in ROWS:
        print(f"{row['case_id']} {row['outcome']} {row['observed']}")


if __name__ == "__main__":
    main()
