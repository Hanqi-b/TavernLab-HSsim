"""Card-by-card live behavior probes for the middle LOOTAPALOOZA slice.

Each case uses a fresh real Fireplace game and asserts visible game state.
Rows are flushed after every card so partial progress stays reviewable.
"""
import csv
import logging
import random
import sys
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone

logging.disable(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import (  # noqa: E402
    FIREBALL, HOLY_LIGHT, MOONFIRE, WISP, prepare_empty_game,
)
from fireplace.exceptions import InvalidAction  # noqa: E402

BASELINE = HERE / "remaining_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
MECHANISMS = HERE / "card_mechanism.csv"
ISSUES = HERE / "mechanism_issues.csv"
PROBE_OUT = HERE / "loot_probe_b.csv"
VERDICT_OUT = HERE / "loot_verdict_b.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


BASE_ROWS = sorted(
    (r for r in read_csv(BASELINE) if r["set"] == "Kobolds & Catacombs (LOOTAPALOOZA)"),
    key=lambda r: r["card_id"],
)
OWN_ROWS = BASE_ROWS[45:90]
OWN_IDS = [r["card_id"] for r in OWN_ROWS]
assert len(OWN_IDS) == 45 and OWN_IDS[0] == "LOOT_149" and OWN_IDS[-1] == "LOOT_365"
MASTER_BY_ID = {r["card_id"]: r for r in read_csv(MASTER)}
QUALITY_BY_ID = {r["card_id"]: r for r in read_csv(QUALITY)}
MECH_BY_ID = {}
for _row in read_csv(MECHANISMS):
    MECH_BY_ID.setdefault(_row["card_id"], []).append(_row)
ISSUE_BY_ID = {}
for _row in read_csv(ISSUES):
    ISSUE_BY_ID.setdefault(_row.get("card_id", ""), []).append(_row)

CLASS_BY_ID = {
    "LOOT_170": CardClass.MAGE, "LOOT_172": CardClass.MAGE, "LOOT_231": CardClass.MAGE,
    "LOOT_204": CardClass.ROGUE, "LOOT_210": CardClass.ROGUE, "LOOT_211": CardClass.ROGUE,
    "LOOT_214": CardClass.ROGUE, "LOOT_216": CardClass.PALADIN, "LOOT_217": CardClass.HUNTER,
    "LOOT_222": CardClass.HUNTER, "LOOT_187": CardClass.PRIEST, "LOOT_278": CardClass.PRIEST,
    "LOOT_285": CardClass.WARRIOR, "LOOT_286": CardClass.PALADIN, "LOOT_309": CardClass.DRUID,
    "LOOT_313": CardClass.PALADIN, "LOOT_314": CardClass.DRUID, "LOOT_333": CardClass.PALADIN,
    "LOOT_344": CardClass.SHAMAN, "LOOT_351": CardClass.DRUID, "LOOT_353": CardClass.PRIEST,
    "LOOT_358": CardClass.SHAMAN, "LOOT_364": CardClass.WARRIOR, "LOOT_365": CardClass.WARRIOR,
}


def new_game(card_id=None, seed=2307, opponent_class=None):
    random.seed(seed)
    card_class = CLASS_BY_ID.get(card_id, CardClass.MAGE)
    game = prepare_empty_game(card_class, opponent_class or card_class)
    game.random.seed(seed)
    if game.current_player is not game.player1:
        game.end_turn()
    assert game.current_player is game.player1
    for player in game.players:
        player.is_standard = False
        player.max_mana = 10
        player.used_mana = 0
        player.temp_mana = 0
        player.overload_locked = 0
        player.discard_hand()
    return game


def give(player, card_id):
    card = player.give(card_id)
    assert card is not None, f"could not give {card_id}"
    return card


def summon(player, card_id):
    card = player.summon(card_id)
    assert card is not None, f"could not summon {card_id}"
    return card


def play(player, card_id, target=None, choose=None, index=None):
    card = give(player, card_id)
    card.play(target=target, choose=choose, index=index)
    return card


def deck_top(player, card_id):
    return player.card(card_id, zone=Zone.DECK)


def ids(cards):
    return [card.id for card in cards]


def race_name(card):
    value = card.race
    return getattr(value, "name", value)


def metadata(card_id):
    master = MASTER_BY_ID[card_id]
    old = QUALITY_BY_ID.get(card_id, {})
    mech = MECH_BY_ID.get(card_id, [])
    mech_text = " | ".join(f"{m['mechanic']}={m['status']}:{m['reason']}" for m in mech) or "none"
    issues = ISSUE_BY_ID.get(card_id, [])
    issue_text = "; ".join(str(i) for i in issues) if issues else "none"
    return (
        f"EN={master['card_text_en']}; ZH={master['card_text_zh']}; "
        f"source={master['python_source'] or master['xml_source']}; "
        f"existing_tests={master.get('test_refs_candidate') or 'none'}; "
        f"prior_card={old.get('status', 'unknown')}:{old.get('reason', 'no prior reason')}; "
        f"prior_mechanisms={mech_text}; issues={issue_text}"
    )


def check(observed, condition, expected):
    return expected, observed, bool(condition)


def c149_cost_triggers():
    g = new_game("LOOT_149"); p, e = g.player1, g.player2
    creeper = give(p, "LOOT_149"); before = creeper.cost
    f = summon(p, WISP); f.destroy()
    e_minion = summon(e, "CS2_231"); e_minion.destroy()
    observed = f"hand_cost={creeper.cost};base_cost={before};friendly_death={f.zone.name};enemy_death={e_minion.zone.name}"
    return check(observed, creeper.zone == Zone.HAND and creeper.cost == before - 2,
                 "Each minion death while in hand reduces cost by exactly 1, including enemy minions.")


def c149_only_in_hand():
    g = new_game("LOOT_149"); p = g.player1
    creeper = play(p, "LOOT_149"); before = creeper.cost
    dead = summon(p, WISP); dead.destroy()
    observed = f"zone={creeper.zone.name};cost={creeper.cost};before={before};dead={dead.zone.name}"
    return check(observed, creeper.zone == Zone.PLAY and creeper.cost == before,
                 "After play, minion deaths no longer reduce Corridor Creeper's cost.")


def c150_transform():
    g = new_game("LOOT_150"); p = g.player1
    target = summon(p, WISP)
    card = play(p, "LOOT_150", target=target)
    transformed = [m for m in p.field if m is not card]
    observed = f"field={[(m.id,m.atk,m.health,race_name(m)) for m in p.field]};card={card.zone.name}"
    ok = card.zone == Zone.PLAY and len(transformed) == 1 and (transformed[0].atk, transformed[0].health) == (6, 6) and race_name(transformed[0]) == Race.ELEMENTAL
    return check(observed, ok, "The selected friendly minion becomes a 6/6 Elemental; Mossbinder is played.")


def c150_enemy_rejected():
    g = new_game("LOOT_150"); p, e = g.player1, g.player2
    friendly = summon(p, WISP); enemy = summon(e, WISP); card = give(p, "LOOT_150"); mana = p.used_mana
    error = None
    try:
        card.play(target=enemy)
    except InvalidAction as exc:
        error = type(exc).__name__
    observed = f"error={error};card={card.zone.name};used_mana={p.used_mana}/{mana};friendly={friendly.id}/{friendly.zone.name};enemy={enemy.id}/{enemy.zone.name};friendly_targets={ids(card.play_targets)}"
    return check(observed, error == "InvalidAction" and card.zone == Zone.HAND and p.used_mana == mana and friendly.zone == Zone.PLAY and enemy.zone == Zone.PLAY,
                 "With a legal friendly target available, the enemy minion is rejected before Mossbinder is paid or moved.")


def c150_optional_no_target():
    g = new_game("LOOT_150"); p = g.player1
    card = play(p, "LOOT_150")
    observed = f"card={card.zone.name};field={[(m.id,m.atk,m.health) for m in p.field]};hand={ids(p.hand)}"
    return check(observed, card.zone == Zone.PLAY and p.field == [card],
                 "With no friendly minion available, the optional-target Battlecry is skipped and Mossbinder is played normally.")


def c152_buff_others():
    g = new_game("LOOT_152"); p = g.player1
    a = summon(p, WISP); b = summon(p, "EX1_399")
    before = [(a.atk,a.health),(b.atk,b.health)]
    card = give(p, "LOOT_152"); card_health = card.health; card.play()
    observed = f"before={before};after={[(a.atk,a.health),(b.atk,b.health)]};bard={card.atk}/{card.health};field={ids(p.field)}"
    ok = (a.atk,a.health) == (before[0][0],before[0][1]+1) and (b.atk,b.health) == (before[1][0],before[1][1]+1) and card.health == card_health and card.zone == Zone.PLAY
    return check(observed, ok, "Battlecry adds exactly 1 Health to every other friendly minion and not to the Bard.")


def c153_seven_grubs():
    g = new_game("LOOT_153"); p = g.player1
    wurm = summon(p, "LOOT_153"); wurm.destroy()
    grubs = [m for m in p.field if m.id == "LOOT_153t1"]
    observed = f"wurm={wurm.zone.name};field={[(m.id,m.atk,m.health) for m in p.field]};grubs={len(grubs)}"
    return check(observed, wurm.zone == Zone.GRAVEYARD and len(grubs) == 7 and all((m.atk,m.health)==(1,1) for m in grubs),
                 "Violet Wurm's deathrattle summons exactly seven 1/1 Grubs on an open board.")


def c153_board_cap():
    g = new_game("LOOT_153"); p = g.player1
    for _ in range(6): summon(p, WISP)
    wurm = summon(p, "LOOT_153"); wurm.destroy()
    grubs = [m for m in p.field if m.id == "LOOT_153t1"]
    observed = f"wurm={wurm.zone.name};field_count={len(p.field)};grubs={len(grubs)};ids={ids(p.field)}"
    return check(observed, wurm.zone == Zone.GRAVEYARD and len(p.field) == 7 and len(grubs) == 1,
                 "With six friendly minions remaining, only one of seven Grubs fits on the board.")


def c154_random_one_cost_opponent():
    seen = set(); samples = []
    for seed in range(2307, 2315):
        g = new_game("LOOT_154", seed=seed); p, e = g.player1, g.player2
        card = play(p, "LOOT_154")
        spawned = list(e.field)
        samples.append([(m.id,m.cost,str(m.type)) for m in spawned])
        if card.zone != Zone.PLAY or len(spawned) != 1 or spawned[0].cost != 1 or spawned[0].type != CardType.MINION:
            return check(f"seed={seed};opponent_field={samples[-1]};source={card.zone.name}", False,
                         "Each Battlecry creates exactly one random 1-Cost minion on the opponent's board.")
        seen.add(spawned[0].id)
    observed = f"seeded_opponent_minions={samples};distinct={len(seen)}"
    return check(observed, len(seen) >= 2,
                 "Across seeded games the Battlecry creates one random 1-Cost minion for the opponent, with varied outcomes.")


def c154_friendly_full_opponent_has_room():
    g=new_game("LOOT_154"); p,e=g.player1,g.player2
    for _ in range(6): summon(p,WISP)
    knight=play(p,"LOOT_154"); spawned=list(e.field)
    observed=f"friendly_field={len(p.field)};opponent_field={[(m.id,m.cost) for m in spawned]};knight={knight.zone.name}"
    return check(observed,len(p.field)==7 and knight.zone==Zone.PLAY and len(spawned)==1 and spawned[0].cost==1,
                 "With the Knight filling its controller's seventh board slot, its Battlecry still summons one 1-Cost minion for the opponent.")


def c154_opponent_full_caps():
    g=new_game("LOOT_154"); p,e=g.player1,g.player2
    existing=[summon(e,WISP) for _ in range(7)]
    knight=play(p,"LOOT_154"); spawned=[m for m in e.field if m.id!="CS2_231"]
    observed=f"knight={knight.zone.name};friendly_field={len(p.field)};opponent_count={len(e.field)};existing_still_present={all(m in e.field for m in existing)};non_wisps={[(m.id,m.cost) for m in spawned]}"
    return check(observed,knight.zone==Zone.PLAY and len(e.field)==7 and all(m in e.field for m in existing) and not spawned,
                 "A full opponent board remains capped at seven minions when Gravelsnout Knight's Battlecry resolves.")


def c161_cube_deathrattle():
    g = new_game("LOOT_161"); p = g.player1
    target = summon(p, WISP)
    cube = play(p, "LOOT_161", target=target)
    after_battlecry = f"target={target.zone.name};cube={cube.zone.name};field={ids(p.field)}"
    cube.destroy()
    copies = [m for m in p.field if m.id == WISP]
    observed = f"after_battlecry={after_battlecry};cube_death={cube.zone.name};copies={[(m.id,m.atk,m.health) for m in copies]}"
    ok = target.zone == Zone.GRAVEYARD and cube.zone == Zone.GRAVEYARD and len(copies) == 2 and all((m.atk,m.health)==(1,1) for m in copies)
    return check(observed, ok, "Cube destroys its selected friendly minion, then its deathrattle summons two copies of that minion.")


def c161_enemy_target_rejected():
    g = new_game("LOOT_161"); p, e = g.player1, g.player2
    friendly = summon(p, WISP); enemy = summon(e, WISP); cube = give(p, "LOOT_161"); mana = p.used_mana
    error = None
    try: cube.play(target=enemy)
    except InvalidAction as exc: error = type(exc).__name__
    observed = f"error={error};cube={cube.zone.name};used_mana={p.used_mana}/{mana};friendly={friendly.zone.name};enemy={enemy.zone.name};targets={ids(cube.play_targets)}"
    return check(observed, error == "InvalidAction" and cube.zone == Zone.HAND and p.used_mana == mana and friendly.zone == Zone.PLAY and enemy.zone == Zone.PLAY,
                 "Cube accepts only a friendly minion target and rejects an enemy before payment.")


def c165_friendly_death_copy():
    g = new_game("LOOT_165"); p = g.player1
    sonya = play(p, "LOOT_165"); dead = summon(p, "EX1_399"); base_cost = dead.cost; dead.destroy()
    copies = [m for m in p.hand if m.id == "EX1_399"]
    observed = f"sonya={sonya.zone.name};dead={dead.zone.name};hand={[(m.id,m.atk,m.health,m.cost,m.zone.name) for m in copies]}"
    ok = sonya.zone == Zone.PLAY and dead.zone == Zone.GRAVEYARD and len(copies) == 1 and (copies[0].atk,copies[0].health,copies[0].cost)==(1,1,1)
    return check(observed, ok, f"A friendly death adds one 1/1 copy to hand at cost 1 (original cost {base_cost}).")


def c165_enemy_death_ignored():
    g = new_game("LOOT_165"); p, e = g.player1, g.player2
    sonya = play(p, "LOOT_165"); enemy = summon(e, WISP); enemy.destroy()
    gained = [m for m in p.hand if m.id == WISP]
    observed = f"sonya={sonya.zone.name};enemy={enemy.zone.name};wisp_copies_in_hand={len(gained)};hand={ids(p.hand)}"
    return check(observed, sonya.zone == Zone.PLAY and enemy.zone == Zone.GRAVEYARD and not gained,
                 "An enemy minion death does not trigger Sonya's friendly-death effect.")


def c167_adjacent_only():
    g = new_game("LOOT_167"); p = g.player1
    left = summon(p, WISP); right = summon(p, "EX1_399"); remote = summon(p, "CS2_231")
    before = {m.id + str(i): (m.atk,m.health) for i,m in enumerate((left,right,remote))}
    card = play(p, "LOOT_167", index=1)
    observed = f"field={[(m.id,m.atk,m.health) for m in p.field]};before={before};bard={card.atk}/{card.health}"
    ok = (left.atk,left.health)==(3,3) and (right.atk,right.health)==(4,9) and (remote.atk,remote.health)==(1,1) and card.zone==Zone.PLAY
    return check(observed, ok, "Fungalmancer buffs the minions immediately to its left and right by +2/+2, leaving the remote minion unchanged.")


def c170_own_higher_cost_spell_drawn():
    g = new_game("LOOT_170"); p,e=g.player1,g.player2
    mine = deck_top(p, FIREBALL); theirs = deck_top(e, MOONFIRE)
    raven = play(p, "LOOT_170")
    observed = f"raven={raven.zone.name};own_spell={mine.id}/{mine.cost}/{mine.zone.name};opponent_spell={theirs.id}/{theirs.cost}/{theirs.zone.name};hand={[(m.id,m.zone.name) for m in p.hand]}"
    return check(observed, raven.zone==Zone.PLAY and mine.zone==Zone.HAND and theirs.zone==Zone.DECK,
                 "Raven Familiar draws the revealed friendly spell when its Cost exceeds the opponent's revealed spell.")


def c170_not_higher_no_draw():
    g = new_game("LOOT_170"); p,e=g.player1,g.player2
    mine = deck_top(p, MOONFIRE); theirs = deck_top(e, FIREBALL)
    raven = play(p, "LOOT_170")
    observed = f"raven={raven.zone.name};own_spell={mine.id}/{mine.cost}/{mine.zone.name};opponent_spell={theirs.id}/{theirs.cost}/{theirs.zone.name};hand={ids(p.hand)}"
    return check(observed, raven.zone==Zone.PLAY and mine.zone==Zone.DECK and theirs.zone==Zone.DECK and not any(m.id==MOONFIRE for m in p.hand),
                 "Raven Familiar does not draw when the friendly revealed spell costs less.")


def c172_reveal_cost_aoe():
    g = new_game("LOOT_172"); p,e=g.player1,g.player2
    revealed = deck_top(p, FIREBALL); friendly = summon(p, "EX1_399"); enemy = summon(e, "EX1_399")
    fury = play(p, "LOOT_172")
    observed = f"revealed={revealed.id}/{revealed.cost}/{revealed.zone.name};friendly={friendly.zone.name}/{friendly.health}/{friendly.damage};enemy={enemy.zone.name}/{enemy.health}/{enemy.damage};fury={fury.zone.name}"
    ok = revealed.zone==Zone.DECK and friendly.damage==4 and enemy.damage==4 and fury.zone==Zone.GRAVEYARD
    return check(observed, ok, "Dragon's Fury reveals the 4-Cost Fireball and deals exactly 4 damage to every minion on both sides.")


def c184_recruit_eight_cost():
    g = new_game("LOOT_184"); p=g.player1
    recruited = deck_top(p, "LOOT_153"); deck_top(p, WISP)
    vanguard = summon(p, "LOOT_184"); vanguard.destroy()
    observed = f"vanguard={vanguard.zone.name};recruit={recruited.id}/{recruited.cost}/{recruited.zone.name};field={[(m.id,m.atk,m.health) for m in p.field]};deck={[(m.id,m.cost) for m in p.deck]}"
    return check(observed, vanguard.zone==Zone.GRAVEYARD and recruited.zone==Zone.PLAY and recruited in p.field,
                 "Silver Vanguard recruits the only 8-Cost minion from the deck after dying.")


def c184_no_eight_cost():
    g = new_game("LOOT_184"); p=g.player1
    deck_top(p,WISP); vanguard=summon(p,"LOOT_184"); vanguard.destroy()
    observed=f"vanguard={vanguard.zone.name};field={ids(p.field)};deck={[(m.id,m.cost) for m in p.deck]}"
    return check(observed, vanguard.zone==Zone.GRAVEYARD and not p.field,
                 "Silver Vanguard summons nothing when the deck has no 8-Cost minion.")


def c187_dead_friendly_copies():
    g=new_game("LOOT_187"); p,e=g.player1,g.player2
    dead1=summon(p,"EX1_029"); dead2=summon(p,"LOOT_233")
    dead1.destroy(); dead2.destroy()
    call=play(p,"LOOT_187")
    copies=[m for m in p.field if m.id in {"EX1_029","LOOT_233"}]
    observed=f"deaths={dead1.zone.name},{dead2.zone.name};call={call.zone.name};copies={[(m.id,m.atk,m.health,m.has_deathrattle) for m in copies]};field={ids(p.field)}"
    ok=call.zone==Zone.GRAVEYARD and len(copies)==2 and all((m.atk,m.health)==(1,1) and m.has_deathrattle for m in copies)
    return check(observed,ok,"Twilight's Call summons two 1/1 copies of friendly Deathrattle minions that died this game.")


def c193_friendly_spell_target():
    g=new_game("LOOT_193"); p=g.player1
    courser=summon(p,"LOOT_193"); spell=play(p,MOONFIRE,target=courser)
    observed=f"courser={courser.zone.name}/{courser.health}/{courser.damage};spell={spell.zone.name}"
    return check(observed,spell.zone==Zone.GRAVEYARD and courser.zone==Zone.PLAY and courser.damage==1,
                 "The controller can target Shimmering Courser with a spell.")


def c193_enemy_spell_and_power_blocked():
    g=new_game("LOOT_193",opponent_class=CardClass.MAGE); p,e=g.player1,g.player2
    courser=summon(p,"LOOT_193"); g.end_turn(); error_spell=None; error_power=None
    spell=give(e,FIREBALL)
    try: spell.play(target=courser)
    except InvalidAction as exc: error_spell=type(exc).__name__
    try: e.hero.power.use(target=courser)
    except InvalidAction as exc: error_power=type(exc).__name__
    observed=f"spell_error={error_spell};spell_zone={spell.zone.name};power_error={error_power};courser={courser.zone.name}/{courser.damage};enemy_turn={g.current_player is e}"
    ok=error_spell=="InvalidAction" and error_power=="InvalidAction" and spell.zone==Zone.HAND and courser.zone==Zone.PLAY and courser.damage==0
    return check(observed,ok,"Opponent spells and Hero Powers cannot target Shimmering Courser.")


def c203_upgrade_each_equipped_weapon():
    g=new_game("LOOT_203"); p=g.player1
    stone=give(p,"LOOT_203"); first=give(p,"CS2_091"); first.play()
    after_one=[c.id for c in p.hand if c.id.startswith("LOOT_203")]
    second=give(p,"CS2_091"); second.play()
    after_two=[c.id for c in p.hand if c.id.startswith("LOOT_203")]
    stone_in_hand=next((c for c in p.hand if c.id=="LOOT_203t3"),None)
    if stone_in_hand is not None: stone_in_hand.play()
    golems=[m for m in p.field if m.id=="LOOT_203t4"]
    observed=f"after_one={after_one};after_two={after_two};stone={stone.id}/{stone.zone.name};golems={[(m.id,m.atk,m.health) for m in golems]};field={ids(p.field)}"
    ok=after_one==["LOOT_203t2"] and after_two==["LOOT_203t3"] and stone_in_hand is not None and stone_in_hand.zone==Zone.GRAVEYARD and len(golems)==3 and all((m.atk,m.health)==(5,5) for m in golems)
    return check(observed,ok,"Each equipped weapon upgrades the Spellstone in hand; the twice-upgraded spell summons three 5/5 Mithril Golems.")


def c204_friendly_death_bounces_discounted():
    g=new_game("LOOT_204"); p=g.player1
    secret=play(p,"LOOT_204"); target=summon(p,"LOOT_233"); original_cost=target.cost; attacker=summon(p.opponent,"EX1_399")
    g.end_turn(); attacker.attack(target)
    bounced=[m for m in p.hand if m.id=="EX1_399"]
    bounced_target=[m for m in p.hand if m.id=="LOOT_233"]
    observed=f"secret={secret.zone.name}/{secret in p.secrets};dead={target.zone.name};attacker={attacker.zone.name};bounced={[(m.id,m.cost,m.atk,m.health,m.zone.name) for m in bounced_target]}"
    ok=secret.zone==Zone.GRAVEYARD and secret not in p.secrets and target.zone==Zone.HAND and len(bounced_target)==1 and bounced_target[0].cost==max(0,original_cost-2)
    return check(observed,ok,"Cheat Death triggers on a friendly minion death, bounces it to hand, and reduces its Cost by 2.")


def c204_enemy_death_does_not_trigger():
    g=new_game("LOOT_204"); p,e=g.player1,g.player2
    secret=play(p,"LOOT_204"); friendly=summon(p,"EX1_399"); enemy=summon(e,WISP); g.end_turn(); enemy.attack(friendly)
    observed=f"secret={secret.zone.name}/{secret in p.secrets};enemy={enemy.zone.name};p_hand={ids(p.hand)}"
    return check(observed,secret.zone==Zone.SECRET and secret in p.secrets and enemy.zone==Zone.GRAVEYARD and friendly.zone==Zone.PLAY,
                 "An enemy minion death leaves Cheat Death armed and adds no enemy minion to its controller's hand.")


def c209_three_spell_threshold_each_turn():
    g=new_game("LOOT_209"); p,e=g.player1,g.player2
    weapon=play(p,"LOOT_209")
    for _ in range(2): play(p,MOONFIRE,target=e.hero)
    dragons_before=[m for m in p.field if m.id=="LOOT_209t"]
    play(p,MOONFIRE,target=e.hero)
    dragons_after=[m for m in p.field if m.id=="LOOT_209t"]
    g.skip_turn()
    for _ in range(3): play(p,MOONFIRE,target=e.hero)
    dragons_next_turn=[m for m in p.field if m.id=="LOOT_209t"]
    observed=f"weapon={weapon.zone.name}/{p.weapon.id if p.weapon else None};after_two={len(dragons_before)};after_three={[(m.id,m.atk,m.health) for m in dragons_after]};next_turn={[(m.id,m.atk,m.health) for m in dragons_next_turn]}"
    ok=weapon.zone==Zone.PLAY and p.weapon==weapon and not dragons_before and len(dragons_after)==1 and (dragons_after[0].atk,dragons_after[0].health)==(5,5) and len(dragons_next_turn)==2 and all((m.atk,m.health)==(5,5) for m in dragons_next_turn)
    return check(observed,ok,"Dragon Soul summons a 5/5 after the third spell, resets at turn end, and summons another after three spells next turn.")


def c210_secret_redirects_attack():
    g=new_game("LOOT_210"); p,e=g.player1,g.player2
    secret=play(p,"LOOT_210"); attacker=summon(e,"EX1_399"); neighbor=summon(e,WISP)
    g.end_turn(); attacker.attack(p.hero)
    observed=f"secret={secret.zone.name}/{secret in p.secrets};hero={p.hero.health}/{p.hero.damage};attacker={attacker.zone.name}/{attacker.damage};neighbor={neighbor.zone.name}/{neighbor.damage};enemy_field={ids(e.field)}"
    ok=secret.zone==Zone.GRAVEYARD and secret not in p.secrets and p.hero.health==30 and neighbor.zone==Zone.GRAVEYARD and attacker.zone==Zone.PLAY
    return check(observed,ok,"When an enemy minion attacks the Rogue hero, Sudden Betrayal redirects it to its sole adjacent minion.")


def c211_combo_draws_two_minions():
    g=new_game("LOOT_211"); p,e=g.player1,g.player2
    first=deck_top(p,WISP); second=deck_top(p,"EX1_399")
    play(p,MOONFIRE,target=e.hero); minstrel=play(p,"LOOT_211")
    drawn=[c for c in p.hand if c.id in {WISP,"EX1_399"}]
    observed=f"minstrel={minstrel.zone.name};drawn={[(c.id,c.type,c.zone.name) for c in drawn]};deck={ids(p.deck)};enemy_hero={e.hero.health}"
    return check(observed,minstrel.zone==Zone.PLAY and len(drawn)==2 and {c.id for c in drawn}=={WISP,"EX1_399"} and first.zone==Zone.HAND and second.zone==Zone.HAND,
                 "With Combo active, Elven Minstrel draws two minions from the deck.")


def c214_damage_then_immune():
    g=new_game("LOOT_214"); p,e=g.player1,g.player2
    secret=play(p,"LOOT_214"); first=summon(e,"EX1_399"); second=summon(e,"EX1_399")
    g.end_turn(); first.attack(p.hero); after_first=(p.hero.health,p.hero.immune); error=None
    try: second.attack(p.hero)
    except InvalidAction as exc: error=type(exc).__name__
    after_second=(p.hero.health,p.hero.immune)
    g.end_turn(); after_turn=p.hero.immune; g.end_turn(); second.attack(p.hero)
    after_next_hit=(p.hero.health,p.hero.immune)
    observed=f"secret={secret.zone.name}/{secret in p.secrets};after_first={after_first};second_attack_error={error};after_second={after_second};after_turn_end_immune={after_turn};after_next_turn_hit={after_next_hit};secret_after_repeat={secret.zone.name}/{secret in p.secrets}"
    ok=secret.zone==Zone.GRAVEYARD and after_first[0]==28 and after_first[1] and error=="InvalidAction" and after_second==after_first and not after_turn and after_next_hit[0]==26
    return check(observed,ok,"Evasion triggers after the first hit, blocks a second attack while immune, expires at turn end, and consumes the Secret exactly once.")


def c216_recasts_friendly_minion_spells():
    g=new_game("LOOT_216"); p=g.player1
    targets=[summon(p,WISP) for _ in range(3)]
    for target in targets: play(p,"CS2_087",target=target)
    lynessa=give(p,"LOOT_216"); base=(lynessa.atk,lynessa.health); lynessa.play()
    observed=f"base={base};lynessa={lynessa.atk}/{lynessa.health}/{lynessa.zone.name};targets={[(m.atk,m.health) for m in targets]};casts={len(p.cards_played_this_game)}"
    ok=lynessa.zone==Zone.PLAY and lynessa.atk==base[0]+9 and lynessa.health==base[1]
    return check(observed,ok,"Lynessa recasts all three previously cast +3 Attack spells that targeted friendly minions onto herself.")


def c217_one_or_two_companions():
    g=new_game("LOOT_217"); p=g.player1
    deck_top(p,WISP); one=play(p,"LOOT_217"); companions={"NEW1_032","NEW1_033","NEW1_034"}
    first=[m for m in p.field if m.id in companions]
    g2=new_game("LOOT_217"); p2=g2.player1
    deck_top(p2,FIREBALL); two=play(p2,"LOOT_217")
    second=[m for m in p2.field if m.id in companions]
    observed=f"minion_deck={[(m.id,m.atk,m.health) for m in first]};no_minion_deck={[(m.id,m.atk,m.health) for m in second]};cards={one.zone.name},{two.zone.name}"
    ok=one.zone==Zone.GRAVEYARD and two.zone==Zone.GRAVEYARD and len(first)==1 and len(second)==2 and all(m.zone==Zone.PLAY for m in first+second)
    return check(observed,ok,"To My Side! summons one Animal Companion with a minion in deck, or two when its deck has no minions.")


def c218_attack_hero_copy_only():
    g=new_game("LOOT_218"); p,e=g.player1,g.player2
    gibberer=summon(p,"LOOT_218"); g.end_turn(); g.end_turn(); gibberer.attack(e.hero)
    copies=[m for m in p.hand if m.id=="LOOT_218"]
    observed=f"attacker={gibberer.zone.name}/{gibberer.atk}/{gibberer.health};enemy_hero={e.hero.health};copies={[(m.id,m.atk,m.health,m.cost) for m in copies]}"
    ok=gibberer.zone==Zone.PLAY and e.hero.health<30 and len(copies)==1 and (copies[0].atk,copies[0].health)==(gibberer.atk,gibberer.health) and copies[0].cost==gibberer.cost
    return check(observed,ok,"After Feral Gibberer attacks the enemy hero, one copy is added to its controller's hand.")


def c218_attack_minion_no_copy():
    g=new_game("LOOT_218"); p,e=g.player1,g.player2
    gibberer=summon(p,"LOOT_218"); target=summon(e,"EX1_341"); g.end_turn(); g.end_turn(); gibberer.attack(target)
    copies=[m for m in p.hand if m.id=="LOOT_218"]
    observed=f"attacker={gibberer.zone.name}/{gibberer.damage};target={target.zone.name};copies={len(copies)}"
    return check(observed,not copies and gibberer.zone==Zone.PLAY and target.zone==Zone.PLAY and target.damage==gibberer.atk,
                 "Attacking a minion does not trigger Feral Gibberer's hero-attack effect.")


def c222_immune_while_attacking():
    g=new_game("LOOT_222"); p,e=g.player1,g.player2
    weapon=play(p,"LOOT_222"); enemy=summon(e,"EX1_399"); before=(p.hero.health,p.hero.armor,enemy.health)
    p.hero.attack(enemy)
    observed=f"weapon={weapon.zone.name}/{weapon.durability};hero={p.hero.health}/{p.hero.damage}/{p.hero.immune};enemy={enemy.zone.name}/{enemy.health}/{enemy.damage};before={before}"
    ok=weapon.zone==Zone.PLAY and weapon.durability==2 and p.hero.health==before[0] and enemy.damage==1 and enemy.zone==Zone.PLAY
    return check(observed,ok,"Candleshot deals 1 combat damage to a minion without allowing the attacking hero to take damage.")


def c231_armor_matches_spell_cost():
    g=new_game("LOOT_231"); p,e=g.player1,g.player2
    artificer=play(p,"LOOT_231"); fireball=play(p,FIREBALL,target=e.hero); after_fireball=(p.hero.armor,e.hero.health)
    moonfire=play(p,MOONFIRE,target=e.hero); after_zero=(p.hero.armor,e.hero.health)
    observed=f"artificer={artificer.zone.name};fireball={fireball.zone.name};after_four_cost={after_fireball};moonfire={moonfire.zone.name};after_zero_cost={after_zero}"
    ok=artificer.zone==Zone.PLAY and fireball.zone==Zone.GRAVEYARD and after_fireball==(4,24) and moonfire.zone==Zone.GRAVEYARD and after_zero==(4,23)
    return check(observed,ok,"Arcane Artificer grants Armor equal to each spell's mana Cost: 4 for Fireball and 0 for Moonfire.")


def c233_deathrattle_revenant():
    g=new_game("LOOT_233"); p=g.player1
    disciple=summon(p,"LOOT_233"); disciple.destroy()
    revenants=[m for m in p.field if m.id=="LOOT_233t"]
    observed=f"disciple={disciple.zone.name};revenants={[(m.id,m.atk,m.health,m.zone.name) for m in revenants]}"
    return check(observed,disciple.zone==Zone.GRAVEYARD and len(revenants)==1 and (revenants[0].atk,revenants[0].health)==(5,1),
                 "Cursed Disciple's deathrattle summons one 5/1 Revenant.")


def _draw_from_top(player, card_id):
    """Return the in-hand Morph result, since draw() may return its stale source."""
    deck_top(player,card_id)
    prior = {id(card) for card in player.hand}
    drawn = player.draw()
    added = [card for card in player.hand if id(card) not in prior]
    variants = {
        "LOOT_278": {"LOOT_278t1", "LOOT_278t2", "LOOT_278t3", "LOOT_278t4"},
        "LOOT_285": {"LOOT_285t", "LOOT_285t2", "LOOT_285t3", "LOOT_285t4"},
        "LOOT_286": {"LOOT_286t1", "LOOT_286t2", "LOOT_286t3", "LOOT_286t4"},
    }[card_id]
    morphed = [card for card in added if card.id in variants]
    assert drawn is not None and drawn.id == card_id and drawn.zone == Zone.SETASIDE, (
        f"draw {card_id} source did not become stale after Morph: "
        f"returned={None if drawn is None else (drawn.id, drawn.zone)}"
    )
    assert len(morphed) == 1 and morphed[0].zone == Zone.HAND, (
        f"draw {card_id}: returned={None if drawn is None else (drawn.id, drawn.zone)}; "
        f"added={[(card.id, card.zone) for card in added]}"
    )
    return morphed[0]


def c278_unidentified_elixir_variants():
    samples={}; seen=set(); t4_return=[]
    for seed in range(3000,3048):
        g=new_game("LOOT_278",seed=seed); p=g.player1
        card=_draw_from_top(p,"LOOT_278"); variant=card.id; seen.add(variant)
        target=summon(p,WISP); card.play(target=target)
        copies=[m for m in p.field if m.id==WISP and m is not target]
        result={"target":(target.atk,target.health,target.lifesteal,target.divine_shield,target.has_deathrattle),"copies":[(m.id,m.atk,m.health) for m in copies]}
        if variant=="LOOT_278t1": ok=result["target"][:3]==(3,3,1)
        elif variant=="LOOT_278t2": ok=result["target"][0:2]==(3,3) and result["target"][3]
        elif variant=="LOOT_278t3": ok=result["target"][0:2]==(3,3) and len(copies)==1 and (copies[0].atk,copies[0].health)==(1,1)
        elif variant=="LOOT_278t4":
            target.destroy()
            t4_return.append(f"field={ids(p.field)};hand={[(m.id,m.zone.name) for m in p.hand]};dead={target.zone.name}")
            ok=target.zone==Zone.GRAVEYARD and any(m.id==WISP for m in p.hand)
        else: ok=False
        samples.setdefault(variant,[]).append(f"seed={seed};{result}")
        if not ok:
            return check(f"variant={variant};seed={seed};result={result};t4={t4_return[-1:]}",False,
                         "Each in-hand bonus variant applies its described +2/+2 and bonus effect; Elixir of Hope returns its minion to hand on death.")
    expected={"LOOT_278t1","LOOT_278t2","LOOT_278t3","LOOT_278t4"}
    observed=f"variants={sorted(seen)};samples={ {k:v[0] for k,v in samples.items()} };elixir_of_hope={t4_return[:2]}"
    return check(observed,seen==expected,"Across seeded draws, all four bonus variants apply their described +2/+2 and bonus effect, including return to hand on death.")


def c285_unidentified_shield_variants():
    samples={}; seen=set()
    for seed in range(3100,3148):
        g=new_game("LOOT_285",seed=seed); p,e=g.player1,g.player2
        enemy=summon(e,"EX1_399"); card=_draw_from_top(p,"LOOT_285"); variant=card.id
        if variant=="LOOT_285t2": card.play(target=enemy)
        else: card.play()
        minions=[m for m in p.field if m.id=="LOOT_285t3t"]
        weapon=p.weapon
        result=f"armor={p.hero.armor};enemy={enemy.zone.name}/{enemy.health}/{enemy.damage};golem={[(m.atk,m.health) for m in minions]};weapon={None if weapon is None else (weapon.atk,weapon.durability)}"
        seen.add(variant); samples.setdefault(variant,result)
        checks={
            "LOOT_285t":p.hero.armor==15,
            "LOOT_285t2":p.hero.armor==5 and enemy.damage==5,
            "LOOT_285t3":p.hero.armor==5 and len(minions)==1 and (minions[0].atk,minions[0].health)==(5,5),
            "LOOT_285t4":p.hero.armor==5 and weapon is not None and weapon.atk==5 and weapon.durability==2,
        }
        if not checks.get(variant,False):
            return check(f"variant={variant};{result}",False,"Each Unidentified Shield bonus applies in addition to the base 5 Armor.")
    expected={"LOOT_285t","LOOT_285t2","LOOT_285t3","LOOT_285t4"}
    observed=f"variants={sorted(seen)};samples={samples}"
    return check(observed,seen==expected,"Across seeded draws, all four Unidentified Shield variants gain the base 5 Armor and resolve their bonus.")


def c286_unidentified_maul_variants():
    samples={}; seen=set()
    for seed in range(3200,3248):
        g=new_game("LOOT_286",seed=seed); p=g.player1
        minion=summon(p,WISP); card=_draw_from_top(p,"LOOT_286"); variant=card.id; card.play()
        recruits=[m for m in p.field if m.id=="CS2_101t"]
        result=f"weapon={card.id}/{card.zone.name};minion={minion.atk}/{minion.health}/taunt:{minion.taunt}/shield:{minion.divine_shield};recruits={len(recruits)}"
        seen.add(variant); samples.setdefault(variant,result)
        checks={
            "LOOT_286t1":len(recruits)==2,
            "LOOT_286t2":minion.taunt,
            "LOOT_286t3":minion.atk==2,
            "LOOT_286t4":minion.divine_shield,
        }
        if not checks.get(variant,False):
            return check(f"variant={variant};{result}",False,"Each Unidentified Maul bonus applies to friendly minions or summons the two Recruit tokens.")
    expected={"LOOT_286t1","LOOT_286t2","LOOT_286t3","LOOT_286t4"}
    observed=f"variants={sorted(seen)};samples={samples}"
    return check(observed,seen==expected,"Across seeded draws, all four Unidentified Maul variants resolve their own Battlecry effect.")


def c291_restore_four_health():
    g=new_game("LOOT_291"); p,e=g.player1,g.player2
    target=summon(p,"EX1_399"); g.end_turn()
    for _ in range(4): play(e,MOONFIRE,target=target)
    g.end_turn(); before=(target.health,target.damage)
    brewer=play(p,"LOOT_291",target=target)
    observed=f"before={before};target={target.health}/{target.damage};brewer={brewer.zone.name};field={ids(p.field)}"
    return check(observed,before==(3,4) and target.health==7 and target.damage==0 and brewer.zone==Zone.PLAY,
                 "Shroom Brewer restores exactly 4 Health to the selected damaged minion.")


def c306_recruit_demon():
    g=new_game("LOOT_306"); p=g.player1
    demon=deck_top(p,"LOOT_368"); deck_top(p,WISP)
    lackey=summon(p,"LOOT_306"); lackey.destroy()
    observed=f"lackey={lackey.zone.name};demon={demon.id}/{demon.race}/{demon.zone.name};field={[(m.id,m.atk,m.health) for m in p.field]};deck={ids(p.deck)}"
    return check(observed,lackey.zone==Zone.GRAVEYARD and demon.zone==Zone.PLAY and demon in p.field,
                 "Possessed Lackey recruits the only Demon in the deck when it dies.")


def c306_no_demon():
    g=new_game("LOOT_306"); p=g.player1
    deck_top(p,WISP); lackey=summon(p,"LOOT_306"); lackey.destroy()
    observed=f"lackey={lackey.zone.name};field={ids(p.field)};deck={ids(p.deck)}"
    return check(observed,lackey.zone==Zone.GRAVEYARD and not p.field,
                 "Possessed Lackey summons nothing when the deck has no Demon.")


def c309_armor_and_recruit():
    g=new_game("LOOT_309"); p=g.player1
    eligible=deck_top(p,"CS2_182"); deck_top(p,"LOOT_153")
    spell=play(p,"LOOT_309")
    observed=f"spell={spell.zone.name};armor={p.hero.armor};eligible={eligible.id}/{eligible.cost}/{eligible.zone.name};field={[(m.id,m.cost,m.atk,m.health) for m in p.field]}"
    return check(observed,spell.zone==Zone.GRAVEYARD and p.hero.armor==6 and eligible.zone==Zone.PLAY and eligible in p.field,
                 "Oaken Summons grants 6 Armor and recruits the only minion costing 4 or less.")


def c313_discount_divine_shield():
    g=new_game("LOOT_313"); p=g.player1
    r1=summon(p,"CS2_101t"); r2=summon(p,"CS2_101t"); lion=give(p,"LOOT_313"); base=lion.data.cost
    cost_two=lion.cost; r1.destroy(); cost_one=lion.cost; lion.play()
    observed=f"base={base};cost_two={cost_two};cost_one={cost_one};recruits={r1.zone.name},{r2.zone.name};lion={lion.zone.name}/{lion.atk}/{lion.health}/shield:{lion.divine_shield}"
    ok=cost_two==base-2 and cost_one==base-1 and lion.zone==Zone.PLAY and lion.divine_shield and r2.zone==Zone.PLAY
    return check(observed,ok,"Crystal Lion costs 1 less per Recruit controlled, updates after a Recruit dies, and enters with Divine Shield.")


def c314_taunt_and_two_recruits():
    g=new_game("LOOT_314"); p=g.player1
    a=deck_top(p,WISP); b=deck_top(p,"CS2_182"); deck_top(p,"LOOT_153")
    guardian=summon(p,"LOOT_314"); taunt=guardian.taunt; guardian.destroy()
    recruited=[m for m in p.field if m.id in {WISP,"CS2_182"}]
    observed=f"taunt_before_death={taunt};guardian={guardian.zone.name};recruited={[(m.id,m.cost,m.zone.name) for m in recruited]};deck={[(m.id,m.cost) for m in p.deck]}"
    ok=taunt and guardian.zone==Zone.GRAVEYARD and len(recruited)==2 and {m.id for m in recruited}=={WISP,"CS2_182"} and a.zone==Zone.PLAY and b.zone==Zone.PLAY
    return check(observed,ok,"Grizzled Guardian has Taunt and its deathrattle recruits two minions costing 4 or less, skipping the 8-Cost minion.")


def c315_taunt_poisonous_combat():
    g=new_game("LOOT_315"); p,e=g.player1,g.player2
    trogg=summon(p,"LOOT_315"); attacker=summon(e,"EX1_399"); g.end_turn(); blocked=None
    try: attacker.attack(p.hero)
    except InvalidAction as exc: blocked=type(exc).__name__
    attacker.attack(trogg)
    observed=f"trogg={trogg.zone.name}/{trogg.atk}/{trogg.health}/{trogg.poisonous}/{trogg.taunt};enemy={attacker.zone.name}/{attacker.damage};hero={p.hero.health};blocked={blocked}"
    return check(observed,blocked=="InvalidAction" and attacker.zone==Zone.GRAVEYARD and trogg.zone==Zone.PLAY and p.hero.health==30 and trogg.poisonous and trogg.taunt,
                 "Trogg Gloomeater has Taunt and Poisonous: the hero cannot be attacked while it stands, and its combat poison kills a larger attacker.")


def c329_summons_copy_after_minion_play():
    g=new_game("LOOT_329"); p=g.player1
    ix=summon(p,"LOOT_329"); wisp=play(p,WISP)
    copies=[m for m in p.field if m.id==WISP]
    observed=f"ixlid={ix.zone.name};played={wisp.zone.name};wisps={[(m.atk,m.health,m.zone.name) for m in copies]};field={ids(p.field)}"
    return check(observed,ix.zone==Zone.PLAY and wisp.zone==Zone.PLAY and len(copies)==2 and all((m.atk,m.health)==(1,1) for m in copies),
                 "After a minion is played, Ixlid summons one copy of it without replaying the minion.")


def c333_level_up_recruits():
    g=new_game("LOOT_333"); p=g.player1
    recruits=[summon(p,"CS2_101t") for _ in range(2)]; other=summon(p,WISP); before=(other.atk,other.health)
    spell=play(p,"LOOT_333")
    observed=f"spell={spell.zone.name};recruits={[(m.atk,m.health,m.taunt) for m in recruits]};other={(other.atk,other.health)};before={before}"
    ok=spell.zone==Zone.GRAVEYARD and all((m.atk,m.health,m.taunt)==(3,3,True) for m in recruits) and (other.atk,other.health)==before
    return check(observed,ok,"Level Up! gives each Silver Hand Recruit +2/+2 and Taunt while leaving other minions unchanged.")


def c344_give_deathrattle_totem():
    g=new_game("LOOT_344"); p=g.player1
    minions=[summon(p,WISP),summon(p,"EX1_399")]; spell=play(p,"LOOT_344")
    before=[(m.id,m.has_deathrattle) for m in minions]
    for m in minions: m.destroy()
    totems=[m for m in p.field if m.id in {"CS2_050","CS2_051","CS2_052","NEW1_009"}]
    observed=f"spell={spell.zone.name};before_deathrattle={before};dead={[m.zone.name for m in minions]};totems={[(m.id,m.atk,m.health) for m in totems]};field={ids(p.field)}"
    ok=spell.zone==Zone.GRAVEYARD and all(x[1] for x in before) and all(m.zone==Zone.GRAVEYARD for m in minions) and len(totems)==2
    return check(observed,ok,"Primal Talismans grants each friendly minion a deathrattle that summons one random Basic Totem when it dies.")


def c347_random_damage_all_enemies():
    results=[]; hero_damage=[]
    for seed in range(3300,3316):
        g=new_game("LOOT_347",seed=seed); p,e=g.player1,g.player2
        friendly=summon(p,"EX1_399"); enemies=[summon(e,"EX1_399"),summon(e,"CS2_182")]; before=[m.health for m in enemies]
        spell=play(p,"LOOT_347")
        dealt=[before[i]-enemies[i].health for i in range(2)]; hero_loss=30-e.hero.health
        results.append((dealt,hero_loss)); hero_damage.append(hero_loss)
        if spell.zone!=Zone.PLAY or sum(dealt)+hero_loss!=3 or friendly.damage!=0:
            return check(f"seed={seed};minion_damage={dealt};hero_damage={hero_loss};friendly={friendly.damage}",False,
                         "Three damage points are randomly distributed among all enemy characters, with no friendly damage.")
    observed=f"seeded_minion_and_hero_damage={results};hero_damaged_games={sum(v>0 for v in hero_damage)}"
    return check(observed,any(x>0 for x in hero_damage),"Across seeded games, three damage is split among enemy minions and the enemy hero, with no friendly damage.")


def c347_enemy_hero_only():
    g=new_game("LOOT_347"); p,e=g.player1,g.player2
    apprentice=play(p,"LOOT_347"); observed=f"apprentice={apprentice.zone.name};enemy_hero={e.hero.health}/30;enemy_field={ids(e.field)}"
    return check(observed,apprentice.zone==Zone.PLAY and e.hero.health==27 and not e.field,
                 "With no enemy minions, all three randomly split damage points hit the enemy hero.")


def c351_empty_mana_crystal():
    g=new_game("LOOT_351"); p=g.player1
    p.max_mana=3; p.used_mana=0
    sprite=summon(p,"LOOT_351"); before=(p.max_mana,p.mana); sprite.destroy(); after=(p.max_mana,p.mana)
    observed=f"sprite={sprite.zone.name};mana_before={before};mana_after={after};used={p.used_mana}"
    return check(observed,sprite.zone==Zone.GRAVEYARD and after[0]==before[0]+1 and after[1]==before[1],
                 "Greedy Sprite's deathrattle adds one empty Mana Crystal without filling it.")


def c353_copy_opponent_spell():
    g=new_game("LOOT_353"); p,e=g.player1,g.player2
    spell=deck_top(e,FIREBALL); deck_top(e,WISP); probe=play(p,"LOOT_353")
    copies=[m for m in p.hand if m.id==FIREBALL]
    observed=f"probe={probe.zone.name};opponent_spell={spell.id}/{spell.zone.name};own_copies={[(m.id,m.type,m.zone.name) for m in copies]};opponent_deck={[(m.id,m.zone.name) for m in e.deck]}"
    return check(observed,probe.zone==Zone.GRAVEYARD and spell.zone==Zone.DECK and len(copies)==1 and copies[0].type==CardType.SPELL,
                 "Psionic Probe copies an opponent-deck spell into hand while leaving the original in that deck.")


def c357_treasure_chest_and_board_ownership():
    g=new_game("LOOT_357"); p,e=g.player1,g.player2
    marin=play(p,"LOOT_357"); chest=next((m for m in e.field if m.id=="LOOT_357l"),None)
    before=(chest.atk,chest.health,chest.zone.name) if chest else None
    if chest: chest.destroy()
    treasures={"LOOT_998h","LOOT_998j","LOOT_998l","LOOT_998k"}
    found=[m for m in p.hand if m.id in treasures]
    enemy_found=[m for m in e.hand if m.id in treasures]
    observed=f"marin={marin.zone.name};chest_before={before};chest_after={None if chest is None else chest.zone.name};marin_hand={[(m.id,m.zone.name) for m in found]};enemy_hand={[(m.id,m.zone.name) for m in enemy_found]}"
    ok=marin.zone==Zone.PLAY and chest is not None and before==(0,8,"PLAY") and chest.zone==Zone.GRAVEYARD and len(found)==1 and not enemy_found
    return check(observed,ok,"Marin summons a 0/8 Treasure Chest for the opponent; breaking it gives exactly one treasure to Marin, the chest controller's opponent.")


def c357_friendly_full_board_still_summons():
    g=new_game("LOOT_357"); p,e=g.player1,g.player2
    for _ in range(6): summon(p,WISP)
    marin=play(p,"LOOT_357"); chest=[m for m in e.field if m.id=="LOOT_357l"]
    observed=f"friendly_field={len(p.field)};opponent_field={[(m.id,m.atk,m.health) for m in e.field]};marin={marin.zone.name}"
    return check(observed,len(p.field)==7 and marin.zone==Zone.PLAY and len(chest)==1 and (chest[0].atk,chest[0].health)==(0,8),
                 "The opponent's Chest still summons when Marin fills his controller's seventh board slot.")


def c357_enemy_full_board_caps():
    g=new_game("LOOT_357"); p,e=g.player1,g.player2
    for _ in range(7): summon(e,WISP)
    marin=play(p,"LOOT_357"); chests=[m for m in e.field if m.id=="LOOT_357l"]
    observed=f"marin={marin.zone.name};friendly_field={len(p.field)};opponent_field={len(e.field)};chests={len(chests)}"
    return check(observed,marin.zone==Zone.PLAY and len(e.field)==7 and not chests,
                 "When the opponent's board is full, Marin's Battlecry cannot exceed seven minions.")


def c358_bounce_other_minions_cost_one():
    g=new_game("LOOT_358"); p=g.player1
    a=summon(p,"CS2_182"); b=summon(p,"EX1_399"); grumble=play(p,"LOOT_358")
    returned=[m for m in p.hand if m.id in {"CS2_182","EX1_399"}]
    observed=f"grumble={grumble.zone.name};board={ids(p.field)};returned={[(m.id,m.cost,m.zone.name) for m in returned]}"
    ok=grumble.zone==Zone.PLAY and len(returned)==2 and all(m.cost==1 and m.zone==Zone.HAND for m in returned) and grumble in p.field
    return check(observed,ok,"Grumble returns every other friendly minion to hand at Cost 1 and remains on the board.")


def c363_three_recruits_to_hand():
    g=new_game("LOOT_363"); p=g.player1
    jailor=summon(p,"LOOT_363"); jailor.destroy()
    recruits=[m for m in p.hand if m.id=="CS2_101t"]
    observed=f"jailor={jailor.zone.name};recruits={[(m.id,m.atk,m.health,m.zone.name) for m in recruits]};hand_count={len(p.hand)}"
    return check(observed,jailor.zone==Zone.GRAVEYARD and len(recruits)==3 and all(m.zone==Zone.HAND for m in recruits),
                 "Drygulch Jailor's deathrattle adds exactly three Silver Hand Recruits to hand.")


def c364_spend_all_armor_deal_damage():
    g=new_game("LOOT_364"); p,e=g.player1,g.player2
    play(p,"EX1_606"); friendly=summon(p,"EX1_399"); enemy=summon(e,"EX1_399"); before=(friendly.health,enemy.health)
    spell=play(p,"LOOT_364")
    observed=f"armor=0/{p.hero.armor};before={before};friendly={friendly.zone.name}/{friendly.health}/{friendly.damage};enemy={enemy.zone.name}/{enemy.health}/{enemy.damage};spell={spell.zone.name}"
    ok=p.hero.armor==0 and friendly.zone==Zone.PLAY and enemy.zone==Zone.PLAY and friendly.damage==5 and enemy.damage==5 and spell.zone==Zone.GRAVEYARD
    return check(observed,ok,"Reckless Flurry spends all 5 Armor and deals exactly 5 damage to every minion on both sides.")


def c364_zero_armor():
    g=new_game("LOOT_364"); p,e=g.player1,g.player2
    friendly=summon(p,"EX1_399"); enemy=summon(e,"EX1_399"); spell=play(p,"LOOT_364")
    observed=f"armor={p.hero.armor};friendly={friendly.zone.name}/{friendly.damage};enemy={enemy.zone.name}/{enemy.damage};spell={spell.zone.name}"
    return check(observed,p.hero.armor==0 and friendly.damage==0 and enemy.damage==0 and spell.zone==Zone.GRAVEYARD,
                 "With no Armor to spend, Reckless Flurry deals zero damage to minions.")


def c365_attack_threshold_and_control():
    # At zero Armor the Golem should be blocked, while an ordinary control minion can attack.
    g=new_game("LOOT_365"); p,e=g.player1,g.player2
    golem=summon(p,"LOOT_365"); control=summon(p,"CS2_182"); target=summon(e,"EX1_399")
    g.end_turn(); g.end_turn(); armor_before=p.hero.armor
    control_error=None; golem_error=None
    try: control.attack(target)
    except InvalidAction as exc: control_error=type(exc).__name__
    try: golem.attack(target)
    except InvalidAction as exc: golem_error=type(exc).__name__
    low_observed=f"armor={armor_before};control_error={control_error};control={control.zone.name};golem_error={golem_error};golem={golem.zone.name};target_damage={target.damage}"
    # At exactly 5 Armor, compare a ready ordinary minion with the ready Golem.
    g2=new_game("LOOT_365"); p2,e2=g2.player1,g2.player2
    golem2=summon(p2,"LOOT_365"); control2=summon(p2,"CS2_182"); target2=summon(e2,"EX1_399")
    play(p2,"EX1_606"); g2.end_turn(); g2.end_turn(); armor_at_threshold=p2.hero.armor
    control_error2=None
    try: control2.attack(target2)
    except InvalidAction as exc: control_error2=type(exc).__name__
    golem_error2=None
    try: golem2.attack(target2)
    except InvalidAction as exc: golem_error2=type(exc).__name__
    observed=f"below_threshold={low_observed};at_threshold={armor_at_threshold};control_error={control_error2};control={control2.zone.name}/{control2.atk};golem_error={golem_error2};golem={golem2.zone.name}/{golem2.atk}/{golem2.damage};target={target2.zone.name}/{target2.health}/{target2.damage};active={g2.current_player is p2}"
    ok=armor_before==0 and control_error is None and control.zone==Zone.PLAY and target.damage==control.atk and golem_error=="InvalidAction" and golem.zone==Zone.PLAY and armor_at_threshold==5 and control_error2 is None and golem_error2 is None and golem2.zone==Zone.PLAY and target2.zone==Zone.GRAVEYARD and g2.current_player is p2
    return check(observed,ok,"At 0 Armor the ordinary minion can attack while Gemstudded Golem cannot; at exactly 5 Armor, a ready Golem attacks and destroys a 4/7 enemy minion after the ordinary control has attacked.")


CASES = {
    "LOOT_149": [("death_reduces_hand_cost_each_side", c149_cost_triggers), ("death_after_play_does_not_reduce", c149_only_in_hand)],
    "LOOT_150": [("friendly_target_becomes_6_6_elemental", c150_transform), ("enemy_target_rejected_before_cost", c150_enemy_rejected), ("no_friendly_target_battlecry_skipped", c150_optional_no_target)],
    "LOOT_152": [("battlecry_buffs_all_other_friendly_health", c152_buff_others)],
    "LOOT_153": [("death_summons_seven_one_one_grubs", c153_seven_grubs), ("deathrattle_respects_board_capacity", c153_board_cap)],
    "LOOT_154": [("opponent_gets_random_one_cost_minion", c154_random_one_cost_opponent), ("friendly_full_board_opponent_room", c154_friendly_full_opponent_has_room), ("opponent_full_board_caps_summon", c154_opponent_full_caps)],
    "LOOT_161": [("destroy_friendly_then_two_copies_on_death", c161_cube_deathrattle), ("enemy_target_rejected", c161_enemy_target_rejected)],
    "LOOT_165": [("friendly_death_adds_one_one_copy_cost_one", c165_friendly_death_copy), ("enemy_death_does_not_trigger", c165_enemy_death_ignored)],
    "LOOT_167": [("only_adjacent_minions_gain_two_two", c167_adjacent_only)],
    "LOOT_170": [("higher_friendly_joust_spell_drawn", c170_own_higher_cost_spell_drawn), ("lower_friendly_joust_spell_not_drawn", c170_not_higher_no_draw)],
    "LOOT_172": [("revealed_spell_cost_is_aoe_damage", c172_reveal_cost_aoe)],
    "LOOT_184": [("deathrattle_recruits_eight_cost", c184_recruit_eight_cost), ("no_eight_cost_recruits_nothing", c184_no_eight_cost)],
    "LOOT_187": [("summons_two_one_one_dead_friendly_deathrattles", c187_dead_friendly_copies)],
    "LOOT_193": [("friendly_spell_can_target_courser", c193_friendly_spell_target), ("opponent_spell_and_hero_power_cannot_target", c193_enemy_spell_and_power_blocked)],
    "LOOT_203": [("two_weapons_upgrade_to_three_golems", c203_upgrade_each_equipped_weapon)],
    "LOOT_204": [("friendly_death_returns_with_two_cost_discount", c204_friendly_death_bounces_discounted), ("enemy_death_leaves_secret_armed", c204_enemy_death_does_not_trigger)],
    "LOOT_209": [("third_spell_summons_dragon_per_turn", c209_three_spell_threshold_each_turn)],
    "LOOT_210": [("attack_at_hero_redirected_to_neighbor", c210_secret_redirects_attack)],
    "LOOT_211": [("combo_draws_two_minions", c211_combo_draws_two_minions)],
    "LOOT_214": [("hero_damage_triggers_immunity_until_turn_end", c214_damage_then_immune)],
    "LOOT_216": [("recasts_spells_cast_on_friendly_minions", c216_recasts_friendly_minion_spells)],
    "LOOT_217": [("one_companion_with_minions_two_without", c217_one_or_two_companions)],
    "LOOT_218": [("hero_attack_adds_copy_to_hand", c218_attack_hero_copy_only), ("minion_attack_does_not_add_copy", c218_attack_minion_no_copy)],
    "LOOT_222": [("hero_immune_during_weapon_attack", c222_immune_while_attacking)],
    "LOOT_231": [("armor_gain_matches_spell_cost_including_zero", c231_armor_matches_spell_cost)],
    "LOOT_233": [("deathrattle_summons_five_one_revenant", c233_deathrattle_revenant)],
    "LOOT_278": [("drawn_variant_plus_two_two_and_bonus", c278_unidentified_elixir_variants)],
    "LOOT_285": [("drawn_variant_five_armor_and_bonus", c285_unidentified_shield_variants)],
    "LOOT_286": [("drawn_maul_variant_applies_bonus", c286_unidentified_maul_variants)],
    "LOOT_291": [("battlecry_restores_four_health", c291_restore_four_health)],
    "LOOT_306": [("deathrattle_recruits_demon", c306_recruit_demon), ("no_demon_recruits_nothing", c306_no_demon)],
    "LOOT_309": [("six_armor_and_recruit_cost_four_or_less", c309_armor_and_recruit)],
    "LOOT_313": [("cost_tracks_recruit_count_and_divine_shield", c313_discount_divine_shield)],
    "LOOT_314": [("taunt_and_two_recruits_cost_four_or_less", c314_taunt_and_two_recruits)],
    "LOOT_315": [("taunt_blocks_hero_and_poisonous_kills_attacker", c315_taunt_poisonous_combat)],
    "LOOT_329": [("played_minion_creates_one_copy", c329_summons_copy_after_minion_play)],
    "LOOT_333": [("buffs_recruits_only", c333_level_up_recruits)],
    "LOOT_344": [("minion_death_summons_basic_totem", c344_give_deathrattle_totem)],
    "LOOT_347": [("three_damage_split_among_all_enemies", c347_random_damage_all_enemies), ("enemy_hero_only_damage", c347_enemy_hero_only)],
    "LOOT_351": [("deathrattle_adds_empty_mana_crystal", c351_empty_mana_crystal)],
    "LOOT_353": [("copies_opponent_deck_spell_without_removing_original", c353_copy_opponent_spell)],
    "LOOT_357": [("summons_treasure_chest_and_rewards_treasure", c357_treasure_chest_and_board_ownership), ("friendly_full_board_opponent_has_room", c357_friendly_full_board_still_summons), ("opponent_full_board_caps_chest", c357_enemy_full_board_caps)],
    "LOOT_358": [("returns_other_minions_at_cost_one", c358_bounce_other_minions_cost_one)],
    "LOOT_363": [("deathrattle_adds_three_recruits", c363_three_recruits_to_hand)],
    "LOOT_364": [("spends_all_armor_and_deals_equal_damage", c364_spend_all_armor_deal_damage), ("zero_armor_zero_damage", c364_zero_armor)],
    "LOOT_365": [("armor_threshold_and_regular_minion_control", c365_attack_threshold_and_control)],
}


def run():
    probe_rows = []
    verdict_rows = []
    seen_cases = set()
    active_ids = OWN_IDS[: int(sys.argv[1])] if len(sys.argv) > 1 else OWN_IDS
    for card_id in active_ids:
        card_rows = []
        funcs = CASES.get(card_id, [])
        for case_id, fn in funcs:
            key = (card_id, case_id)
            assert key not in seen_cases, f"duplicate case {key}"
            seen_cases.add(key)
            try:
                expected, observed, passed = fn()
                outcome = "pass" if passed else "confirmed_error"
            except Exception as exc:  # Fixture/API blockers remain YELLOW until resolved.
                expected = "Bespoke live assertion for the documented core behavior."
                observed = f"{type(exc).__name__}: {exc}"
                outcome = "inconclusive"
            row = {"card_id": card_id, "case_id": case_id, "expected": expected,
                   "observed": observed, "outcome": outcome, "notes": metadata(card_id)}
            card_rows.append(row)
            print(f"{card_id} {case_id}: {outcome} | {observed}", flush=True)
        probe_rows.extend(card_rows)
        outcomes = [r["outcome"] for r in card_rows]
        mechanisms = QUALITY_BY_ID[card_id]["mechanic"]
        if not funcs:
            status = "YELLOW"
            reason = "No live behavioral case has been implemented yet."
        elif "confirmed_error" in outcomes:
            status = "RED"
            reason = "A live case confirmed a card behavior mismatch; see the failing case row."
        elif "inconclusive" in outcomes:
            status = "YELLOW"
            blocked = [f"{r['case_id']}={r['observed']}" for r in card_rows if r["outcome"] == "inconclusive"]
            reason = "Concrete live-probe blocker: " + "; ".join(blocked)
        else:
            status = "GREEN"
            passed = [f"{r['case_id']} observed {r['observed']}" for r in card_rows]
            reason = "All live cases passed: " + "; ".join(passed)
        if status == "RED":
            failed = [f"{r['case_id']} observed {r['observed']}" for r in card_rows if r["outcome"] == "confirmed_error"]
            reason = "Confirmed live mismatch: " + "; ".join(failed)
        verdict_rows.append({"card_id": card_id, "status": status, "mechanic_scope": mechanisms,
                             "reason": reason, "probe_file": PROBE_OUT.name,
                             "notes": f"Cases={len(card_rows)}; per-case rows include EN/ZH text, source, existing tests, prior card and mechanism audit."})
        write_csv(PROBE_OUT, PROBE_FIELDS, probe_rows)
        write_csv(VERDICT_OUT, VERDICT_FIELDS, verdict_rows)
        print(f"updated {card_id}: {status} ({len(probe_rows)} total cases)", flush=True)
    assert {r["card_id"] for r in verdict_rows} == set(active_ids)
    assert len({r["card_id"] for r in verdict_rows}) == len(active_ids)
    assert len(seen_cases) == len(probe_rows)
    counts = {status: sum(r["status"] == status for r in verdict_rows) for status in ("GREEN", "RED", "YELLOW")}
    print(f"SUMMARY cards={len(verdict_rows)} cases={len(probe_rows)} {counts}", flush=True)


if __name__ == "__main__":
    run()
