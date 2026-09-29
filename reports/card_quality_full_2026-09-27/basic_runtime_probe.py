"""Runtime probes for collectible BASIC cards.

Run from the repository root:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/basic_runtime_probe.py

The first group discovers all collectible BASIC minions without a Python card
script and verifies their printed stats and actual board entry. Additional
cases exercise native Taunt, Charge, Spell Damage, weapons, several Battlecries,
auras, and spells through observable game state.
"""

import csv
import logging
from pathlib import Path

import fireplace.cards as carddb
from fireplace.dsl.selector import BEAST, DEMON, ELEMENTAL, MURLOC
from hearthstone.enums import CardClass, CardSet, CardType, GameTag, Race, Zone

from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


OUT = Path(__file__).with_suffix(".csv")
FIELDS = ["case_id", "card_id", "mechanic", "expected", "observed", "outcome", "notes"]
ROWS = []


def new_game():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    return game


def record(case_id, card_id, mechanic, expected, observed, passed, notes=""):
    ROWS.append(
        {
            "case_id": case_id,
            "card_id": card_id,
            "mechanic": mechanic,
            "expected": expected,
            "observed": observed,
            "outcome": "PASS" if passed else "FAIL",
            "notes": notes,
        }
    )


def run_case(case_id, card_id, mechanic, expected, probe, notes=""):
    try:
        observed, passed = probe()
    except Exception as error:  # Keep runtime failures visible in the evidence.
        observed = f"exception={type(error).__name__}: {error}"
        passed = False
    record(case_id, card_id, mechanic, expected, observed, passed, notes)


def has_python_script(card):
    # CardDB attaches a direct subclass of object when no card module defines it.
    return len(card.scripts.__mro__) > 2


def no_script_entry_probe(card_id):
    data = carddb.db[card_id]
    race_selectors = {
        Race.BEAST: BEAST,
        Race.DEMON: DEMON,
        Race.ELEMENTAL: ELEMENTAL,
        Race.MURLOC: MURLOC,
    }

    def probe():
        game = new_game()
        player = game.player1
        minion = player.give(card_id)
        hand_zone = minion.zone
        hand_stats = (minion.atk, minion.health)
        hand_cost, hand_race = minion.cost, minion.race
        minion.play()
        actual_stats = (minion.atk, minion.health)
        actual_cost, actual_race = minion.cost, minion.race
        expected_stats = (data.atk, data.health)
        expected_taunt = bool(data.taunt)
        expected_charge = bool(data.tags.get(GameTag.CHARGE, 0))
        expected_spell_damage = int(data.spell_damage or 0)
        actual_spell_damage = int(minion.spellpower or 0)
        selector = race_selectors.get(data.race)
        if selector is None:
            tribe_selected = "not_applicable"
        else:
            other = player.summon("CS2_231")  # Wisp has no tribe.
            matches = selector.eval(game.live_entities, minion)
            tribe_selected = minion in matches and other not in matches
        observed = (
            f"printed={data.atk}/{data.health},cost={data.cost},race={data.race.name};"
            f"hand={hand_zone.name}:{hand_stats[0]}/{hand_stats[1]},cost={hand_cost},race={Race(hand_race).name};"
            f"play={minion.zone.name}:{actual_stats[0]}/{actual_stats[1]},cost={actual_cost},race={Race(actual_race).name};"
            f"in_field={minion in player.field};taunt={minion.taunt};charge={minion.charge};"
            f"spell_damage={actual_spell_damage};tribe_selector={tribe_selected}"
        )
        passed = (
            hand_zone == Zone.HAND
            and hand_stats == expected_stats
            and hand_cost == data.cost
            and hand_race == data.race
            and minion.zone == Zone.PLAY
            and minion in player.field
            and actual_stats == expected_stats
            and actual_cost == data.cost
            and actual_race == data.race
            and minion.taunt == expected_taunt
            and bool(minion.charge) == expected_charge
            and actual_spell_damage == expected_spell_damage
            and tribe_selected in (True, "not_applicable")
        )
        return observed, passed

    expected = (
        f"hand and PLAY zone; printed stats {data.atk}/{data.health}, cost {data.cost}, "
        f"race {data.race.name} preserved; tribe selector if applicable; "
        f"Taunt={bool(data.taunt)}, Charge={bool(data.tags.get(GameTag.CHARGE, 0))}, "
        f"Spell Damage={int(data.spell_damage or 0)}"
    )
    run_case(
        f"entry_{card_id}",
        card_id,
        "No-script minion entry / printed stats",
        expected,
        probe,
        "Entry, cost, tribe selection, and native keyword state; Taunt/Charge/Spell Damage interactions have separate cases.",
    )


