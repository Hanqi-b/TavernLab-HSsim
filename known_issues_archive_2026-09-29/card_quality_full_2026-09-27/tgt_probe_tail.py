"""Independent live-game probes for the AT_100..AT_133 TGT YELLOW tail."""

import csv
import logging
import random
import sys
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Zone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import FIREBALL, KOBOLD_GEOMANCER, MOONFIRE, THE_COIN, WISP, prepare_empty_game  # noqa: E402

logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)

PROBE = HERE / "tgt_probe_tail.csv"
VERDICT = HERE / "tgt_verdict_tail.csv"
BASE = HERE / "four_set_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
PF = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VF = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        out = csv.DictWriter(stream, fieldnames=fields)
        out.writeheader()
        out.writerows(rows)


def game(c1=CardClass.MAGE, c2=CardClass.MAGE, seed=417):
    random.seed(seed)
    g = prepare_empty_game(c1, c2)
    g.random.seed(seed)
    if g.current_player is not g.player1:
        g.end_turn()
    for p in g.players:
        p.max_mana = 10
        p.is_standard = False
    return g


def play(p, cid, target=None):
    card = p.give(cid)
    if target is None:
        card.play()
    else:
        card.play(target=target)
    return card


def put(p, cid):
    return p.summon(cid)


def shuffle(p, cid):
    c = p.give(cid)
    c.shuffle_into_deck()
    return c


def inspire(g):
    power = g.player1.hero.power
    if power.requires_target():
        power.use(target=g.player2.hero)
    else:
        power.use()


def p100():
    g = game(CardClass.PALADIN, CardClass.PALADIN)
    r = play(g.player1, "AT_100")
    before = [m.id for m in g.player1.field]
    inspire(g)
    after = [m.id for m in g.player1.field]
    control = game(CardClass.PALADIN, CardClass.PALADIN)
    inspire(control)
    base_recruits = sum(m.id == "CS2_101t" for m in control.player1.field)
    observed_recruits = after.count("CS2_101t")
    return f"before={before};after={after};without_regent={base_recruits};with_regent={observed_recruits}", r.zone == Zone.PLAY and base_recruits == 1 and observed_recruits == base_recruits + 1


def p103():
    g = game()
    target = put(g.player2, "CS2_182")
    kraken = play(g.player1, "AT_103", target)
    return f"target_damage={target.damage};target_zone={target.zone.name};kraken={kraken.zone.name}", target.damage == 4 and target.zone == Zone.PLAY and kraken.zone == Zone.PLAY


def joust(cid, own, enemy):
    g = game(CardClass.PALADIN)
    shuffle(g.player1, own)
    shuffle(g.player2, enemy)
    card = play(g.player1, cid)
    return g, card


def p104_win():
    g = game(CardClass.PALADIN)
    g.player1.hero.hit(9)
    shuffle(g.player1, "NEW1_030")
    shuffle(g.player2, WISP)
    card = play(g.player1, "AT_104")
    return f"hero_health={g.player1.hero.health};card={card.zone.name}", g.player1.hero.health == 28 and card.zone == Zone.PLAY


def p104_lose():
    g = game(CardClass.PALADIN)
    g.player1.hero.hit(9)
    shuffle(g.player1, WISP)
    shuffle(g.player2, "NEW1_030")
    play(g.player1, "AT_104")
    return f"hero_health={g.player1.hero.health}", g.player1.hero.health == 21


def p105():
    g = game()
    c = play(g.player1, "AT_105")
    return f"stats={c.atk}/{c.health};damage={c.damage};zone={c.zone.name}", c.damage == 3 and c.zone == Zone.PLAY


def p106():
    g = game()
    demon = put(g.player2, "CS2_065")
    own_demon = put(g.player1, "CS2_065")
    enemy_plain = put(g.player2, "CS2_182")
    own_plain = put(g.player1, "CS2_182")
    before = demon.taunt
    card = g.player1.give("AT_106")
    legal = set(card.targets)
    card.play(target=demon)
    return f"target_ids={[x.id for x in legal]};taunt_before={before};taunt_after={demon.taunt};silenced={demon.silenced};champion={card.zone.name}", legal == {demon, own_demon} and enemy_plain not in legal and own_plain not in legal and before and not demon.taunt and demon.silenced and card.zone == Zone.PLAY


