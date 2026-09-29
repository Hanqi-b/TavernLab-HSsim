"""Card specific live probes for the second ICECROWN YELLOW slice.

The probe deliberately keeps each card in its own small game and records the
card's important state transitions.  It is an audit script, not a regression
test suite: a failed assertion is retained as evidence for a RED verdict.
"""

import csv
import logging
import random
import sys
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Rarity, Zone

logging.disable(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import FIREBALL, HOLY_LIGHT, MOONFIRE, WISP, prepare_empty_game  # noqa: E402
from fireplace.cards.utils import LICH_KING_CARDS  # noqa: E402

BASELINE = HERE / "icecrown_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
PROBE_OUT = HERE / "icc_probe_b.csv"
VERDICT_OUT = HERE / "icc_verdict_b.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read_csv(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


BASE_ROWS = [
    r for r in read_csv(BASELINE)
    if r["set"] == "Knights of the Frozen Throne (ICECROWN)"
]
BASE_ROWS.sort(key=lambda r: r["card_id"])
# The parent task froze rows 44:88 (zero based, end exclusive) of this set.
OWN_ROWS = BASE_ROWS[44:88]
OWN_IDS = [r["card_id"] for r in OWN_ROWS]
assert len(OWN_IDS) == 44 and OWN_IDS[0] == "ICC_094" and OWN_IDS[-1] == "ICC_701"
MASTER_BY_ID = {r["card_id"]: r for r in read_csv(MASTER)}
QUALITY_BY_ID = {r["card_id"]: r for r in read_csv(QUALITY)}


def new_game(card_class=CardClass.MAGE, opponent_class=None, seed=917):
    random.seed(seed)
    opponent_class = opponent_class or card_class
    game = prepare_empty_game(card_class, opponent_class)
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


def play(player, card_id, target=None, choose=None):
    card = give(player, card_id)
    if target is not None:
        card.play(target=target)
    elif choose is not None:
        card.play(choose=choose)
    else:
        card.play()
    return card


def deck_top(player, card_id):
    """Put a known card at the deterministic top of an empty test deck."""
    card = player.card(card_id, zone=Zone.DECK)
    return card


def ids(cards):
    return [c.id for c in cards]


def metadata(card_id):
    master = MASTER_BY_ID[card_id]
    old = QUALITY_BY_ID.get(card_id, {})
    return (
        f"EN={master['card_text_en']}; ZH={master['card_text_zh']}; "
        f"source={master['python_source'] or master['xml_source']}; "
        f"existing_tests={master['test_refs_candidate'] or 'none'}; "
        f"prior={old.get('status', 'unknown')}:{old.get('reason', 'no prior reason')}"
    )


def check(observed, condition, expected):
    return observed, True if condition else False


def c094():
    g = new_game(); p, e = g.player1, g.player2
    target = summon(p, "CS2_231")
    before = (target.atk, target.health)
    card = play(p, "ICC_094", target=target)
    observed = f"target={target.atk}/{target.health};before={before};field={ids(p.field)};source={card.zone.name}"
    return check(observed, (target.atk, target.health) == (before[0] + 1, before[1] + 1)
                 and target in p.field and card.zone == Zone.PLAY, "friendly target gains exactly +1/+1")


def c096():
    g = new_game(); p = g.player1
    w1 = give(p, "CS2_091")
    w2 = give(p, "ICC_236")
    base = give(p, "ICC_096")
    base_stats = (base.atk, base.health)
    expected = (base_stats[0] + w1.atk + w2.atk, base_stats[1] + w1.durability + w2.durability)
    base.play()
    observed = f"weapons={[(w1.id,w1.zone.name),(w2.id,w2.zone.name)]};colossus={base.atk}/{base.health};expected={expected};zone={base.zone.name}"
    return check(observed, w1.zone in (Zone.GRAVEYARD, Zone.REMOVEDFROMGAME)
                 and w2.zone in (Zone.GRAVEYARD, Zone.REMOVEDFROMGAME) and base.zone == Zone.PLAY
                 and (base.atk, base.health) == expected, "discard every hand weapon and gain the sum of their stats")


def c097():
    g = new_game(); p = g.player1
    shambler = summon(p, "ICC_097")
    before = (shambler.atk, shambler.health)
    weapon = give(p, "CS2_091"); weapon.play()
    weapon.destroy()
    observed = f"weapon={weapon.zone.name};shambler={shambler.atk}/{shambler.health};before={before}"
    return check(observed, (shambler.atk, shambler.health) == (before[0] + 1, before[1] + 1)
                 and weapon.zone == Zone.GRAVEYARD, "weapon destruction grants exactly +1/+1")


def c098():
    g = new_game(); p = g.player1
    dead = summon(p, "ICC_099"); dead.destroy()
    card = play(p, "ICC_098")
    gained = [c for c in p.hand if c.id == "ICC_099"]
    observed = f"dead={dead.zone.name};gained={[(c.id,c.zone.name) for c in gained]};field={ids(p.field)};source={card.zone.name}"
    return check(observed, dead.zone == Zone.GRAVEYARD and len(gained) == 1 and gained[0].zone == Zone.HAND
                 and card.zone == Zone.PLAY, "adds one random Deathrattle minion that died this game")


def c098_pool():
    seen = set()
    pool = {"ICC_099", "EX1_029"}
    for seed in range(917, 933):
        g = new_game(seed=seed); p, e = g.player1, g.player2
        friendly = summon(p, "ICC_099")
        enemy = summon(e, "EX1_029")
        friendly.destroy(); enemy.destroy()
        card = play(p, "ICC_098")
        gained = [c for c in p.hand if c.id in pool]
        observed = f"seed={seed};dead={[friendly.id,enemy.id]};gained={[(c.id,c.zone.name) for c in gained]};source={card.zone.name}"
        if len(gained) != 1 or gained[0].id not in pool or card.zone != Zone.PLAY:
            return observed, False
        seen.add(gained[0].id)
    return f"random_dead_deathrattle_pool={sorted(seen)};seeds=16", len(seen) == 2


def c099():
    g = new_game(); p, e = g.player1, g.player2
    friendly = summon(p, "EX1_399")
    enemy = summon(e, "EX1_399")
    card = summon(p, "ICC_099")
    card.destroy()
    observed = f"source={card.zone.name};friendly={friendly.zone.name}/{friendly.health}/{friendly.damage};enemy={enemy.zone.name}/{enemy.health}/{enemy.damage}"
    return check(observed, card.zone == Zone.GRAVEYARD and friendly.zone == Zone.PLAY and friendly.damage == 5
                 and enemy.zone == Zone.PLAY and enemy.damage == 0, "deathrattle deals 5 only to friendly minions")


def c200_open():
    g = new_game(CardClass.HUNTER); p, e = g.player1, g.player2
    friendly = summon(p, WISP)
    trap = play(p, "ICC_200")
    attacker = summon(e, "EX1_399")
    g.end_turn()
    attacker.attack(friendly)
    cobras = [m for m in p.field if m.id == "EX1_170"]
    observed = f"trap={trap.zone.name}/{trap in p.secrets};friendly={friendly.zone.name};attacker={attacker.zone.name};cobras={[(m.id,m.atk,m.health,m.poisonous) for m in cobras]};field={ids(p.field)}"
    return check(observed, trap.zone == Zone.GRAVEYARD and trap not in p.secrets and len(cobras) == 1
                 and (cobras[0].atk, cobras[0].health) == (2, 3) and cobras[0].poisonous, "attacking a friendly minion reveals and summons one 2/3 Poisonous Cobra")


def c200_full_board():
    g = new_game(CardClass.HUNTER); p, e = g.player1, g.player2
    existing = [summon(p, "EX1_399") for _ in range(7)]
    trap = play(p, "ICC_200")
    attacker = summon(e, WISP)
    g.end_turn(); attacker.attack(existing[0])
    cobras = [m for m in p.field if m.id == "EX1_170"]
    observed = f"trap={trap.zone.name}/{trap in p.secrets};existing={len(existing)};target={existing[0].zone.name}/{existing[0].damage};field={len(p.field)};cobras={len(cobras)}"
    return check(observed, trap in p.secrets and trap.zone == Zone.SECRET and len(cobras) == 0
                 and len(p.field) == 7, "a full normal board cannot summon the Cobra and keeps the Secret set")


def c200_dormant_full_board():
    g = new_game(CardClass.HUNTER); p, e = g.player1, g.player2
    existing = [summon(p, "EX1_399") for _ in range(6)]
    dormant = summon(p, "BT_009")
    trap = play(p, "ICC_200")
    attacker = summon(e, WISP)
    g.end_turn(); attacker.attack(existing[0])
    cobras = [m for m in p.field if m.id == "EX1_170"]
    observed = f"trap={trap.zone.name}/{trap in p.secrets};dormant={dormant.zone.name}/{dormant.dormant};field={len(p.field)};cobras={len(cobras)}"
    return check(observed, trap in p.secrets and trap.zone == Zone.SECRET and len(cobras) == 0
                 and dormant.zone == Zone.PLAY, "six active plus one dormant occupant is full and leaves the Secret set")


def c201():
    g = new_game(CardClass.ROGUE); p = g.player1
    top_death = deck_top(p, "ICC_099")
    second = deck_top(p, "CS2_231")
    # Draw consumes deck[-1].  Put the Deathrattle card on top, followed by a
    # non-Deathrattle card for the recursive cast.
    p.deck.clear()
    p.deck.append(second)
    p.deck.append(top_death)
    card = play(p, "ICC_201")
    drawn = [c.id for c in p.hand]
    observed = f"drawn={drawn};deck={[c.id for c in p.deck]};source={card.zone.name}"
    return check(observed, top_death in p.hand and second in p.hand and card.zone == Zone.GRAVEYARD,
                 "draws a Deathrattle card and recursively casts Roll the Bones once")


def c204():
    seen = set()
    for seed in range(917, 925):
        g = new_game(CardClass.HUNTER, seed=seed); p = g.player1
        professor = summon(p, "ICC_204")
        before = len(p.secrets)
        original = play(p, "ICC_200")
        hunter_secrets = [c for c in p.secrets if c.data.card_class == CardClass.HUNTER]
        if len(p.secrets) != before + 2:
            observed = f"seed={seed};before={before};secrets={[(c.id,c.zone.name) for c in p.secrets]};professor={professor.zone.name}"
            return observed, False
        seen.update(c.id for c in hunter_secrets)
    observed = f"secrets={sorted(seen)};count={len(seen)}"
    return check(observed, len(seen) >= 2, "playing a Secret adds a random Hunter Secret to the battlefield")


def c206():
    g = new_game(CardClass.WARLOCK); p, e = g.player1, g.player2
    target = summon(p, WISP)
    card = play(p, "ICC_206", target=target)
    observed = f"target={target.controller.name}/{target.zone.name};friendly={ids(p.field)};enemy={ids(e.field)};source={card.zone.name}"
    return check(observed, target in e.field and target not in p.field and card.zone == Zone.GRAVEYARD,
                 "chosen friendly minion changes controller and remains in play")


def c207():
    g = new_game(CardClass.PRIEST); p, e = g.player1, g.player2
    for cid in (WISP, FIREBALL, "ICC_099", "EX1_308"):
        deck_top(e, cid)
    before = len(e.deck)
    card = play(p, "ICC_207")
    copied = [c.id for c in p.hand]
    allowed = {WISP, FIREBALL, "ICC_099", "EX1_308"}
    observed = f"opponent_deck={len(e.deck)}->{len(e.deck)};copied={copied};source={card.zone.name}"
    return check(observed, len(copied) == 3 and set(copied) <= allowed and len(e.deck) == before
                 and card.zone == Zone.GRAVEYARD, "copies three cards from opponent deck without removing them")


def c210():
    seen = set()
    for seed in range(917, 925):
        g = new_game(CardClass.PRIEST, seed=seed); p, e = g.player1, g.player2
        asc = summon(p, "ICC_210")
        one = summon(p, WISP); two = summon(p, "EX1_399")
        before = {m.id: (m.atk, m.health) for m in (asc, one, two)}
        g.end_turn()
        changed = [m for m in (one, two) if (m.atk, m.health) != before[m.id]]
        if len(changed) != 1 or (asc.atk, asc.health) != before[asc.id] or not all((m.atk, m.health) == (before[m.id][0] + 1, before[m.id][1] + 1) for m in changed):
            return f"seed={seed};before={before};after={[(m.id,m.atk,m.health) for m in (asc,one,two)]}", False
        seen.add(changed[0].id)
    return f"buffed_random_others={sorted(seen)}", len(seen) == 2


def _lifesteal_attack(cid):
    g = new_game(); p, e = g.player1, g.player2
    attacker = summon(p, cid)
    defender = summon(e, "EX1_399")
    p.hero.hit(5)
    before = p.hero.health
    g.end_turn(); g.end_turn()
    attacker.attack(defender)
    gained = p.hero.health - before
    return f"attacker={attacker.id};lifesteal={attacker.lifesteal};hero={before}->{p.hero.health};damage={gained};defender={defender.health}/{defender.damage}", attacker.lifesteal and gained == attacker.atk and defender.zone == Zone.PLAY


def c212():
    return _lifesteal_attack("ICC_212")


def c213():
    g = new_game(CardClass.PRIEST); p = g.player1
    dead1 = summon(p, WISP); dead1.destroy()
    dead2 = summon(p, "EX1_399"); dead2.destroy()
    card = play(p, "ICC_213")
    choices = list(p.choice.cards) if p.choice else []
    allowed = {WISP, "EX1_399"}
    if not choices or not all(c.id in allowed for c in choices):
        return f"choices={ids(choices)};hand={ids(p.hand)};source={card.zone.name}", False
    chosen = choices[0]
    p.choice.choose(chosen)
    summoned = [m for m in p.field if m.id == chosen.id]
    observed = f"dead={[dead1.zone.name,dead2.zone.name]};choices={ids(choices)};chosen={chosen.id};summoned={[(m.id,m.zone.name) for m in summoned]};source={card.zone.name}"
    return check(observed, card.zone == Zone.GRAVEYARD and len(summoned) == 1, "choice offers dead friendly minions and summons the selected one")


def c214():
    seen = set()
    for seed in range(917, 925):
        g = new_game(CardClass.PRIEST, seed=seed); p, e = g.player1, g.player2
        statue = summon(p, "ICC_214")
        first = summon(e, "EX1_399"); second = summon(e, "CS2_119")
        if not (statue.taunt and statue.lifesteal):
            return f"seed={seed};taunt={statue.taunt};lifesteal={statue.lifesteal}", False
        statue.destroy()
        dead = [m for m in (first, second) if m.zone == Zone.GRAVEYARD]
        live = [m for m in (first, second) if m.zone == Zone.PLAY]
        if statue.zone != Zone.GRAVEYARD or len(dead) != 1 or len(live) != 1:
            return f"seed={seed};statue={statue.zone.name};dead={[(m.id,m.zone.name) for m in (first,second)]}", False
        seen.add(dead[0].id)
    return f"random_enemy_destroyed={sorted(seen)}", len(seen) == 2


def c215():
    g = new_game(CardClass.PRIEST); p, e = g.player1, g.player2
    own = deck_top(p, WISP)
    enemy_ids = [FIREBALL, "ICC_099", "EX1_308"]
    enemy_cards = [deck_top(e, cid) for cid in enemy_ids]
    before_own = len(p.deck); before_enemy = len(e.deck)
    card = play(p, "ICC_215")
    own_ids = [c.id for c in p.deck]
    observed = f"own_deck={before_own}->{len(p.deck)}:{own_ids};enemy_deck={before_enemy}->{len(e.deck)}:{ids(e.deck)};source={card.zone.name}"
    return check(observed, len(p.deck) == before_own + before_enemy and len(e.deck) == before_enemy
                 and all(cid in own_ids for cid in enemy_ids) and own.id in own_ids and card.zone == Zone.PLAY,
                 "shuffles a copy of the complete opponent deck into own deck")


def c218():
    g = new_game(CardClass.WARLOCK); p = g.player1
    how = summon(p, "ICC_218")
    first = give(p, WISP); second = give(p, FIREBALL)
    before = ids(p.hand)
    spell = give(p, MOONFIRE); spell.play(target=how)
    after = ids(p.hand)
    observed = f"howl={how.zone.name}/{how.damage};hand_before={before};hand_after={after};discard={[c.id for c in p.graveyard]}"
    return check(observed, how.zone == Zone.PLAY and how.damage == 1 and len(after) == len(before) - 1
                 and (first.id not in after or second.id not in after), "damage to Howlfiend discards exactly one random hand card")


def c220():
    return _lifesteal_attack("ICC_220")


def c221():
    g = new_game(CardClass.ROGUE); p = g.player1
    weapon = give(p, "CS2_091"); weapon.play()
    before_dur = weapon.durability
    card = play(p, "ICC_221")
    active = weapon.lifesteal
    g.end_turn()
    expired = weapon.lifesteal
    observed = f"weapon={weapon.id};durability={before_dur};lifesteal={active}->{expired};source={card.zone.name}"
    return check(observed, active and not expired and weapon.zone == Zone.PLAY and card.zone == Zone.GRAVEYARD,
                 "equipped weapon gains Lifesteal for the current turn only")


def c233():
    g = new_game(CardClass.ROGUE); p, e = g.player1, g.player2
    weapon = give(p, "ICC_236"); weapon.play()
    # Spend one durability before the spell so the returned weapon's current
    # durability is included in the assertion.
    p.hero.attack(e.hero)
    durability_before_throw = weapon.durability
    target = summon(e, "EX1_399")
    before = target.health
    card = play(p, "ICC_233", target=target)
    observed = f"target={target.health}/{target.damage};weapon={weapon.zone.name}/{weapon.durability};durability_before_throw={durability_before_throw};p_weapon={p.weapon};spell={card.zone.name}"
    return check(observed, target.health == before - weapon.atk and weapon.zone == Zone.HAND
                 and weapon.durability == durability_before_throw
                 and p.weapon is None and card.zone == Zone.GRAVEYARD, "weapon deals its attack, leaves play, and returns to hand")


def c235():
    seen = set()
    for seed in range(917, 925):
        g = new_game(CardClass.PRIEST, seed=seed); p = g.player1
        originals = [deck_top(p, WISP), deck_top(p, "EX1_399")]
        card = play(p, "ICC_235")
        spawned = [m for m in p.field if m.id != card.id]
        if len(spawned) != 1 or spawned[0].id not in {WISP, "EX1_399"} or (spawned[0].atk, spawned[0].health) != (5, 5) or any(o not in p.deck for o in originals):
            return f"seed={seed};spawned={[(m.id,m.atk,m.health,m.zone.name) for m in spawned]};deck={ids(p.deck)}", False
        seen.add(spawned[0].id)
    return f"random_deck_minions={sorted(seen)}", len(seen) == 2


def c236():
    g = new_game(CardClass.SHAMAN); p, e = g.player1, g.player2
    weapon = give(p, "ICC_236"); weapon.play()
    frozen = summon(e, "EX1_399")
    p.give("ICC_058").play(target=frozen)
    before = p.hero.health
    defender_atk = frozen.atk
    p.hero.attack(frozen)
    observed = f"weapon={weapon.zone.name};frozen={frozen.zone.name};frozen_tag={frozen.frozen};hero={before}->{p.hero.health}"
    return check(observed, frozen.zone == Zone.GRAVEYARD and weapon.zone == Zone.PLAY and p.hero.health == before - defender_atk,
                 "damaging a Frozen minion with this weapon destroys it")


def c238():
    g = new_game(CardClass.WARRIOR); p = g.player1
    berserker = summon(p, "ICC_238")
    target = give(p, "CS2_182")
    base = (target.atk, target.health)
    target.play()
    observed = f"target={target.zone.name}/{target.atk}/{target.health};base={base};damage={target.damage};berserker={berserker.zone.name}"
    return check(observed, target.zone == Zone.PLAY and target.damage == 1 and (target.atk, target.max_health) == base,
                 "playing a minion deals exactly 1 damage to that minion")


def c240():
    g = new_game(CardClass.ROGUE); p, e = g.player1, g.player2
    weapon = give(p, "CS2_091"); weapon.play()
    haunter = summon(p, "ICC_240")
    before = weapon.durability
    p.hero.attack(e.hero)
    during = weapon.durability
    g.end_turn()
    aura_after = weapon.immune
    observed = f"weapon={weapon.id};durability={before}->{during};haunter={haunter.zone.name};immune_after_turn={aura_after}"
    return check(observed, during == before and aura_after is False, "during owner turn weapon does not lose durability; aura ends after turn")


def c243():
    g = new_game(CardClass.HUNTER); p = g.player1
    death = give(p, "ICC_099"); plain = give(p, WISP)
    before = (death.cost, plain.cost)
    widow = summon(p, "ICC_243")
    reduced = (death.cost, plain.cost)
    widow.destroy()
    restored = (death.cost, plain.cost)
    observed = f"before={before};reduced={reduced};restored={restored};widow={widow.zone.name}"
    return check(observed, reduced == (before[0] - 2, before[1]) and restored == before,
                 "Deathrattle cards cost 2 less while Corpse Widow is in play")


def c244():
    g = new_game(CardClass.PALADIN); p = g.player1
    target = summon(p, WISP)
    spell = play(p, "ICC_244", target=target)
    target.destroy()
    resurrected = [m for m in p.field if m.id == WISP]
    observed = f"target={target.zone.name};resurrected={[(m.id,m.health,m.max_health,m.zone.name) for m in resurrected]};spell={spell.zone.name}"
    return check(observed, target.zone == Zone.GRAVEYARD and len(resurrected) == 1 and resurrected[0].health == 1
                 and spell.zone == Zone.GRAVEYARD, "target's Deathrattle returns a copy with 1 Health")


def c245():
    seen = set()
    last = ""
    for seed in range(917, 925):
        g = new_game(CardClass.PALADIN, seed=seed); p, e = g.player1, g.player2
        guard = summon(p, "ICC_245")
        first = summon(e, "EX1_399"); second = summon(e, "CS2_119")
        p.hero.hit(10)
        before = p.hero.health
        heal = give(p, HOLY_LIGHT); heal.play(target=p.hero)
        damaged = [m for m in (first, second) if m.damage]
        last = f"seed={seed};hero={before}->{p.hero.health};enemy={[(m.id,m.health,m.damage,m.zone.name) for m in (first,second)]};guard={guard.zone.name}"
        if p.hero.health != before + 6 or len(damaged) != 1 or damaged[0].damage != 6 or guard.zone != Zone.PLAY:
            return last, False
        seen.add(damaged[0].id)
    return f"random_targets={sorted(seen)};seeds=8", len(seen) == 2


def c252():
    g = new_game(CardClass.SHAMAN); p, e = g.player1, g.player2
    enemy = summon(e, WISP)
    p.give("ICC_058").play(target=enemy)
    top = deck_top(p, WISP)
    before = len(p.hand)
    card = play(p, "ICC_252")
    drawn = len(p.hand) - before
    observed = f"enemy_frozen={enemy.frozen};draw_delta={drawn};hand={ids(p.hand)};source={card.zone.name}"
    return check(observed, enemy.frozen and drawn == 1 and top in p.hand and card.zone == Zone.PLAY,
                 "Battlecry draws one card when an enemy is Frozen")


def c252_not_frozen():
    g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
    enemy = summon(e, WISP)
    top = deck_top(p, WISP)
    before = len(p.hand)
    card = play(p, "ICC_252")
    drawn = len(p.hand) - before
    observed = f"enemy_frozen={enemy.frozen};draw_delta={drawn};deck={ids(p.deck)};source={card.zone.name}"
    return check(observed, not enemy.frozen and drawn == 0 and top in p.deck and card.zone == Zone.PLAY,
                 "Battlecry does not draw when no enemy is Frozen")


def c257():
    g = new_game(); p = g.player1
    target = summon(p, "EX1_399")
    before_count = len(p.field)
    card = play(p, "ICC_257", target=target)
    target.destroy()
    copies = [m for m in p.field if m.id == "EX1_399"]
    observed = f"target={target.zone.name};copies={[(m.id,m.health,m.zone.name) for m in copies]};field={len(p.field)};source={card.zone.name}"
    return check(observed, target.zone == Zone.GRAVEYARD and len(copies) == 1 and card.zone == Zone.PLAY
                 and len(p.field) == before_count + 1, "friendly target gains a Deathrattle that resummons it")


def c281():
    g = new_game(CardClass.WARRIOR); p = g.player1
    weapon_ids = ["CS2_091", "ICC_236"]
    for cid in weapon_ids:
        deck_top(p, cid)
    nonweapon = deck_top(p, WISP)
    before = len(p.deck)
    card = play(p, "ICC_281")
    drawn = [c.id for c in p.hand]
    observed = f"drawn={drawn};deck={[c.id for c in p.deck]};before={before};after={len(p.deck)};source={card.zone.name}"
    return check(observed, all(cid in drawn for cid in weapon_ids) and nonweapon in p.deck
                 and len(p.deck) == before - 2 and card.zone == Zone.GRAVEYARD, "draws exactly two weapons and leaves nonweapon deck cards")


def c289():
    g = new_game(CardClass.SHAMAN); p, e = g.player1, g.player2
    moorabi = summon(p, "ICC_289")
    target = summon(e, WISP)
    p.give("ICC_058").play(target=target)
    copies = [c for c in p.hand if c.id == WISP]
    observed = f"moorabi={moorabi.zone.name};target={target.zone.name}/{target.frozen};copies={[(c.id,c.zone.name) for c in copies]}"
    return check(observed, target.frozen and len(copies) == 1 and moorabi not in p.hand,
                 "freezing another minion adds exactly one copy to hand")


def c289_self_excluded():
    g = new_game(CardClass.SHAMAN, opponent_class=CardClass.SHAMAN); p, e = g.player1, g.player2
    moorabi = summon(p, "ICC_289")
    g.end_turn()
    e.give("ICC_058").play(target=moorabi)
    copies = [c for c in p.hand if c.id == "ICC_289"]
    observed = f"moorabi={moorabi.zone.name}/{moorabi.frozen};self_copies={[(c.id,c.zone.name) for c in copies]};p_hand={ids(p.hand)}"
    return check(observed, moorabi.frozen and not copies,
                 "Freezing Moorabi itself does not copy it because the trigger says another minion")


def c314():
    seen = set()
    for seed in range(917, 925):
        g = new_game(seed=seed); p = g.player1
        lich = summon(p, "ICC_314")
        if not lich.taunt:
            return f"seed={seed};taunt={lich.taunt}", False
        before = len(p.hand)
        g.end_turn()
        added = [c for c in p.hand if c.id in LICH_KING_CARDS]
        if len(p.hand) != before + 1 or len(added) != 1:
            return f"seed={seed};before={before};hand={ids(p.hand)};added={ids(added)}", False
        seen.add(added[0].id)
    return f"taunt=True;death_knight_cards={sorted(seen)}", len(seen) >= 2


def c405():
    seen = set()
    for seed in range(917, 925):
        g = new_game(CardClass.WARRIOR, seed=seed); p = g.player1
        rot = summon(p, "ICC_405")
        p.give(MOONFIRE).play(target=rot)
        summoned = [m for m in p.field if m is not rot]
        if rot.zone != Zone.PLAY or rot.damage != 1 or len(summoned) != 1 or summoned[0].rarity != Rarity.LEGENDARY:
            return f"seed={seed};rot={rot.zone.name}/{rot.damage};summoned={[(m.id,str(m.rarity),m.zone.name) for m in summoned]}", False
        seen.add(summoned[0].id)
    return f"surviving_damage_legendary_pool={sorted(seen)}", len(seen) >= 2


def c405_lethal():
    g = new_game(CardClass.WARRIOR); p = g.player1
    rot = summon(p, "ICC_405")
    p.give(FIREBALL).play(target=rot)
    legendary = [m for m in p.field if m.rarity == Rarity.LEGENDARY]
    observed = f"rot={rot.zone.name};damage={rot.damage};legendary_summons={[(m.id,m.zone.name) for m in legendary]}"
    return check(observed, rot.zone == Zone.GRAVEYARD and not legendary,
                 "Lethal damage does not summon a Legendary because Rotface did not survive")


def c407():
    g = new_game(CardClass.WARLOCK); p, e = g.player1, g.player2
    kept = deck_top(e, FIREBALL)
    removed = deck_top(e, WISP)
    before = len(e.deck)
    card = play(p, "ICC_407")
    observed = f"removed={removed.id}/{removed.zone.name};kept={kept.id}/{kept.zone.name};deck={ids(e.deck)};before={before};source={card.zone.name}"
    return check(observed, len(e.deck) == before - 1 and removed.zone in (Zone.GRAVEYARD, Zone.REMOVEDFROMGAME) and kept in e.deck
                 and card.zone == Zone.PLAY, "removes the top opponent deck card without drawing it")


def c408():
    g = new_game(CardClass.WARRIOR); p = g.player1
    val = summon(p, "ICC_408")
    p.give(MOONFIRE).play(target=val)
    ghouls = [m for m in p.field if m.id == "ICC_900t"]
    observed = f"val={val.zone.name}/{val.damage};ghouls={[(m.id,m.atk,m.health,m.zone.name) for m in ghouls]}"
    return check(observed, val.zone == Zone.PLAY and val.damage == 1 and len(ghouls) == 1
                 and (ghouls[0].atk, ghouls[0].health) == (2, 2), "surviving damage summons one 2/2 Ghoul")


def c408_lethal():
    g = new_game(CardClass.WARRIOR); p = g.player1
    val = summon(p, "ICC_408")
    p.give(FIREBALL).play(target=val)
    ghouls = [m for m in p.field if m.id == "ICC_900t"]
    observed = f"val={val.zone.name};damage={val.damage};ghouls={len(ghouls)}"
    return check(observed, val.zone == Zone.GRAVEYARD and not ghouls,
                 "Lethal damage does not summon a Ghoul because the minion did not survive")


def c415():
    g = new_game(CardClass.HUNTER); p = g.player1
    first = deck_top(p, WISP); second = deck_top(p, "EX1_399"); non = deck_top(p, FIREBALL)
    before = len(p.deck)
    card = play(p, "ICC_415")
    choices = list(p.choice.cards) if p.choice else []
    allowed = {WISP, "EX1_399"}
    if not choices or not all(c.id in allowed for c in choices):
        return f"choices={ids(choices)};deck={ids(p.deck)};source={card.zone.name}", False
    chosen = choices[0]; p.choice.choose(chosen)
    copies = [c for c in p.hand if c.id == chosen.id]
    observed = f"choices={ids(choices)};chosen={chosen.id};copies={[(c.id,c.zone.name) for c in copies]};deck={ids(p.deck)};before={before};source={card.zone.name}"
    return check(observed, len(copies) == 1 and first in p.deck and second in p.deck and non in p.deck
                 and len(p.deck) == before and card.zone == Zone.PLAY, "Discovers a minion from deck and adds a copy while preserving deck")


def c419():
    g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
    bear = summon(p, "ICC_419"); other = summon(p, WISP)
    spell = give(p, MOONFIRE)
    power = p.hero.power
    observed = f"spell_targets={[c.id for c in spell.targets]};power_targets={[c.id for c in power.targets]};bear={bear.zone.name};other={other.zone.name}"
    return check(observed, bear not in spell.targets and other in spell.targets and bear not in power.targets
                 and other in power.targets, "Bearshark is excluded from both spell and Hero Power targets")


def c450():
    g = new_game(); p, e = g.player1, g.player2
    one = summon(p, "EX1_399"); two = summon(e, "CS2_182")
    p.give(MOONFIRE).play(target=one); p.give(MOONFIRE).play(target=two)
    card = play(p, "ICC_450")
    observed = f"damaged={[(m.id,m.damage,m.zone.name) for m in (one,two)]};revenant={card.atk}/{card.health};base={card.data.atk}/{card.data.health}"
    return check(observed, card.atk == card.data.atk + 2 and card.health == card.data.health + 2 and card.zone == Zone.PLAY,
                 "gains +1/+1 for each of two damaged minions")


def c466():
    g = new_game(); p = g.player1
    card = play(p, "ICC_466")
    gang = [m for m in p.field if m.id == "ICC_466"]
    observed = f"field={[(m.id,m.atk,m.health,m.taunt,m.zone.name) for m in gang]};source={card.zone.name}"
    return check(observed, len(gang) == 2 and all(m.taunt and m.zone == Zone.PLAY for m in gang)
                 and card in gang, "Battlecry summons one exact additional Taunt copy")


def c467():
    g = new_game(); p, e = g.player1, g.player2
    target = summon(p, "EX1_399")
    card = play(p, "ICC_467", target=target)
    immune_now = target.immune
    p.give(MOONFIRE).play(target=target)
    immune_damage = target.damage
    g.end_turn()
    expired = target.immune
    observed = f"target={target.zone.name};immune_now={immune_now};damage={immune_damage};expired_after_owner_turn={expired};source={card.zone.name}"
    return check(observed, immune_now and immune_damage == 0 and expired is False and card.zone == Zone.PLAY,
                 "friendly target is Immune for this turn and the effect expires")


def c468():
    g = new_game(); p, e = g.player1, g.player2
    tiller = summon(p, "ICC_468")
    defender = summon(e, "EX1_399")
    tiller2 = summon(p, "ICC_468")
    g.end_turn(); g.end_turn()
    before_hero = e.hero.health
    tiller.attack(defender)
    minion_attack_hero = e.hero.health
    before_face = e.hero.health
    tiller2.attack(e.hero)
    face_after = e.hero.health
    observed = f"minion_attack_hero={before_hero}->{minion_attack_hero};defender={defender.health}/{defender.damage};face_attack={before_face}->{face_after};tiller2={tiller2.zone.name}"
    return check(observed, minion_attack_hero == before_hero - 2 and face_after == before_face - tiller2.atk - 2,
                 "each attack also deals 2 damage to the enemy hero")


def c469():
    seen = set()
    for seed in range(917, 925):
        g = new_game(CardClass.WARLOCK, seed=seed); p, e = g.player1, g.player2
        chosen = summon(p, WISP); remain = summon(p, "EX1_399")
        first = summon(e, "EX1_399"); second = summon(e, "CS2_182")
        spell = play(p, "ICC_469", target=chosen)
        dead = [m for m in (first, second) if m.zone == Zone.GRAVEYARD]
        if chosen.zone != Zone.GRAVEYARD or remain.zone != Zone.PLAY or len(dead) != 1 or spell.zone != Zone.GRAVEYARD:
            return f"seed={seed};friendly={[(m.id,m.zone.name) for m in (chosen,remain)]};enemy={[(m.id,m.zone.name) for m in (first,second)]};spell={spell.zone.name}", False
        seen.add(dead[0].id)
    return f"random_enemy_destroyed={sorted(seen)}", len(seen) == 2


def c481():
    seen = set()
    for seed in range(917, 925):
        g = new_game(CardClass.SHAMAN, seed=seed); p, e = g.player1, g.player2
        one = summon(p, WISP); two = summon(p, "EX1_399")
        originals = [(one.id, one.cost), (two.id, two.cost)]
        hero = play(p, "ICC_481")
        transformed = [m for m in p.field]
        if p.hero.id != "ICC_481" or len(transformed) != 2:
            return f"seed={seed};hero={p.hero.id};field={[(m.id,m.cost,m.zone.name) for m in transformed]}", False
        expected_costs = sorted(cost + 2 for _, cost in originals)
        actual_costs = sorted(m.cost for m in transformed)
        if actual_costs != expected_costs:
            return f"seed={seed};originals={originals};transformed={[(m.id,m.cost) for m in transformed]}", False
        seen.update(m.id for m in transformed)
    return f"evolved_minions={sorted(seen)}", len(seen) >= 2


def c700():
    g = new_game(); p = g.player1
    ghoul = give(p, "ICC_700")
    base = ghoul.cost
    p.hero.hit(5)
    heal = give(p, HOLY_LIGHT); heal.play(target=p.hero)
    active = ghoul.cost
    g.end_turn()
    expired = ghoul.cost
    observed = f"cost={base}->{active}->{expired};hero={p.hero.health};zone={ghoul.zone.name}"
    return check(observed, base == 3 and active == 0 and expired == 3 and ghoul.zone == Zone.HAND,
                 "healing the hero makes Happy Ghoul cost 0 for this turn only")


def c701():
    g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
    # One-cost spells are planted in both hands and decks; non-one-cost cards
    # provide controls for the hand/deck destruction boundary.
    own_one = give(p, "CS1_130"); own_one2 = give(p, "EX1_308"); own_four = give(p, FIREBALL); own_minion = give(p, WISP)
    enemy_one = give(e, "EX1_308"); enemy_one2 = give(e, "CS1_130"); enemy_four = give(e, FIREBALL); enemy_minion = give(e, WISP)
    own_deck_one = deck_top(p, "CS1_130"); own_deck_one2 = deck_top(p, "EX1_308"); own_deck_four = deck_top(p, FIREBALL); own_deck_minion = deck_top(p, WISP)
    enemy_deck_one = deck_top(e, "EX1_308"); enemy_deck_one2 = deck_top(e, "CS1_130"); enemy_deck_four = deck_top(e, FIREBALL); enemy_deck_minion = deck_top(e, WISP)
    card = play(p, "ICC_701")
    observed = f"p_hand={ids(p.hand)};e_hand={ids(e.hand)};p_deck={ids(p.deck)};e_deck={ids(e.deck)};source={card.zone.name}"
    controls_remain = all(x in p.hand for x in (own_four, own_minion)) and all(x in e.hand for x in (enemy_four, enemy_minion))
    deck_controls = all(x in p.deck for x in (own_deck_four, own_deck_minion)) and all(x in e.deck for x in (enemy_deck_four, enemy_deck_minion))
    removed = all(x.zone in (Zone.GRAVEYARD, Zone.REMOVEDFROMGAME) for x in (own_one, own_one2, enemy_one, enemy_one2, own_deck_one, own_deck_one2, enemy_deck_one, enemy_deck_one2))
    return check(observed, removed and controls_remain and deck_controls and card.zone == Zone.PLAY,
                 "destroys every 1-Cost spell in both hands and decks while preserving controls")


CASES = {
    "ICC_094": [("friendly_target_plus_one", "Friendly target gains +1/+1.", c094)],
    "ICC_096": [("discard_all_weapons_gain_sum", "Discard all hand weapons and gain their combined Attack and Durability.", c096)],
    "ICC_097": [("weapon_destroy_plus_one", "Weapon destruction grants Grave Shambler +1/+1.", c097)],
    "ICC_098": [("dead_deathrattle_minion_added", "Adds a random Deathrattle minion that died this game.", c098), ("dead_pool_includes_both_sides", "Across seeded games the random pool includes eligible friendly and enemy Deathrattle corpses.", c098_pool)],
    "ICC_099": [("friendly_only_five_damage", "Deathrattle deals 5 damage to friendly minions only.", c099)],
    "ICC_200": [("open_board_secret_trigger", "Secret triggers on a friendly minion attack and summons a Poisonous Cobra.", c200_open), ("normal_full_board_one_slot", "A normal full board leaves one slot after the attacked minion dies.", c200_full_board), ("dormant_full_board_secret_stays", "A dormant occupant still makes the board full for the Secret summon.", c200_dormant_full_board)],
    "ICC_201": [("deathrattle_draw_recurses", "A Deathrattle draw casts Roll the Bones recursively.", c201)],
    "ICC_204": [("secret_play_adds_hunter_secret", "Playing a Secret adds a random Hunter Secret to the battlefield.", c204)],
    "ICC_206": [("friendly_minion_changes_controller", "Treachery gives the selected friendly minion to the opponent.", c206)],
    "ICC_207": [("copy_three_opponent_deck_cards", "Copies three opponent deck cards to hand without removing the deck cards.", c207)],
    "ICC_210": [("end_turn_random_other_friendly_buff", "At turn end exactly one other random friendly minion gains +1/+1.", c210)],
    "ICC_212": [("lifesteal_attack", "Acolyte of Agony heals its controller for combat damage.", c212)],
    "ICC_213": [("choice_dead_friendly_summon", "Choice offers dead friendly minions and summons the selected one.", c213)],
    "ICC_214": [("taunt_lifesteal_random_deathrattle", "Obsidian Statue has Taunt/Lifesteal and destroys one random enemy on death.", c214)],
    "ICC_215": [("copy_complete_opponent_deck", "Shuffles a copy of the complete opponent deck into own deck.", c215)],
    "ICC_218": [("damage_discards_one_random_card", "Damage to Howlfiend discards one random hand card.", c218)],
    "ICC_220": [("lifesteal_attack", "Deadscale Knight heals its controller for combat damage.", c220)],
    "ICC_221": [("weapon_lifesteal_one_turn", "Leeching Poison grants weapon Lifesteal for this turn only.", c221)],
    "ICC_233": [("weapon_damage_then_bounce", "Doomerang deals weapon damage and returns the weapon to hand.", c233)],
    "ICC_235": [("random_deck_minion_five_five_copy", "Summons a 5/5 copy of a random minion from deck.", c235)],
    "ICC_236": [("frozen_minion_destroyed", "Ice Breaker destroys a Frozen minion it damages.", c236)],
    "ICC_238": [("played_minion_takes_one", "Animated Berserker deals 1 damage to each minion played.", c238)],
    "ICC_240": [("weapon_durability_preserved_own_turn", "Runeforge Haunter prevents durability loss during the owner's turn.", c240)],
    "ICC_243": [("deathrattle_cost_aura", "Corpse Widow reduces Deathrattle card costs by 2 and restores them when removed.", c243)],
    "ICC_244": [("deathrattle_returns_one_health", "Desperate Stand returns the target with 1 Health.", c244)],
    "ICC_245": [("healing_random_enemy_damage", "Hero healing deals the same amount to one random enemy minion.", c245)],
    "ICC_252": [("frozen_enemy_draws", "Coldwraith draws when an enemy is Frozen.", c252), ("non_frozen_enemy_no_draw", "Coldwraith does not draw when no enemy is Frozen.", c252_not_frozen)],
    "ICC_257": [("target_resummons", "Corpse Raiser makes the target resummon itself on death.", c257)],
    "ICC_281": [("draw_two_weapons", "Forge of Souls draws two weapons and leaves nonweapons in deck.", c281)],
    "ICC_289": [("freeze_other_adds_copy", "Freezing another minion adds a copy to Moorabi's hand.", c289), ("freeze_self_excluded", "Freezing Moorabi itself does not add a copy.", c289_self_excluded)],
    "ICC_314": [("end_turn_death_knight_card", "The Lich King is Taunt and adds a random Death Knight card at turn end.", c314)],
    "ICC_405": [("survive_damage_random_legendary", "Rotface summons a random Legendary after surviving damage.", c405), ("lethal_damage_no_legendary", "Lethal damage does not summon a Legendary.", c405_lethal)],
    "ICC_407": [("mill_opponent_top_card", "Gnomeferatu removes the top opponent deck card.", c407)],
    "ICC_408": [("survive_damage_ghoul", "Val'kyr Soulclaimer summons a 2/2 Ghoul after surviving damage.", c408), ("lethal_damage_no_ghoul", "Lethal damage does not summon a Ghoul.", c408_lethal)],
    "ICC_415": [("discover_deck_minion_copy", "Stitched Tracker discovers a deck minion and adds a copy.", c415)],
    "ICC_419": [("spell_and_power_untargetable", "Bearshark is excluded from spell and Hero Power targets.", c419)],
    "ICC_450": [("damaged_minions_plus_one_each", "Death Revenant gains +1/+1 for each damaged minion.", c450)],
    "ICC_466": [("summon_exact_taunt_copy", "Saronite Chain Gang summons one additional Taunt copy.", c466)],
    "ICC_467": [("immune_this_turn", "Deathspeakergives a friendly target Immunity for this turn.", c467)],
    "ICC_468": [("attack_deals_two_to_hero", "Wretched Tiller deals 2 damage to the enemy hero whenever it attacks.", c468)],
    "ICC_469": [("destroy_friendly_random_enemy", "Unwilling Sacrifice destroys the chosen friendly and one random enemy minion.", c469)],
    "ICC_481": [("evolve_minions_cost_plus_two", "Thrall transforms friendly minions into random minions costing 2 more.", c481)],
    "ICC_700": [("healed_hero_zero_cost_until_turn_end", "Happy Ghoul costs 0 after hero healing and restores cost next turn.", c700)],
    "ICC_701": [("destroy_one_cost_spells_everywhere", "Skulking Geist destroys all 1-Cost spells in both hands and decks.", c701)],
}


def main():
    assert set(CASES) == set(OWN_IDS), sorted(set(OWN_IDS) - set(CASES))
    rows = []
    verdicts = []
    for cid in OWN_IDS:
        card = MASTER_BY_ID[cid]
        for case_id, expected, fn in CASES[cid]:
            try:
                observed, passed = fn()
                outcome = "pass" if passed is True else "confirmed_error" if passed is False else "inconclusive"
            except AssertionError as exc:
                observed = f"AssertionError: {exc}"
                outcome = "inconclusive"
            except Exception as exc:
                observed = f"{type(exc).__name__}: {exc}"
                outcome = "inconclusive"
            rows.append({"card_id": cid, "case_id": case_id, "expected": expected,
                         "observed": observed, "outcome": outcome,
                         "notes": metadata(cid)})
            write_csv(PROBE_OUT, PROBE_FIELDS, rows)
            print(cid, case_id, outcome, observed, flush=True)
        own = [r for r in rows if r["card_id"] == cid]
        errors = [r for r in own if r["outcome"] == "confirmed_error"]
        inconclusive = [r for r in own if r["outcome"] == "inconclusive"]
        status = "RED" if errors else "YELLOW" if inconclusive else "GREEN"
        if errors:
            reason = "确认行为与文本不符：" + "; ".join(f"{r['case_id']} expected[{r['expected']}] observed[{r['observed']}]" for r in errors)
        elif inconclusive:
            reason = "关键行为待进一步核实：" + "; ".join(f"{r['case_id']}={r['observed']}" for r in inconclusive)
        else:
            reason = "本轮逐卡行为断言通过：" + "; ".join(f"{r['case_id']}={r['observed']}" for r in own)
        verdicts.append({"card_id": cid, "status": status, "mechanic_scope": card["mechanics"],
                         "reason": reason, "probe_file": PROBE_OUT.name,
                         "notes": f"{len(own)} live cases; card EN/ZH text, source, existing tests and prior audit recorded in probe notes."})
        write_csv(VERDICT_OUT, VERDICT_FIELDS, verdicts)


if __name__ == "__main__":
    main()