def taunt_probe(card_id):
    def probe():
        game = new_game()
        owner, attacker_owner = game.player1, game.player2
        taunt = owner.give(card_id)
        taunt.play()
        non_taunt = owner.summon("CS2_168")
        game.end_turn()
        attacker = attacker_owner.give("CS2_171")
        attacker.play()
        legal = list(attacker.targets)
        taunt_health = taunt.health
        other_health = non_taunt.health
        hero_health = owner.hero.health
        ready = attacker.can_attack()
        attacker.attack(taunt)
        observed = (
            f"taunt={taunt.id}:{taunt_health}->{taunt.health}/{taunt.zone.name};"
            f"other={non_taunt.id}:{other_health}->{non_taunt.health}/{non_taunt.zone.name};"
            f"p1_hero={hero_health}->{owner.hero.health};"
            f"legal_targets={[getattr(target, 'id', 'HERO') for target in legal]};"
            f"boar_ready={ready};boar_zone={attacker.zone.name}"
        )
        passed = (
            taunt in legal
            and non_taunt not in legal
            and owner.hero not in legal
            and ready
            and taunt.health == taunt_health - 1
            and non_taunt.health == other_health
            and owner.hero.health == hero_health
            and attacker.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        f"taunt_{card_id}",
        card_id,
        "Taunt / attack targeting",
        "A ready enemy Charge minion can attack the Taunt minion, but cannot target a non-Taunt minion or hero; combat resolves.",
        probe,
        "Uses Stonetusk Boar as a deterministic ready attacker; its 1/1 body should die to the retaliation.",
    )


def charge_probe(card_id):
    def probe():
        game = new_game()
        owner, opponent = game.player1, game.player2
        minion = owner.give(card_id)
        minion.play()
        ready = minion.can_attack()
        target_legal = opponent.hero in minion.targets
        before = opponent.hero.health
        if ready:
            minion.attack(opponent.hero)
        observed = (
            f"printed_atk={carddb.db[card_id].atk};charge={minion.charge};ready_on_entry={ready};"
            f"hero_target_legal={target_legal};enemy_hero={before}->{opponent.hero.health};"
            f"zone={minion.zone.name};num_attacks={minion.num_attacks};ready_after={minion.can_attack()}"
        )
        passed = (
            minion.charge
            and ready
            and target_legal
            and opponent.hero.health == before - carddb.db[card_id].atk
            and minion.zone == Zone.PLAY
            and minion.num_attacks == 1
            and not minion.can_attack()
        )
        return observed, passed

    run_case(
        f"charge_{card_id}",
        card_id,
        "Charge / same-turn attack",
        "The minion can attack the enemy hero immediately after being played, deals printed attack damage, and is exhausted after one attack.",
        probe,
    )


def spell_damage_probe(card_id):
    def probe():
        game = new_game()
        owner, opponent = game.player1, game.player2
        caster = owner.give(card_id)
        caster.play()
        spell = owner.give("CS2_008")
        legal = opponent.hero in spell.targets
        before = opponent.hero.health
        spell.play(target=opponent.hero)
        observed = (
            f"minion_spell_damage={caster.spellpower};legal_target={legal};"
            f"enemy_hero={before}->{opponent.hero.health};spell_zone={spell.zone.name};"
            f"minion_zone={caster.zone.name}"
        )
        passed = (
            caster.spellpower == 1
            and legal
            and opponent.hero.health == before - 2
            and spell.zone == Zone.GRAVEYARD
            and caster.zone == Zone.PLAY
        )
        return observed, passed

    run_case(
        f"spell_damage_{card_id}",
        card_id,
        "Spell Damage / spell resolution",
        "After this Spell Damage +1 minion is summoned, Moonfire deals 2 rather than 1 damage and enters the graveyard.",
        probe,
        "Moonfire is used as a deterministic damage probe; the tested BASIC minion's damage bonus is the subject.",
    )