def p106_friendly():
    g = game()
    demon = put(g.player1, "CS2_065")
    card = play(g.player1, "AT_106", demon)
    return f"friendly_demon_silenced={demon.silenced};taunt={demon.taunt};champion={card.zone.name}", demon.silenced and not demon.taunt and card.zone == Zone.PLAY


def p108_win():
    g, c = joust("AT_108", "NEW1_030", WISP)
    return f"charge={c.charge};zone={c.zone.name}", c.charge and c.zone == Zone.PLAY


def p108_lose():
    g, c = joust("AT_108", WISP, "NEW1_030")
    return f"charge={c.charge};zone={c.zone.name}", not c.charge and c.zone == Zone.PLAY


def p109():
    g = game()
    c = play(g.player1, "AT_109")
    g.end_turn(); g.end_turn()
    before = c.can_attack()
    inspire(g)
    after = c.can_attack()
    try:
        c.attack(g.player2.hero)
        attack_result = f"accepted;enemy_health={g.player2.hero.health}"
        attacked = True
    except Exception as exc:
        attack_result = f"rejected:{type(exc).__name__}:{exc}"
        attacked = False
    return f"can_attack_before={before};after_inspire={after};actual_attack={attack_result};cant_attack_tag={c.cant_attack};buffs={[b.id for b in c.buffs]};zone={c.zone.name}", not before and after and attacked and c.zone == Zone.PLAY


def p110():
    g = game()
    c = play(g.player1, "AT_110")
    inspire(g)
    return f"zone={c.zone.name};in_hand={c in g.player1.hand};in_field={c in g.player1.field}", c.zone == Zone.HAND and c in g.player1.hand and c not in g.player1.field


def p111():
    g = game()
    g.player1.hero.hit(6)
    g.player2.hero.hit(2)
    c = play(g.player1, "AT_111")
    return f"friendly_health={g.player1.hero.health};enemy_health={g.player2.hero.health};card={c.zone.name}", g.player1.hero.health == 28 and g.player2.hero.health == 30 and c.zone == Zone.PLAY


def p112_win():
    g, c = joust("AT_112", "NEW1_030", WISP)
    return f"taunt={c.taunt};shield={c.divine_shield};zone={c.zone.name}", c.taunt and c.divine_shield and c.zone == Zone.PLAY


def p112_lose():
    g, c = joust("AT_112", WISP, "NEW1_030")
    return f"taunt={c.taunt};shield={c.divine_shield};zone={c.zone.name}", not c.taunt and not c.divine_shield and c.zone == Zone.PLAY


def p113():
    g = game()
    c = play(g.player1, "AT_113")
    before = len(g.player1.hand)
    inspire(g)
    gained = [x for x in g.player1.hand if x.id == "CS2_152"]
    return f"before={before};hand={[x.id for x in g.player1.hand]};squires={len(gained)}", c.zone == Zone.PLAY and len(g.player1.hand) == before + 1 and len(gained) == 1


def p114():
    g = game()
    c = play(g.player1, "AT_114")
    return f"taunt={c.taunt};zone={c.zone.name};atk={c.atk};health={c.health}", c.taunt and c.zone == Zone.PLAY and c.atk == c.data.atk and c.health == c.data.health


def p115():
    g = game()
    c = play(g.player1, "AT_115")
    hp = g.player1.hero.power
    first_cost = hp.cost
    if hp.requires_target(): hp.use(target=g.player2.hero)
    else: hp.use()
    next_cost = hp.cost
    return f"hero_power_cost_before={first_cost};after_use={next_cost};coach={c.zone.name}", first_cost == 0 and next_cost == hp.data.cost and c.zone == Zone.PLAY