def weapon_probe(card_id):
    data = carddb.db[card_id]

    def probe():
        game = new_game()
        owner, opponent = game.player1, game.player2
        weapon = owner.give(card_id)
        weapon.play()
        equipped = owner.weapon is weapon
        atk = owner.hero.atk
        durability_before = weapon.durability
        enemy_before = opponent.hero.health
        own_before = owner.hero.health
        if card_id == "CS2_097":
            # Exercise its attack trigger from a controlled, damaged state.
            owner.hero.set_current_health(25)
            own_before = owner.hero.health
        owner.hero.attack(opponent.hero)
        observed = (
            f"equipped={equipped};printed={data.atk}/{data.durability};hero_atk={atk};"
            f"weapon_durability={durability_before}->{weapon.durability};"
            f"enemy_hero={enemy_before}->{opponent.hero.health};"
            f"own_hero={own_before}->{owner.hero.health};weapon_zone={weapon.zone.name};"
            f"hero_ready_after={owner.hero.can_attack()}"
        )
        expected_heal = 2 if card_id == "CS2_097" else 0
        passed = (
            equipped
            and atk == data.atk
            and durability_before == data.durability
            and weapon.durability == durability_before - 1
            and opponent.hero.health == enemy_before - data.atk
            and owner.hero.health == own_before + expected_heal
            and weapon.zone == Zone.PLAY
            and not owner.hero.can_attack()
        )
        return observed, passed

    notes = ""
    if card_id == "CS2_097":
        notes = "Hero current health is set to 25 before attack to expose the printed 2 Health restore trigger."
    run_case(
        f"weapon_{card_id}",
        card_id,
        "Weapon / equip, attack, durability" + (" / heal trigger" if card_id == "CS2_097" else ""),
        f"Equip with {data.atk} Attack and {data.durability} Durability; hero attack deals printed damage, durability falls by 1, weapon remains equipped."
        + (" Truesilver also restores 2 Health." if card_id == "CS2_097" else ""),
        probe,
        notes,
    )


def fire_elemental_probe():
    card_id = "CS2_042"

    def probe():
        game = new_game()
        owner, opponent = game.player1, game.player2
        target = opponent.summon("CS2_179")
        before = target.health
        minion = owner.give(card_id)
        legal = target in minion.targets
        minion.play(target=target)
        observed = (
            f"target_legal={legal};target={before}->{target.health}/{target.zone.name};"
            f"battlecry_minion={minion.zone.name};in_field={minion in owner.field}"
        )
        return observed, (
            legal
            and target.health == before - 3
            and target.zone == Zone.PLAY
            and minion.zone == Zone.PLAY
            and minion in owner.field
        )

    run_case(
        "battlecry_CS2_042",
        card_id,
        "Battlecry / targeting / damage",
        "Fire Elemental's Battlecry legally targets an enemy minion, deals exactly 3 damage to a 3/5 target, and enters play.",
        probe,
    )


def gnomish_inventor_probe():
    card_id = "CS2_147"

    def probe():
        game = new_game()
        owner = game.player1
        seeded = owner.give("CS2_120")
        seeded.shuffle_into_deck()
        deck_before = len(owner.deck)
        draws_before = owner.cards_drawn_this_turn
        minion = owner.give(card_id)
        minion.play()
        observed = (
            f"deck={deck_before}->{len(owner.deck)};draw_count={draws_before}->{owner.cards_drawn_this_turn};"
            f"seeded_card_in_hand={seeded in owner.hand};inventor_zone={minion.zone.name};"
            f"inventor_in_field={minion in owner.field}"
        )
        return observed, (
            len(owner.deck) == deck_before - 1
            and owner.cards_drawn_this_turn == draws_before + 1
            and seeded in owner.hand
            and minion.zone == Zone.PLAY
            and minion in owner.field
        )

    run_case(
        "battlecry_CS2_147",
        card_id,
        "Battlecry / draw / zone",
        "Gnomish Inventor draws the known top-deck card, decreases deck by 1, increments turn draw count by 1, and enters play.",
        probe,
    )


def frostwolf_warlord_probe():
    card_id = "CS2_226"

    def probe():
        game = new_game()
        owner = game.player1
        other_one = owner.summon("CS2_168")
        other_two = owner.summon("CS2_168")
        enemy = game.player2.summon("CS2_168")
        minion = owner.give(card_id)
        minion.play()
        observed = (
            f"warlord={minion.atk}/{minion.health};base={carddb.db[card_id].atk}/{carddb.db[card_id].health};"
            f"other_minions={other_one.atk}/{other_one.health},{other_two.atk}/{other_two.health};"
            f"enemy={enemy.atk}/{enemy.health};"
            f"zone={minion.zone.name};in_field={minion in owner.field}"
        )
        return observed, (
            (minion.atk, minion.health) == (6, 6)
            and (other_one.atk, other_one.health) == (2, 1)
            and (other_two.atk, other_two.health) == (2, 1)
            and (enemy.atk, enemy.health) == (2, 1)
            and minion.zone == Zone.PLAY
            and minion in owner.field
        )

    run_case(
        "battlecry_CS2_226",
        card_id,
        "Battlecry / conditional stats",
        "With two other friendly minions and one enemy minion, Frostwolf Warlord gains exactly +2/+2; enemy does not count.",
        probe,
    )


def stormwind_champion_probe():
    card_id = "CS2_222"

    def probe():
        game = new_game()
        owner = game.player1
        first = owner.summon("CS2_168")
        second = owner.summon("CS2_168")
        champion = owner.give(card_id)
        champion.play()
        while_aura = (first.atk, first.health, second.atk, second.health)
        self_stats = (champion.atk, champion.health)
        silence = owner.give("EX1_332")
        legal = champion in silence.targets
        silence.play(target=champion)
        after_silence = (first.atk, first.health, second.atk, second.health)
        observed = (
            f"other_minions_with_aura={while_aura};champion={self_stats};"
            f"silence_legal={legal};other_minions_after_silence={after_silence};"
            f"champion_silenced={champion.silenced};zone={champion.zone.name}"
        )
        return observed, (
            while_aura == (3, 2, 3, 2)
            and self_stats == (6, 6)
            and legal
            and after_silence == (2, 1, 2, 1)
            and champion.silenced
            and champion.zone == Zone.PLAY
        )

    run_case(
        "aura_CS2_222",
        card_id,
        "Aura / continuous effect / Silence",
        "Stormwind Champion gives +1/+1 to all other friendly minions, not itself; silencing it removes both aura buffs.",
        probe,
    )


def timber_wolf_probe():
    card_id = "DS1_175"

    def probe():
        game = new_game()
        owner = game.player1
        beast = owner.summon("CS2_172")
        non_beast = owner.summon("CS2_168")
        wolf = owner.give(card_id)
        wolf.play()
        with_aura = (beast.atk, beast.health, non_beast.atk, non_beast.health, wolf.atk, wolf.health)
        silence = owner.give("EX1_332")
        legal = wolf in silence.targets
        silence.play(target=wolf)
        after_silence = (beast.atk, beast.health, non_beast.atk, non_beast.health)
        observed = (
            f"beast=3/2->{beast.atk}/{beast.health};non_beast=2/1->{non_beast.atk}/{non_beast.health};"
            f"wolf={wolf.atk}/{wolf.health};silence_legal={legal};"
            f"stats_with_aura={with_aura};stats_after_silence={after_silence};silenced={wolf.silenced}"
        )
        return observed, (
            with_aura == (4, 2, 2, 1, 1, 1)
            and legal
            and after_silence == (3, 2, 2, 1)
            and wolf.silenced
            and wolf.zone == Zone.PLAY
        )

    run_case(
        "aura_DS1_175",
        card_id,
        "Aura / tribe filter / Silence",
        "Timber Wolf gives +1 Attack to other friendly Beasts only (not itself or a non-Beast); Silence removes the Beast buff.",
        probe,
    )