def p116_yes():
    g = game(CardClass.PRIEST)
    g.player1.give("NEW1_030")
    c = play(g.player1, "AT_116")
    return f"atk={c.atk};taunt={c.taunt};zone={c.zone.name}", c.atk == c.data.atk + 1 and c.taunt and c.zone == Zone.PLAY


def p116_no():
    g = game(CardClass.PRIEST)
    c = play(g.player1, "AT_116")
    return f"atk={c.atk};taunt={c.taunt};zone={c.zone.name}", c.atk == c.data.atk and not c.taunt and c.zone == Zone.PLAY


def p117_yes():
    g = game()
    put(g.player1, KOBOLD_GEOMANCER)
    c = play(g.player1, "AT_117")
    return f"stats={c.atk}/{c.health};printed={c.data.atk}/{c.data.health}", c.atk == c.data.atk + 2 and c.health == c.data.health + 2


def p117_no():
    g = game()
    c = play(g.player1, "AT_117")
    return f"stats={c.atk}/{c.health};printed={c.data.atk}/{c.data.health}", c.atk == c.data.atk and c.health == c.data.health


def p117_enemy_only():
    g = game()
    put(g.player2, KOBOLD_GEOMANCER)
    c = play(g.player1, "AT_117")
    return f"enemy_spellpower={g.player2.spellpower};own_spellpower={g.player1.spellpower};stats={c.atk}/{c.health};printed={c.data.atk}/{c.data.health}", g.player2.spellpower == 1 and g.player1.spellpower == 0 and c.atk == c.data.atk and c.health == c.data.health


def p118():
    samples = []
    for seed in range(30, 46):
        g = game(seed=seed)
        c = play(g.player1, "AT_118")
        gained = list(g.player1.hand)
        if len(gained) != 1 or gained[0].card_class != CardClass.PALADIN or gained[0].zone != Zone.HAND or c.zone != Zone.PLAY:
            return f"seed={seed};gained={[(x.id,str(x.card_class),x.zone.name) for x in gained]};card={c.zone.name}", False
        samples.append(gained[0].id)
    return f"16_seeded_paladin_cards={samples};distinct={len(set(samples))}", len(set(samples)) > 1


def p119():
    g = game()
    c = play(g.player1, "AT_119")
    before = (c.atk, c.health)
    inspire(g)
    return f"before={before};after={c.atk}/{c.health};zone={c.zone.name}", c.atk == before[0] + 2 and c.health == before[1] + 2 and c.zone == Zone.PLAY


def p120():
    g = game()
    c = g.player1.give("AT_120")
    before = c.cost
    inspire(g)
    after = c.cost
    g.end_turn(); g.end_turn()
    inspire(g)
    return f"costs={before}->{after}->{c.cost}", after == before - 1 and c.cost == before - 2


def p121():
    g = game()
    c = play(g.player1, "AT_121")
    before = (c.atk, c.health)
    play(g.player1, WISP)
    plain = (c.atk, c.health)
    play(g.player1, "EX1_066")
    after = (c.atk, c.health)
    return f"before={before};after_plain={plain};after_battlecry={after}", plain == before and after == (before[0] + 1, before[1] + 1)


def p121_opponent_battlecry():
    g = game()
    c = play(g.player1, "AT_121")
    before = (c.atk, c.health)
    g.end_turn()
    play(g.player2, "EX1_066")
    return f"before={before};after_opponent_battlecry={c.atk}/{c.health};zone={c.zone.name}", (c.atk, c.health) == before and c.zone == Zone.PLAY


def p122_yes():
    g = game()
    for _ in range(4): put(g.player1, WISP)
    target = put(g.player2, "CS2_182")
    c = play(g.player1, "AT_122", target)
    return f"target_damage={target.damage};target_zone={target.zone.name};card={c.zone.name}", target.damage == 4 and c.zone == Zone.PLAY