def frost_nova_probe():
    card_id = "CS2_026"

    def probe():
        game = new_game()
        owner, opponent = game.player1, game.player2
        enemy_one = opponent.summon("CS2_168")
        enemy_two = opponent.summon("CS2_168")
        friendly = owner.summon("CS2_168")
        spell = owner.give(card_id)
        spell.play()
        observed = (
            f"enemy_frozen={enemy_one.frozen},{enemy_two.frozen};friendly_frozen={friendly.frozen};"
            f"enemy_zones={enemy_one.zone.name},{enemy_two.zone.name};spell_zone={spell.zone.name}"
        )
        return observed, (
            enemy_one.frozen
            and enemy_two.frozen
            and not friendly.frozen
            and enemy_one.zone == Zone.PLAY
            and enemy_two.zone == Zone.PLAY
            and spell.zone == Zone.GRAVEYARD
        )

    run_case(
        "spell_CS2_026",
        card_id,
        "Spell resolution / Freeze",
        "Frost Nova freezes all enemy minions, leaves friendly minions unfrozen, and enters the graveyard.",
        probe,
    )


def swipe_probe():
    card_id = "CS2_012"

    def probe():
        game = new_game()
        owner, opponent = game.player1, game.player2
        target = opponent.summon("CS2_182")
        secondary = opponent.summon("CS2_182")
        friendly = owner.summon("CS2_182")
        spell = owner.give(card_id)
        legal = target in spell.targets
        spell.play(target=target)
        observed = (
            f"target={target.health}/{target.zone.name};secondary={secondary.health}/{secondary.zone.name};"
            f"enemy_hero={opponent.hero.health};friendly={friendly.health}/{friendly.zone.name};"
            f"target_legal={legal};spell_zone={spell.zone.name}"
        )
        return observed, (
            legal
            and target.health == 1
            and target.zone == Zone.PLAY
            and secondary.health == 4
            and secondary.zone == Zone.PLAY
            and opponent.hero.health == 29
            and friendly.health == 5
            and friendly.zone == Zone.PLAY
            and spell.zone == Zone.GRAVEYARD
        )

    run_case(
        "spell_CS2_012",
        card_id,
        "Spell resolution / targeting / area damage",
        "Swipe deals 4 to the selected enemy and 1 to every other enemy character (including hero), while leaving friendly minions unchanged.",
        probe,
    )


def mark_of_the_wild_probe():
    card_id = "CS2_009"

    def probe():
        game = new_game()
        owner = game.player1
        minion = owner.summon("CS2_119")
        spell = owner.give(card_id)
        legal = minion in spell.targets
        before = (minion.atk, minion.health)
        spell.play(target=minion)
        observed = (
            f"target_legal={legal};stats={before}->{minion.atk}/{minion.health};"
            f"taunt={minion.taunt};zone={minion.zone.name};spell_zone={spell.zone.name}"
        )
        return observed, (
            legal
            and before == (2, 7)
            and (minion.atk, minion.health) == (4, 9)
            and minion.taunt
            and minion.zone == Zone.PLAY
            and spell.zone == Zone.GRAVEYARD
        )

    run_case(
        "spell_CS2_009",
        card_id,
        "Spell resolution / stats / Taunt",
        "Mark of the Wild gives a friendly minion +2/+2 and Taunt, preserving it on board and consuming the spell to graveyard.",
        probe,
    )


def arcane_explosion_probe():
    card_id = "CS2_025"

    def probe():
        game = new_game()
        owner, opponent = game.player1, game.player2
        enemy_one = opponent.summon("CS2_119")
        enemy_two = opponent.summon("CS2_182")
        friendly = owner.summon("CS2_168")
        spell = owner.give(card_id)
        spell.play()
        observed = (
            f"enemy_minions={enemy_one.health}/{enemy_one.zone.name},{enemy_two.health}/{enemy_two.zone.name};"
            f"enemy_hero={opponent.hero.health};friendly={friendly.health}/{friendly.zone.name};"
            f"spell_zone={spell.zone.name}"
        )
        return observed, (
            enemy_one.health == 6
            and enemy_two.health == 4
            and enemy_one.zone == Zone.PLAY
            and enemy_two.zone == Zone.PLAY
            and opponent.hero.health == 30
            and friendly.health == 1
            and friendly.zone == Zone.PLAY
            and spell.zone == Zone.GRAVEYARD
        )

    run_case(
        "spell_CS2_025",
        card_id,
        "Spell resolution / enemy-minion area damage",
        "Arcane Explosion deals 1 to all enemy minions only, not enemy hero or friendly minions; spell enters graveyard.",
        probe,
    )