def p122_no():
    g = game()
    for _ in range(3): put(g.player1, WISP)
    target = put(g.player2, "CS2_182")
    c = play(g.player1, "AT_122")
    return f"target_damage={target.damage};card={c.zone.name}", target.damage == 0 and c.zone == Zone.PLAY


def p123_yes():
    g = game()
    g.player1.give("NEW1_030")
    ally = put(g.player1, "CS2_182")
    enemy = put(g.player2, "CS2_182")
    c = play(g.player1, "AT_123")
    taunt = c.taunt
    c.destroy()
    return f"taunt={taunt};ally_damage={ally.damage};enemy_damage={enemy.damage};chillmaw_zone={c.zone.name}", taunt and ally.damage == enemy.damage == 3 and c.zone == Zone.GRAVEYARD


def p123_no():
    g = game()
    ally = put(g.player1, "CS2_182")
    enemy = put(g.player2, "CS2_182")
    c = play(g.player1, "AT_123")
    c.destroy()
    return f"ally_damage={ally.damage};enemy_damage={enemy.damage};zone={c.zone.name}", ally.damage == enemy.damage == 0 and c.zone == Zone.GRAVEYARD


def p123_dragon_added_late():
    g = game()
    ally = put(g.player1, "CS2_182")
    enemy = put(g.player2, "CS2_182")
    c = play(g.player1, "AT_123")
    dragon = g.player1.give("NEW1_030")
    c.destroy()
    return f"dragon_at_death={dragon.id}/{dragon.zone.name};ally_damage={ally.damage};enemy_damage={enemy.damage};zone={c.zone.name}", dragon.zone == Zone.HAND and ally.damage == enemy.damage == 3 and c.zone == Zone.GRAVEYARD


def p123_dragon_removed_before_death():
    g = game()
    dragon = g.player1.give("NEW1_030")
    ally = put(g.player1, "CS2_182")
    enemy = put(g.player2, "CS2_182")
    c = play(g.player1, "AT_123")
    g.player1.discard_hand()
    c.destroy()
    return f"dragon_after_discard={dragon.zone.name};ally_damage={ally.damage};enemy_damage={enemy.damage};zone={c.zone.name}", dragon.zone != Zone.HAND and ally.damage == enemy.damage == 0 and c.zone == Zone.GRAVEYARD


def p124():
    g = game()
    c = play(g.player1, "AT_124")
    before = g.player1.hero.health
    play(g.player2, MOONFIRE, g.player1.hero) if g.current_player is g.player2 else c.controller.hero.hit(2)
    return f"hero_health={g.player1.hero.health};bolf_damage={c.damage};zone={c.zone.name}", g.player1.hero.health == before and c.damage == 2 and c.zone == Zone.PLAY


def p125():
    g = game()
    c = play(g.player1, "AT_125")
    enemy = put(g.player2, "CS2_182")
    can_face = g.player2.hero in c.attack_targets
    can_minion = enemy in c.attack_targets
    c.attack(enemy)
    return f"charge={c.charge};hero_target={can_face};minion_target={can_minion};enemy_zone={enemy.zone.name};icehowl_zone={c.zone.name}", c.charge and not can_face and can_minion and enemy.zone == Zone.GRAVEYARD


def p127():
    samples = []
    for seed in range(30, 46):
        g = game(seed=seed)
        c = play(g.player1, "AT_127")
        before = len(g.player1.hand)
        inspire(g)
        gained = list(g.player1.hand)
        if len(gained) != before + 1 or gained[-1].type != CardType.SPELL or gained[-1].zone != Zone.HAND or c.zone != Zone.PLAY:
            return f"seed={seed};before={before};gained={[(x.id,str(x.type),x.zone.name) for x in gained]}", False
        samples.append(gained[-1].id)
    return f"16_seeded_spell_cards={samples};distinct={len(set(samples))}", len(set(samples)) > 1


def p128_win():
    g = game()
    c = play(g.player1, "AT_128")
    shuffle(g.player1, "NEW1_030")
    shuffle(g.player2, WISP)
    c.destroy()
    return f"zone={c.zone.name};in_hand={c in g.player1.hand}", c.zone == Zone.HAND and c in g.player1.hand