def windfury_probe():
    card_id = "CS2_039"

    def probe():
        game = new_game()
        owner, opponent = game.player1, game.player2
        minion = owner.give("CS2_168")
        minion.play()
        game.end_turn()
        game.end_turn()
        first_before = opponent.hero.health
        minion.attack(opponent.hero)
        after_first = opponent.hero.health
        spell = owner.give(card_id)
        legal = minion in spell.targets
        spell.play(target=minion)
        ready_after_buff = minion.can_attack()
        attacks_after_buff = minion.num_attacks
        if ready_after_buff:
            minion.attack(opponent.hero)
        observed = (
            f"hero={first_before}->{after_first}->{opponent.hero.health};"
            f"windfury={minion.windfury};target_legal={legal};"
            f"ready_after_buff={ready_after_buff};attacks_after_buff={attacks_after_buff};"
            f"attacks_final={minion.num_attacks};ready_final={minion.can_attack()};spell_zone={spell.zone.name}"
        )
        return observed, (
            legal
            and after_first == first_before - 2
            and minion.windfury
            and ready_after_buff
            and attacks_after_buff == 1
            and opponent.hero.health == after_first - 2
            and minion.num_attacks == 2
            and not minion.can_attack()
            and spell.zone == Zone.GRAVEYARD
        )

    run_case(
        "spell_CS2_039",
        card_id,
        "Spell resolution / Windfury / attack state",
        "A minion that attacked once gains a second attack from Windfury, deals its printed 2 Attack damage each time, and is exhausted after attack two.",
        probe,
    )


def main():
    basic_minions = carddb.filter(card_set=CardSet.BASIC, collectible=True, type=CardType.MINION)
    no_script_minions = [
        card_id
        for card_id in basic_minions
        if not has_python_script(carddb.db[card_id])
    ]

    # Inventory-complete entry/stat probes for every collectible BASIC minion
    # without a Python card script (no HERO_* cards are minions, so none enter).
    for card_id in sorted(no_script_minions):
        no_script_entry_probe(card_id)

    # Every BASIC native Taunt minion: assert combat targeting, not just the tag.
    for card_id in sorted(
        card_id for card_id in no_script_minions if carddb.db[card_id].taunt
    ):
        taunt_probe(card_id)

    # Every BASIC native Charge minion: attack immediately and verify attack state.
    for card_id in sorted(
        card_id
        for card_id in no_script_minions
        if carddb.db[card_id].tags.get(GameTag.CHARGE, 0)
    ):
        charge_probe(card_id)

    # Every BASIC native Spell Damage minion: test the bonus through Moonfire.
    for card_id in sorted(
        card_id for card_id in no_script_minions if carddb.db[card_id].spell_damage
    ):
        spell_damage_probe(card_id)

    # All BASIC weapons, including Truesilver's attack-heal trigger.
    for card_id in ("CS2_080", "CS2_106", "CS2_112", "CS2_097"):
        weapon_probe(card_id)

    # Representative Basic scripted minion and spell effects.
    fire_elemental_probe()
    gnomish_inventor_probe()
    frostwolf_warlord_probe()
    stormwind_champion_probe()
    timber_wolf_probe()
    frost_nova_probe()
    swipe_probe()
    mark_of_the_wild_probe()
    arcane_explosion_probe()
    windfury_probe()

    with OUT.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ROWS)

    counts = {}
    for row in ROWS:
        counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
    print(
        f"BASIC collectible minions={len(basic_minions)};"
        f"no-script minions={len(no_script_minions)};probe_rows={len(ROWS)};"
        f"outcomes={counts};csv={OUT}"
    )
    for row in ROWS:
        if row["outcome"] != "PASS":
            print(f"{row['case_id']}: {row['outcome']}: {row['observed']}")
    if counts.get("FAIL"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