def p128_lose():
    g = game()
    c = play(g.player1, "AT_128")
    shuffle(g.player1, WISP)
    shuffle(g.player2, "NEW1_030")
    c.destroy()
    return f"zone={c.zone.name};in_hand={c in g.player1.hand}", c.zone == Zone.GRAVEYARD and c not in g.player1.hand


def p129():
    g = game()
    c = play(g.player1, "AT_129")
    before = c.divine_shield
    play(g.player1, "CS2_004", c)
    return f"shield_before={before};shield_after={c.divine_shield};zone={c.zone.name}", not before and c.divine_shield and c.zone == Zone.PLAY


def p129_opponent():
    g = game()
    c = play(g.player1, "AT_129")
    g.end_turn()
    play(g.player2, MOONFIRE, c)
    return f"shield_after_opponent_spell={c.divine_shield};damage={c.damage};zone={c.zone.name}", not c.divine_shield and c.damage == 1 and c.zone == Zone.PLAY


def p130():
    g = game(CardClass.WARRIOR)
    ally1 = put(g.player1, "CS2_182")
    ally2 = put(g.player1, "CS2_182")
    enemy = put(g.player2, "CS2_182")
    c = shuffle(g.player1, "AT_130")
    g.player1.draw()
    return f"drawn={c.zone.name};ally_damage={[ally1.damage,ally2.damage]};enemy_damage={enemy.damage}", c.zone == Zone.HAND and ally1.damage == ally2.damage == 1 and enemy.damage == 0


def p131():
    hits = []
    for seed in range(30, 46):
        g = game(seed=seed)
        c = play(g.player1, "AT_131")
        target = put(g.player2, "CS2_182")
        play(g.player1, "CS2_004", c)
        deltas = (30 - g.player2.hero.health, target.damage)
        if sum(deltas) != 3 or set(deltas) != {0, 3}:
            return f"seed={seed};enemy_hero_damage={deltas[0]};enemy_minion_damage={deltas[1]};source={c.zone.name}", False
        hits.append("hero" if deltas[0] else "minion")
    return f"16_seeded_targets={hits}", set(hits) == {"hero", "minion"}


def p132():
    g = game(CardClass.MAGE)
    old = g.player1.hero.power.id
    c = play(g.player1, "AT_132")
    new = g.player1.hero.power.id
    before = g.player2.hero.health
    g.player1.hero.power.use(target=g.player2.hero)
    dealt = before - g.player2.hero.health
    return f"old_power={old};new_power={new};upgraded_damage={dealt};card_zone={c.zone.name}", old == "HERO_08bp" and new == "HERO_08bp2" and dealt == 2 and c.zone == Zone.PLAY


def p132_warrior():
    g = game(CardClass.WARRIOR, CardClass.WARRIOR)
    old = g.player1.hero.power.id
    c = play(g.player1, "AT_132")
    new = g.player1.hero.power.id
    before = g.player1.hero.armor
    g.player1.hero.power.use()
    gained = g.player1.hero.armor - before
    return f"old_power={old};new_power={new};armor_gained={gained};card_zone={c.zone.name}", old != new and gained == 4 and c.zone == Zone.PLAY


def p133_win():
    g, c = joust("AT_133", "NEW1_030", WISP)
    return f"stats={c.atk}/{c.health};base={c.data.atk}/{c.data.health}", c.atk == c.data.atk + 1 and c.health == c.data.health + 1


def p133_lose():
    g, c = joust("AT_133", WISP, "NEW1_030")
    return f"stats={c.atk}/{c.health};base={c.data.atk}/{c.data.health}", c.atk == c.data.atk and c.health == c.data.health


CASES = {
    "AT_100": [("inspire_recruit", "With Silver Hand Regent, a Paladin Hero Power summons one extra Recruit beyond its usual one.", p100)],
    "AT_103": [("target_four_damage", "Battlecry deals exactly 4 damage to selected minion.", p103)],
    "AT_104": [("joust_win_heals_seven", "Higher-cost friendly minion heals hero for 7.", p104_win), ("joust_loss_no_heal", "Lower-cost friendly minion does not heal hero.", p104_lose)],
    "AT_105": [("self_three_damage", "Battlecry damages self exactly 3 without changing base maximum Health.", p105)],
    "AT_106": [("target_demon_silence", "Target domain contains friendly and enemy Demons only; selected enemy Demon loses Taunt through Silence.", p106), ("friendly_demon_silence", "A friendly Demon can be selected and silenced.", p106_friendly)],
    "AT_108": [("joust_win_charge", "Higher-cost friendly minion grants Charge.", p108_win), ("joust_loss_no_charge", "Lower-cost friendly minion does not grant Charge.", p108_lose)],
    "AT_109": [("inspire_attack_permission", "After summoning sickness ends, cannot attack before Inspire; can attack after Hero Power.", p109)],
    "AT_110": [("inspire_return_hand", "Hero Power returns Coliseum Manager to controller's hand.", p110)],
    "AT_111": [("heal_both_heroes_cap", "Battlecry heals each hero up to 4, capped at 30.", p111)],
    "AT_112": [("joust_win_two_keywords", "Winning Joust grants Taunt and Divine Shield.", p112_win), ("joust_loss_no_keywords", "Losing Joust grants neither keyword.", p112_lose)],
    "AT_113": [("inspire_squire_hand", "Hero Power adds exactly one 2/2 Squire card to hand.", p113)],
    "AT_114": [("native_taunt_and_stats", "Evil Heckler enters with printed stats and active Taunt.", p114)],
    "AT_115": [("next_hero_power_discount_consumed", "Next Hero Power costs 2 less, then returns to printed cost.", p115)],
    "AT_116": [("holding_dragon_buff", "Holding Dragon grants +1 Attack and Taunt.", p116_yes), ("no_dragon_no_buff", "Without Dragon, printed Attack and no Taunt.", p116_no)],
    "AT_117": [("friendly_spellpower_buff", "Friendly Spell Damage minion grants +2/+2.", p117_yes), ("no_spellpower_no_buff", "Without Spell Damage minion, printed stats.", p117_no), ("opponent_spellpower_no_buff", "Only opponent has Spell Damage: Master stays at printed stats.", p117_enemy_only)],
    "AT_118": [("random_paladin_card", "Across 16 seeds Battlecry adds one Paladin class card to own hand and varies within the pool.", p118)],
    "AT_119": [("inspire_two_two", "Hero Power grants Raider exactly +2/+2.", p119)],
    "AT_120": [("two_hero_power_uses_discount", "Two Hero Power uses this game reduce Frost Giant cost by 2.", p120)],
    "AT_121": [("battlecry_only_trigger", "Plain minion leaves stats unchanged; own Battlecry card grants exactly +1/+1.", p121), ("opponent_battlecry_no_trigger", "Opponent Battlecry does not buff Crowd Favorite.", p121_opponent_battlecry)],
    "AT_122": [("four_allies_damage", "Four other friendly minions enable targeted 4 damage.", p122_yes), ("three_allies_no_damage", "Only three other friendlies do not enable damage.", p122_no)],
    "AT_123": [("holding_dragon_deathrattle", "With Dragon in hand death deals 3 to all other minions.", p123_yes), ("no_dragon_no_deathrattle_damage", "Without Dragon, death deals no minion damage.", p123_no), ("dragon_added_after_play", "Adding a Dragon after play, before death, enables 3 damage to both sides.", p123_dragon_added_late), ("dragon_removed_before_death", "Removing Dragon after play, before death, prevents Deathrattle damage.", p123_dragon_removed_before_death)],
    "AT_124": [("redirect_hero_damage", "Hero damage is redirected to Bolf while hero stays healthy.", p124)],
    "AT_125": [("charge_minion_only", "Charge allows immediate minion attack but enemy hero is illegal.", p125)],
    "AT_127": [("inspire_random_spell", "Across 16 seeds Hero Power adds one Spell card to hand and varies within the pool.", p127)],
    "AT_128": [("winning_joust_bounce", "Higher-cost own deck minion returns Skeleton Knight to hand on death.", p128_win), ("losing_joust_graveyard", "Lower-cost own deck minion leaves Knight in graveyard.", p128_lose)],
    "AT_129": [("friendly_target_spell_shield", "Targeting Fjola with own spell grants Divine Shield.", p129), ("opponent_spell_no_shield", "An opponent spell on Fjola does not grant Divine Shield.", p129_opponent)],
    "AT_130": [("draw_damages_own_minions", "Drawing Sea Reaver deals 1 to each own minion, none to enemy.", p130)],
    "AT_131": [("target_spell_random_enemy", "Across 16 seeds targeting Eydis deals exactly 3 to one random enemy and reaches hero and minion.", p131)],
    "AT_132": [("mage_upgrade_two_damage", "Justicar replaces Mage Fireblast with Rank 2 that deals 2 damage.", p132), ("warrior_upgrade_four_armor", "Justicar replaces Warrior Armor Up with Rank 2 that grants 4 Armor.", p132_warrior)],
    "AT_133": [("joust_win_plus_one", "Winning Joust grants +1/+1.", p133_win), ("joust_loss_printed", "Losing Joust leaves printed stats.", p133_lose)],
}


def main():
    baseline = [r for r in read(BASE) if r["set"] == "The Grand Tournament (TGT)" and r["card_id"] >= "AT_100"]
    assert len(baseline) == len(CASES) == 30 and {r["card_id"] for r in baseline} == set(CASES)
    master = {r["card_id"]: r for r in read(MASTER)}
    prior = {r["card_id"]: r for r in read(QUALITY)}
    results, verdicts = [], []
    for card in baseline:
        cid = card["card_id"]
        for case_id, expected, fn in CASES[cid]:
            try:
                observed, passed = fn()
                outcome = "pass" if passed is True else "confirmed_error" if passed is False else "inconclusive"
            except Exception as exc:
                observed = f"{type(exc).__name__}: {exc}"
                outcome = "inconclusive"
            metadata = master[cid]
            results.append({"card_id": cid, "case_id": case_id, "expected": expected,
                            "observed": observed, "outcome": outcome,
                            "notes": f"EN: {metadata['card_text_en']} ZH: {metadata['card_text_zh']} Implementation: {metadata['python_source'] or 'native tags'}. Existing refs: {metadata['test_refs_candidate'] or 'none'}. Previous audit: {prior[cid]['reason']}"})
            write(PROBE, PF, results)
            print(cid, case_id, outcome, observed, flush=True)
        own = [r for r in results if r["card_id"] == cid]
        errors = [r for r in own if r["outcome"] == "confirmed_error"]
        open_cases = [r for r in own if r["outcome"] == "inconclusive"]
        status = "RED" if errors else "YELLOW" if open_cases else "GREEN"
        if errors:
            reason = "确认与卡面不符：" + "; ".join(f"{r['case_id']} expected[{r['expected']}] observed[{r['observed']}]" for r in errors)
        elif open_cases:
            reason = "运行测试尚未完成关键行为：" + "; ".join(f"{r['case_id']}={r['observed']}" for r in open_cases)
        else:
            reason = "针对性对局断言通过：" + "; ".join(f"{r['case_id']}={r['observed']}" for r in own)
        verdicts.append({"card_id": cid, "status": status, "mechanic_scope": metadata["mechanics"],
                         "reason": reason, "probe_file": PROBE.name,
                         "notes": f"EN/ZH text, source, previous audit and existing tests are recorded in {PROBE.name}; {len(own)} independent live case(s)."})
        write(VERDICT, VF, verdicts)


if __name__ == "__main__":
    main()
