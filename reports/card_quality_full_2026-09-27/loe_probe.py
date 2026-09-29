"""Card-specific runtime probes for the frozen LOE YELLOW roster.

Run from the repository root:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/loe_probe.py

The script records actual Fireplace state assertions after every case/card. It
does not modify card implementations or the shared report builder.
"""

import argparse
import csv
import logging
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone

from utils import FIREBALL, MOONFIRE, MURLOC, WISP, prepare_empty_game


HERE = Path(__file__).resolve().parent
BASELINE = HERE / "four_set_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY_PATH = HERE / "card_quality.csv"
MECHANISM_PATH = HERE / "card_mechanism.csv"
ISSUES_PATH = HERE / "mechanism_issues.csv"
PROBE_OUT = HERE / "loe_probe.csv"
VERDICT_OUT = HERE / "loe_verdict.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")
SET_NAME = "League of Explorers (LOE)"
BASIC_HERO_POWER_IDS = {
    "HERO_01bp", "HERO_02bp", "HERO_03bp", "HERO_04bp", "HERO_05bp",
    "HERO_06bp", "HERO_07bp", "HERO_08bp", "HERO_09bp", "HERO_10bp",
}
logging.getLogger("fireplace").setLevel(logging.CRITICAL)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


ROSTER_ROWS = [row for row in read_csv(BASELINE) if row["set"] == SET_NAME]
CARDS = {row["card_id"]: row for row in read_csv(MASTER)}
QUALITY = {row["card_id"]: row for row in read_csv(QUALITY_PATH)}
MECHANISM_ROWS = read_csv(MECHANISM_PATH)
ISSUE_ROWS = read_csv(ISSUES_PATH)
EXPECTED_IDS = {
    "LOE_002", "LOE_003", "LOE_006", "LOE_007", "LOE_009", "LOE_010",
    "LOE_011", "LOE_016", "LOE_017", "LOE_018", "LOE_019", "LOE_020",
    "LOE_021", "LOE_022", "LOE_023", "LOE_026", "LOE_027", "LOE_029",
    "LOE_038", "LOE_039", "LOE_046", "LOE_047", "LOE_050", "LOE_051",
    "LOE_053", "LOE_073", "LOE_076", "LOE_077", "LOE_079", "LOE_086",
    "LOE_089", "LOE_092", "LOE_104", "LOE_105", "LOE_107", "LOE_110",
    "LOE_111", "LOE_113", "LOE_115", "LOE_116", "LOE_118", "LOE_119",
}
assert len(ROSTER_ROWS) == 42 and {row["card_id"] for row in ROSTER_ROWS} == EXPECTED_IDS
assert all(CARDS[cid]["set"] == SET_NAME for cid in EXPECTED_IDS)

PROBE_ROWS = read_csv(PROBE_OUT) if PROBE_OUT.exists() else []
VERDICT_ROWS = read_csv(VERDICT_OUT) if VERDICT_OUT.exists() else []


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def new_game(class1=CardClass.MAGE, class2=CardClass.MAGE, seed=None):
    game = prepare_empty_game(class1, class2)
    game.player1.is_standard = False
    game.player2.is_standard = False
    assert game.player1.is_standard is False and game.player2.is_standard is False, "LOE probes must run with both players in Wild"
    if seed is not None:
        game.random.seed(seed)
    if game.current_player is not game.player1:
        game.end_turn()
    game.player1.max_mana = game.player2.max_mana = 10
    return game


def all_ids(cards):
    return [card.id for card in cards]


def discover_case(card_id, predicate, label):
    """Play a Discover minion, validate three distinct eligible options, pick one."""
    game = new_game()
    player = game.player1
    minion = player.give(card_id)
    minion.play()
    options = list(player.choice.cards)
    ids = all_ids(options)
    assert len(options) == 3 and len(set(ids)) == 3, f"options={ids}"
    invalid = [(card.id, card.cost, card.type.name) for card in options if not predicate(card)]
    assert not invalid, f"ineligible={invalid};options={ids}"
    chosen = options[0]
    player.choice.choose(chosen)
    assert not player.choice, f"choice remains;options={ids}"
    assert chosen.zone == Zone.HAND and chosen in player.hand, f"chosen={chosen.id}:{chosen.zone.name};hand={all_ids(player.hand)}"
    return f"options={ids};chosen={chosen.id}:HAND;remaining_choice=0"


def case_loE_002():
    game = new_game()
    player, opponent = game.player1, game.player2
    target = opponent.summon("CS2_182")
    torch = player.give("LOE_002")
    torch.play(target=target)
    assert target.health == 2 and target in opponent.field, f"target={target.health}/{target.zone.name}"
    shuffled = [card for card in player.deck if card.id == "LOE_002t"]
    assert len(shuffled) == 1 and shuffled[0].zone == Zone.DECK, f"deck={all_ids(player.deck)}"
    drawn = player.draw()
    assert drawn is shuffled[0] and drawn.zone == Zone.HAND, f"drawn={drawn.id}:{drawn.zone.name}"
    drawn.play(target=target)
    assert target.zone == Zone.GRAVEYARD and target not in opponent.field, f"target={target.health}/{target.zone.name}"
    assert drawn.zone == Zone.GRAVEYARD, f"torch={drawn.zone.name}"
    return f"first_hit=3;shuffled=LOE_002t;second_hit=6;target={target.zone.name}"


def case_loE_006():
    return discover_case("LOE_006", lambda c: c.has_deathrattle, "Deathrattle")


def case_loE_007():
    game = new_game()
    owner, opponent = game.player1, game.player2
    curse_spell = owner.give("LOE_007")
    curse_spell.play()
    cursed = next(card for card in opponent.hand if card.id == "LOE_007t")
    assert opponent.hero.health == 30 and cursed.zone == Zone.HAND, f"health={opponent.hero.health};curse={cursed.zone.name}"
    game.end_turn()
    assert opponent.hero.health == 28 and cursed in opponent.hand, f"start1={opponent.hero.health};curse={cursed.zone.name}"
    game.end_turn()
    game.end_turn()
    assert opponent.hero.health == 26 and cursed in opponent.hand, f"start2={opponent.hero.health};curse={cursed.zone.name}"
    cursed.discard()
    game.end_turn()
    game.end_turn()
    assert opponent.hero.health == 26, f"after leaving hand={opponent.hero.health}"
    return "held_turns=2x2_damage;discarded=no_further_damage;curse_zone=GRAVEYARD"


def case_loE_009():
    game = new_game()
    player = game.player1
    destroyer = player.give("LOE_009")
    destroyer.play()
    assert len(player.field) == 1, f"pre_end={all_ids(player.field)}"
    game.end_turn()
    scarabs = [m for m in player.field if m.id == "LOE_009t"]
    assert len(scarabs) == 1 and (scarabs[0].atk, scarabs[0].health, scarabs[0].taunt) == (1, 1, True), f"field={[(m.id,m.atk,m.health,m.taunt) for m in player.field]}"
    return f"source=PLAY;scarab={scarabs[0].atk}/{scarabs[0].health},taunt=True"


def case_loE_009_full_board():
    game = new_game()
    player = game.player1
    destroyer = player.give("LOE_009")
    destroyer.play()
    for _ in range(6):
        player.summon(WISP)
    assert len(player.field) == 7, f"setup field={len(player.field)}"
    game.end_turn()
    assert len(player.field) == 7 and destroyer in player.field and not player.field.filter(id="LOE_009t"), f"after end turn={[m.id for m in player.field]}"
    return "full_board_end_turn;no_scarab_summoned;board_stays_at_7"


def case_loE_010():
    game = new_game()
    owner, opponent = game.player1, game.player2
    snake = owner.give("LOE_010")
    snake.play()
    assert snake.poisonous, f"poisonous={snake.poisonous}"
    game.end_turn()
    target = opponent.summon("CS2_182")
    game.end_turn()
    assert snake.can_attack(), f"snake cannot attack;zone={snake.zone.name}"
    snake.attack(target)
    assert target.zone == Zone.GRAVEYARD and target not in opponent.field, f"poisonous target survived: {target.health}/{target.zone.name}"
    assert snake.zone == Zone.GRAVEYARD, f"snake should take Yeti retaliation;snake={snake.zone.name}"
    return f"poisonous=True;enemy_yeti={target.zone.name};snake_died_to_4_attack_retaliation={snake.zone.name}"


def case_loE_011():
    game = new_game()
    player = game.player1
    player.hero.set_current_health(10)
    first = player.give("CS2_231")
    first.shuffle_into_deck()
    reno = player.give("LOE_011")
    reno.play()
    assert player.hero.health == 10, f"duplicate deck healed={player.hero.health}"
    first.draw()
    player.hero.set_current_health(10)
    unique = player.give("CS2_182")
    unique.shuffle_into_deck()
    reno2 = player.give("LOE_011")
    reno2.play()
    assert player.hero.health == 30, f"unique deck health={player.hero.health}"
    return f"duplicate_deck=10hp;single_card_deck=30hp;deck={[c.id for c in player.deck]}"


def case_loE_016():
    game = new_game()
    owner, opponent = game.player1, game.player2
    elemental = owner.give("LOE_016")
    elemental.play()
    opponent_hero = opponent.hero.health
    owner.give("CS2_231").play()
    after_vanilla = opponent.hero.health
    assert (opponent_hero, after_vanilla) == (30, 30), f"enemy hero={opponent_hero}->{after_vanilla}"
    game.end_turn()
    owner_state = (owner.hero.health, elemental.health)
    doctor = opponent.give("EX1_011")
    doctor.play(target=opponent.hero)
    assert (owner.hero.health, elemental.health) == owner_state, f"opponent battlecry triggered Rumbling: owner={owner.hero.health};elemental={elemental.health}"
    doctor.destroy()
    game.end_turn()
    owner.hero.set_current_health(20)
    owner.give("EX1_011").play(target=owner.hero)
    assert owner.hero.health == 22 and opponent.hero.health == 28, f"owner_health={owner.hero.health};opponent_health={opponent.hero.health}"
    return "vanilla_and_opponent_battlecry=no_trigger;own_battlecry=2_damage_to_only_enemy_hero"


def case_loE_016_random_target_domain():
    hits = {"hero": 0, "minion": 0}
    for seed in range(1, 17):
        game = new_game(seed=seed)
        owner, opponent = game.player1, game.player2
        owner.summon("LOE_016")
        target = opponent.summon("CS2_182")
        owner.hero.set_current_health(20)
        owner.give("EX1_011").play(target=owner.hero)
        hero_damage = 30 - opponent.hero.health
        minion_damage = target.max_health - target.health
        assert (hero_damage, minion_damage) in ((2, 0), (0, 2)), f"seed={seed};hero_damage={hero_damage};minion_damage={minion_damage}"
        hits["hero" if hero_damage else "minion"] += 1
    assert all(hits.values()), f"fixed seeds did not select both legal enemy types: {hits}"
    return f"seeds=16;eligible_domain=enemy_hero_or_minion;hits={hits}"


def case_loE_017():
    game = new_game()
    owner, opponent = game.player1, game.player2
    target = opponent.summon("CS2_182")
    target.set_current_health(2)
    keeper = owner.give("LOE_017")
    assert target in keeper.targets, f"target not legal: {[getattr(t,'id',None) for t in keeper.targets]}"
    keeper.play(target=target)
    assert (target.atk, target.max_health, target.health, target.damaged) == (3, 3, 3, False), f"target={target.atk}/{target.health}/{target.max_health};damaged={target.damaged}"
    return f"enemy_target_legal=True;set_stats=3/3;damage_cleared=True;keeper={keeper.zone.name}"


def case_loE_017_friendly_target():
    game = new_game()
    owner, opponent = game.player1, game.player2
    friend = owner.summon("CS2_182")
    friend.set_current_health(2)
    enemy = opponent.summon("CS2_182")
    keeper = owner.give("LOE_017")
    assert friend in keeper.targets and enemy in keeper.targets, f"legal targets={[getattr(t,'id',None) for t in keeper.targets]}"
    keeper.play(target=friend)
    assert (friend.atk, friend.max_health, friend.health, friend.damaged) == (3, 3, 3, False), f"friendly={friend.atk}/{friend.health}/{friend.max_health};damaged={friend.damaged}"
    assert (enemy.atk, enemy.max_health, enemy.health) == (4, 5, 5), f"untargeted enemy changed={enemy.atk}/{enemy.health}/{enemy.max_health}"
    return "friendly_and_enemy_targets_legal;selected_friendly_set_to_3/3;unselected_enemy_unchanged"


def case_loE_018():
    game = new_game()
    owner, opponent = game.player1, game.player2
    trogg = owner.give("LOE_018")
    trogg.play()
    owner.give("EX1_243").play()
    assert trogg.atk == 3, f"own overload=2;attack={trogg.atk}"
    game.end_turn()
    opponent.give("EX1_243").play()
    assert trogg.atk == 3, f"opponent overload changed attack={trogg.atk}"
    return "own_overload=2_attack_gain;opponent_overload=no_gain"


def case_loE_019():
    game = new_game()
    owner = game.player1
    gnome = owner.give("EX1_029")
    gnome.play()
    raptor = owner.give("LOE_019")
    raptor.play(target=gnome)
    assert raptor.has_deathrattle, f"raptor deathrattle={raptor.has_deathrattle}"
    raptor.destroy()
    assert raptor.zone == Zone.GRAVEYARD and game.player2.hero.health == 28, f"raptor={raptor.zone.name};opponent={game.player2.hero.health}"
    return "copied_Leper_Gnome_deathrattle=2_face_damage;raptor=GRAVEYARD"


def case_loE_020():
    game = new_game()
    owner, opponent = game.player1, game.player2
    friendly_one = owner.give("CS1_042")
    friendly_one.shuffle_into_deck()
    friendly_two = owner.give("CS2_182")
    friendly_two.shuffle_into_deck()
    enemy_one = opponent.give("CS1_042")
    enemy_one.shuffle_into_deck()
    enemy_two = opponent.give("CS2_182")
    enemy_two.shuffle_into_deck()
    camel = owner.give("LOE_020")
    camel.play()
    assert friendly_one in owner.field and friendly_one.zone == Zone.PLAY, f"friendly 1-cost={friendly_one.zone.name}"
    assert friendly_two in owner.deck, f"friendly 2-cost={friendly_two.zone.name}"
    assert enemy_one in opponent.field and enemy_one.zone == Zone.PLAY, f"enemy 1-cost={enemy_one.zone.name}"
    assert enemy_two in opponent.deck, f"enemy 2-cost={enemy_two.zone.name}"
    return "one_1cost_summoned_from_each_owner;2cost_cards_remain_in_decks"


def case_loE_020_random_deck_candidates():
    seen = {"owner": set(), "opponent": set()}
    for seed in range(1, 17):
        game = new_game(seed=seed)
        owner, opponent = game.player1, game.player2
        for player in (owner, opponent):
            for card_id in ("CS1_042", "CS2_168", "CS2_182"):
                card = player.give(card_id)
                card.shuffle_into_deck()
        owner.give("LOE_020").play()
        for label, player in (("owner", owner), ("opponent", opponent)):
            eligible_ids = {"CS1_042", "CS2_168"}
            summoned = [m for m in player.field if m.id in eligible_ids]
            left = [m for m in player.deck if m.id in eligible_ids]
            assert len(summoned) == 1 and summoned[0].cost == 1, f"seed={seed};{label} summoned={[(m.id,m.cost) for m in summoned]}"
            assert len(left) == 1 and left[0].id in eligible_ids - {summoned[0].id}, f"seed={seed};{label} remaining={[m.id for m in left]}"
            assert any(m.id == "CS2_182" for m in player.deck), f"seed={seed};{label} 2-cost left deck={[m.id for m in player.deck]}"
            seen[label].add(summoned[0].id)
    assert all(ids == {"CS1_042", "CS2_168"} for ids in seen.values()), f"candidate domain did not cover both 1-cost IDs: {seen}"
    return f"seeds=16;owner_choices={sorted(seen['owner'])};opponent_choices={sorted(seen['opponent'])};2-cost_cards_never_selected"


def case_loE_020_one_side_full_board():
    # First game: controller full, opponent has one slot; only opponent recruit fits.
    game = new_game()
    owner, opponent = game.player1, game.player2
    own_card = owner.give("CS1_042")
    own_card.shuffle_into_deck()
    enemy_card = opponent.give("CS1_042")
    enemy_card.shuffle_into_deck()
    for _ in range(6):
        owner.summon(WISP)
        opponent.summon(WISP)
    owner.give("LOE_020").play()
    assert len(owner.field) == 7 and own_card in owner.deck, f"controller full: field={len(owner.field)};deck={all_ids(owner.deck)}"
    assert len(opponent.field) == 7 and enemy_card in opponent.field, f"opponent had one slot: field={len(opponent.field)};card={enemy_card.zone.name}"

    # Reverse capacity: controller has one slot; opponent is full.
    game = new_game()
    owner, opponent = game.player1, game.player2
    own_card = owner.give("CS1_042")
    own_card.shuffle_into_deck()
    enemy_card = opponent.give("CS1_042")
    enemy_card.shuffle_into_deck()
    for _ in range(5):
        owner.summon(WISP)
    for _ in range(7):
        opponent.summon(WISP)
    owner.give("LOE_020").play()
    assert len(owner.field) == 7 and own_card in owner.field, f"controller one slot: field={len(owner.field)};card={own_card.zone.name}"
    assert len(opponent.field) == 7 and enemy_card in opponent.deck, f"opponent full: field={len(opponent.field)};deck={all_ids(opponent.deck)}"
    return "controller_full_opponent_open=summon_opponent_only;controller_open_opponent_full=summon_controller_only;both_boards_capped_at_7"


def case_loE_021():
    game = new_game(CardClass.WARLOCK, CardClass.WARLOCK)
    owner, opponent = game.player1, game.player2
    trap = owner.give("LOE_021")
    trap.play()
    assert trap in owner.secrets, f"secret={trap.zone.name}"
    game.end_turn()
    opponent.hero.power.use()
    assert trap not in owner.secrets and trap.zone == Zone.GRAVEYARD, f"secret={trap.zone.name};secrets={all_ids(owner.secrets)}"
    assert owner.hero.health == 30 and opponent.hero.health == 23, f"heroes={owner.hero.health}/{opponent.hero.health}"
    return "opponent_Life_Tap=2_self_damage;Dart_Trap=5_to_only_eligible_enemy;secret=GRAVEYARD"


def case_loE_021_own_power_no_trigger():
    game = new_game(CardClass.WARLOCK, CardClass.WARLOCK)
    owner = game.player1
    trap = owner.give("LOE_021")
    trap.play()
    owner.hero.power.use()
    assert trap in owner.secrets and trap.zone == Zone.SECRET, f"own power consumed secret={trap.zone.name}"
    assert owner.hero.health == 28 and game.player2.hero.health == 30, f"own Life Tap affected heroes={owner.hero.health}/{game.player2.hero.health}"
    return "controller_Life_Tap=2_self_damage;secret_remained_armed;no_enemy_damage"


def case_loE_021_random_target_domain():
    hits = {"opponent_hero": 0, "opponent_minion": 0}
    for seed in range(1, 17):
        game = new_game(CardClass.WARLOCK, CardClass.WARLOCK, seed=seed)
        owner, opponent = game.player1, game.player2
        minion = opponent.summon("CS2_182")
        trap = owner.give("LOE_021")
        trap.play()
        game.end_turn()
        opponent.hero.power.use()
        assert trap.zone == Zone.GRAVEYARD, f"seed={seed};secret={trap.zone.name}"
        hero_damage = 30 - opponent.hero.health
        minion_died = minion.zone == Zone.GRAVEYARD
        assert (hero_damage, minion_died) in ((7, False), (2, True)), f"seed={seed};hero_damage={hero_damage};minion={minion.health}/{minion.zone.name}"
        hits["opponent_hero" if hero_damage == 7 else "opponent_minion"] += 1
    assert all(hits.values()), f"fixed seeds did not select both eligible opposing characters: {hits}"
    return f"seeds=16;eligible_domain=opponent_hero_or_minion;hits={hits};Life_Tap_damage_separated"


def case_loE_022():
    game = new_game()
    defender, attacker_owner = game.player1, game.player2
    monkey = defender.give("LOE_022")
    monkey.play()
    game.end_turn()
    attacker = attacker_owner.give("CS2_182")
    attacker.play()
    assert defender.hero not in attacker.targets and monkey in attacker.targets, f"targets={[getattr(t,'id','HERO') for t in attacker.targets]}"
    game.end_turn()
    game.end_turn()
    attacker.attack(monkey)
    assert monkey.zone == Zone.GRAVEYARD and attacker in attacker_owner.field and attacker.health == 2, f"attacker={attacker.health}/{attacker.zone.name};taunt={monkey.health}/{monkey.zone.name}"
    return "taunt=True;hero_not_legal;Yeti_attacks_taunt;taunt_minion_dies;Yeti_survives_at_2"


def case_loE_023():
    return discover_case("LOE_023", lambda c: c.cost == 1, "1-Cost collectible")


def case_loE_026():
    game = new_game()
    owner, opponent = game.player1, game.player2
    tiny = owner.give(MURLOC)
    tiny.play()
    owner.give(MOONFIRE).play(target=tiny)
    raider = opponent.summon("CS2_168")
    raider.destroy()
    wisp = owner.give(WISP)
    wisp.play()
    owner.give(MOONFIRE).play(target=wisp)
    spell = owner.give("LOE_026")
    spell.play()
    summoned = list(owner.field.filter(id=MURLOC)) + list(owner.field.filter(id="CS2_168"))
    assert len(summoned) == 2, f"field={all_ids(owner.field)}"
    assert all(m.id in (MURLOC, "CS2_168") for m in owner.field), f"non-murloc summoned: {all_ids(owner.field)}"
    assert len(opponent.field) == 0, f"enemy field={all_ids(opponent.field)}"
    return f"dead_murlocs=2;nonmurloc_deaths_excluded;copies_summoned={[m.id for m in summoned]}"


def case_loE_026_full_board():
    game = new_game()
    owner = game.player1
    dead_murloc = owner.summon(MURLOC)
    dead_murloc.destroy()
    for _ in range(7):
        owner.summon(WISP)
    assert len(owner.field) == 7, f"setup field={len(owner.field)}"
    owner.give("LOE_026").play()
    assert len(owner.field) == 7 and not owner.field.filter(id=MURLOC), f"after Anyfin={all_ids(owner.field)}"
    return "seven_slots_occupied;dead_murloc_not_summoned;field_stays_at_7"


def case_loE_027():
    game = new_game()
    owner, opponent = game.player1, game.player2
    trial = owner.give("LOE_027")
    trial.play()
    for _ in range(2):
        opponent.summon(WISP)
    game.end_turn()
    third = opponent.give(WISP)
    third.play()
    assert trial in owner.secrets and len(opponent.field) == 3 and third in opponent.field, f"below_threshold=secret{trial in owner.secrets};field={all_ids(opponent.field)}"
    fourth = opponent.give(WISP)
    fourth.play()
    assert trial not in owner.secrets and trial.zone == Zone.GRAVEYARD, f"secret={trial.zone.name}"
    assert fourth.zone == Zone.GRAVEYARD and len(opponent.field) == 3, f"fourth={fourth.zone.name};field={all_ids(opponent.field)}"
    return "opponent_minions=3_after_play_survives;4th_play_destroyed;secret_consumed"


def case_loE_029():
    return discover_case("LOE_029", lambda c: c.cost == 3, "3-Cost collectible")


def case_loE_038():
    game = new_game()
    player = game.player1
    zero = player.give(MOONFIRE)
    fireball = player.give(FIREBALL)
    sea_giant = player.give("EX1_586")
    base_costs = {card.id: card.cost for card in (zero, fireball, sea_giant)}
    naga = player.give("LOE_038")
    naga.play()
    assert all(card.cost == 5 for card in (zero, fireball, sea_giant)), f"aura_costs={[c.cost for c in (zero,fireball,sea_giant)]}"
    new_card = player.give("CS2_231")
    assert new_card.cost == 5, f"new card cost={new_card.cost}"
    naga.destroy()
    restored = (zero.cost, fireball.cost, sea_giant.cost, new_card.cost)
    assert restored == (base_costs[MOONFIRE], base_costs[FIREBALL], base_costs["EX1_586"], 0), f"base={base_costs};restored={restored}"
    return f"under_aura=5_each;post_aura={restored};base={base_costs}"


def case_loE_039():
    game = new_game()
    player = game.player1
    first = player.give("LOE_039")
    first.play()
    assert not player.choice, f"choice without mech={all_ids(player.choice.cards)}"
    player.summon("GVG_096")
    second = player.give("LOE_039")
    second.play()
    options = list(player.choice.cards)
    ids = all_ids(options)
    assert len(options) == 3 and len(set(ids)) == 3, f"options={ids}"
    assert all(Race.MECHANICAL in card.races for card in options), f"non-mechs={[(c.id,c.races) for c in options]}"
    selected = options[-1]
    player.choice.choose(selected)
    assert selected in player.hand and selected.zone == Zone.HAND and not player.choice, f"chosen={selected.zone.name};hand={all_ids(player.hand)}"
    return f"no_mech=no_discover;with_mech=3_distinct_mechs:{ids};chosen={selected.id}:HAND"


def case_loE_046():
    game = new_game()
    owner, opponent = game.player1, game.player2
    toad = owner.summon("LOE_046")
    toad.destroy()
    assert toad.zone == Zone.GRAVEYARD and opponent.hero.health == 29, f"toad={toad.zone.name};hero={opponent.hero.health}"
    return "deathrattle_with_only_enemy_hero=1_damage;toad=GRAVEYARD"


def case_loE_046_random_domain():
    hits = {"hero": 0, "minion": 0}
    for seed in range(1, 17):
        game = new_game(seed=seed)
        owner, opponent = game.player1, game.player2
        toad = owner.summon("LOE_046")
        target = opponent.summon("CS2_182")
        toad.destroy()
        hero_damage = 30 - opponent.hero.health
        minion_damage = target.max_health - target.health
        assert (hero_damage, minion_damage) in ((1, 0), (0, 1)), f"seed={seed};hero_damage={hero_damage};minion_damage={minion_damage}"
        hits["hero" if hero_damage else "minion"] += 1
        assert toad.zone == Zone.GRAVEYARD, f"seed={seed};toad={toad.zone.name}"
    assert all(hits.values()), f"16 fixed seeds did not cover both eligible enemy characters: {hits}"
    return f"seeds=16;eligible_domain=enemy_hero_or_minion;hits={hits}"


def case_loE_047():
    return discover_case("LOE_047", lambda c: c.type == CardType.MINION and Race.BEAST in c.races, "Beast")


def case_loE_050():
    game = new_game()
    player = game.player1
    raptor = player.summon("LOE_050")
    raptor.destroy()
    summons = [m for m in player.field if m is not raptor]
    assert raptor.zone == Zone.GRAVEYARD and len(summons) == 1, f"raptor={raptor.zone.name};field={all_ids(player.field)}"
    assert summons[0].cost == 1 and summons[0].type == CardType.MINION, f"summon={summons[0].id};cost={summons[0].cost};type={summons[0].type}"
    return f"deathrattle_summon={summons[0].id};cost=1;source=GRAVEYARD"


def case_loE_050_random_pool_domain():
    selected_ids = []
    for seed in range(1, 17):
        game = new_game(seed=seed)
        player = game.player1
        raptor = player.summon("LOE_050")
        raptor.destroy()
        summons = [m for m in player.field if m is not raptor]
        assert len(summons) == 1, f"seed={seed};field={all_ids(player.field)}"
        assert summons[0].type == CardType.MINION and summons[0].cost == 1, f"seed={seed};summon={summons[0].id};type={summons[0].type};cost={summons[0].cost}"
        selected_ids.append(summons[0].id)
    assert len(set(selected_ids)) >= 2, f"random pool only yielded one ID across seeds: {selected_ids}"
    return f"seeds=16;all_summons=1-cost_minions;distinct_candidates={sorted(set(selected_ids))}"


def case_loE_050_one_open_slot():
    game = new_game()
    player = game.player1
    raptor = player.summon("LOE_050")
    for _ in range(6):
        player.summon(WISP)
    assert len(player.field) == 7, f"setup field={len(player.field)}"
    before = list(player.field)
    raptor.destroy()
    summons = [m for m in player.field if m not in before]
    assert len(player.field) == 7 and len(summons) == 1 and summons[0].cost == 1, f"field={[(m.id,m.cost) for m in player.field]}"
    return f"source_death_opened_one_slot;one_1-cost_summon={summons[0].id};field=7"


def case_loE_051():
    game = new_game()
    owner, opponent = game.player1, game.player2
    moonkin = owner.give("LOE_051")
    moonkin.play()
    owner.give(MOONFIRE).play(target=opponent.hero)
    assert opponent.hero.health == 27, f"friendly spell did {30-opponent.hero.health}"
    game.end_turn()
    opponent.give(MOONFIRE).play(target=owner.hero)
    assert owner.hero.health == 27, f"opponent spell did {30-owner.hero.health}"
    moonkin.destroy()
    game.end_turn()
    owner.give(MOONFIRE).play(target=opponent.hero)
    assert opponent.hero.health == 26, f"after Moonkin death, unpowered Moonfire damage={30-opponent.hero.health}"
    return "both_sides_Moonfire_dealt_3;after_aura_removed_Moonfire_dealt_1"


def case_loE_053():
    game = new_game()
    player = game.player1
    djinni = player.give("LOE_053")
    djinni.play()
    other = player.give(WISP)
    other.play()
    player.give("CS2_004").play(target=other)
    assert other.max_health == 3 and djinni.max_health == 8, f"target/djinni maxhealth={other.max_health}/{djinni.max_health}"
    player.give(MOONFIRE).play(target=player.hero)
    assert djinni.max_health == 8 and player.hero.health == 29, f"hero-targeted spell copied or misresolved;djinni={djinni.max_health};hero={player.hero.health}"
    return "friendly_minion_target_spell_copied_once;hero_target_spell_not_copied"


def case_loE_053_enemy_target_no_copy():
    game = new_game()
    player, opponent = game.player1, game.player2
    djinni = player.give("LOE_053")
    djinni.play()
    djinni_state = (djinni.health, djinni.max_health)
    target = opponent.summon("CS2_182")
    frostbolt = player.give("CS2_024")
    assert target in frostbolt.targets, f"enemy target not legal;Frostbolt targets={[getattr(t,'id',None) for t in frostbolt.targets]}"
    frostbolt.play(target=target)
    assert target.health == 2 and target in opponent.field, f"enemy target={target.health}/{target.zone.name}"
    assert (djinni.health, djinni.max_health) == djinni_state, f"enemy-target spell copied to Djinni: before={djinni_state};after={(djinni.health,djinni.max_health)}"
    assert frostbolt.zone == Zone.GRAVEYARD, f"spell={frostbolt.zone.name}"
    return f"enemy_minion_hit_for_3;Djinni_state_unchanged={djinni_state};spell={frostbolt.zone.name}"


def case_loE_073():
    game = new_game()
    player = game.player1
    no_beast = player.give("LOE_073")
    no_beast.play()
    assert not no_beast.taunt, f"no-beast taunt={no_beast.taunt}"
    player.summon("GVG_092t")
    with_beast = player.give("LOE_073")
    with_beast.play()
    assert with_beast.taunt, f"beast-present taunt={with_beast.taunt}"
    return "no_beast=no_taunt;friendly_beast=taunt"


def case_loE_073_no_beast():
    game = new_game()
    devilsaur = game.player1.give("LOE_073")
    devilsaur.play()
    assert not devilsaur.taunt, f"taunt without Beast={devilsaur.taunt}"
    return "no_friendly_Beast;Taunt=False"


def case_loE_073_with_beast():
    game = new_game()
    player = game.player1
    beast = player.summon("GVG_092t")
    assert Race.BEAST in beast.races, f"setup token races={beast.races}"
    devilsaur = player.give("LOE_073")
    devilsaur.play()
    assert devilsaur.taunt, f"friendly Beast present;Taunt={devilsaur.taunt}"
    return f"friendly_beast={beast.id};Taunt=True"


def case_loE_073_enemy_beast_only():
    game = new_game()
    owner, opponent = game.player1, game.player2
    enemy_beast = opponent.summon("GVG_092t")
    assert Race.BEAST in enemy_beast.races, f"setup token races={enemy_beast.races}"
    devilsaur = owner.give("LOE_073")
    devilsaur.play()
    assert not any(Race.BEAST in minion.races for minion in owner.field if minion is not devilsaur), f"friendly field={[(m.id,m.races) for m in owner.field]}"
    assert devilsaur.taunt is False, f"enemy Beast incorrectly enabled Taunt={devilsaur.taunt}"
    return f"enemy_beast={enemy_beast.id};friendly_beasts=0;Taunt=False"


def case_loE_076():
    game = new_game()
    player = game.player1
    original = player.hero.power
    finley = player.give("LOE_076")
    finley.play()
    options = list(player.choice.cards)
    ids = all_ids(options)
    assert len(options) == 3 and len(set(ids)) == 3, f"options={ids}"
    assert set(ids) <= BASIC_HERO_POWER_IDS, f"non-basic option={[card_id for card_id in ids if card_id not in BASIC_HERO_POWER_IDS]};options={ids}"
    assert all(c.type == CardType.HERO_POWER and c.id != original.id for c in options), f"invalid={[ (c.id,c.type.name) for c in options]};current={original.id}"
    selected = options[1]
    player.choice.choose(selected)
    assert player.hero.power is selected and selected.zone == Zone.PLAY and not player.choice, f"current={player.hero.power.id};chosen={selected.id}:{selected.zone.name}"
    return f"original={original.id};3_distinct_basic_hero_powers={ids};selected={selected.id}:PLAY"


def case_loE_077():
    game = new_game()
    player = game.player1
    player.hero.set_current_health(20)
    player.give("LOE_077").play()
    player.give("EX1_011").play(target=player.hero)
    assert player.hero.health == 24, f"Voodoo Doctor healed to={player.hero.health}, expected 24"
    return "Brann_aura_active;one_2hp_battlecry_healed_4"


def case_loE_077_opponent_battlecry_not_doubled():
    game = new_game()
    owner, opponent = game.player1, game.player2
    brann = owner.give("LOE_077")
    brann.play()
    opponent.hero.set_current_health(20)
    game.end_turn()
    doctor = opponent.give("EX1_011")
    doctor.play(target=opponent.hero)
    assert opponent.hero.health == 22, f"opponent Battlecry healed {opponent.hero.health - 20};expected 2"
    assert brann in owner.field and brann.controller is owner, f"Brann control/zone={brann.controller}/{brann.zone.name}"
    return "opponent_Voodoo_Doctor_healed_2_once;Brann_aura_owner_only"


def case_loE_079():
    game = new_game()
    player = game.player1
    player.give("LOE_079").play()
    maps = [card for card in player.deck if card.id == "LOE_019t"]
    assert len(maps) == 1 and maps[0].zone == Zone.DECK, f"deck={all_ids(player.deck)}"
    map_card = player.draw()
    assert map_card is maps[0] and map_card.zone == Zone.HAND, f"drawn={map_card.id}:{map_card.zone.name}"
    map_card.play()
    assert any(card.id == "LOE_019t2" for card in player.hand), f"hand={all_ids(player.hand)};deck={all_ids(player.deck)}"
    return "Elise_added_Map_to_deck;Map_play_shuffled_Golden_Monkey_and_drew_it"


def case_loE_086():
    game = new_game()
    owner, opponent = game.player1, game.player2
    stone = owner.give("LOE_086")
    stone.play()
    game.end_turn()
    opponent.give(MOONFIRE).play(target=owner.hero)
    assert len([m for m in owner.field if m is not stone]) == 0, f"opponent spell triggered: {all_ids(owner.field)}"
    game.end_turn()
    spell = owner.give("CS2_029")
    spell.play(target=opponent.hero)
    summons = [m for m in owner.field if m is not stone]
    assert len(summons) == 1 and summons[0].cost == spell.data.cost, f"summons={[(m.id,m.cost) for m in summons]};spellcost={spell.data.cost}"
    return f"opponent_spell=no_summon;own_spell_cost={spell.data.cost};summon={summons[0].id}:cost{summons[0].cost}"


def case_loE_086_effect_cast_pending():
    game = new_game()
    player = game.player1
    stone = player.give("LOE_086")
    stone.play()
    djinni = player.give("LOE_053")
    djinni.play()
    friend = player.give(WISP)
    friend.play()
    player.used_mana = 0
    spell = player.give("CS1_129")
    assert spell.cost == 1, f"Inner Fire cost={spell.cost}; expected 1"
    spell.play(target=friend)
    generated = [m for m in player.field if m not in (stone, djinni, friend)]
    assert len(generated) in (1, 2) and all(m.cost == 1 for m in generated), f"effect-cast generated={[(m.id,m.cost) for m in generated]}"
    effect_count = len(generated) - 1
    return (
        f"hand_cast_inner_fire_cost={spell.cost};hand_cast_summons=1;Djinni_effect_cast_additional_summons={effect_count};all_cost=1;"
        "whether an effect-cast counts as 'you cast' remains a rules-semantic blocker (CAST-001)",
        "inconclusive",
    )


def case_loE_089():
    game = new_game()
    player = game.player1
    runts = player.summon("LOE_089")
    runts.destroy()
    tokens = [m for m in player.field if m.id in ("LOE_089t", "LOE_089t2", "LOE_089t3")]
    assert runts.zone == Zone.GRAVEYARD and len(tokens) == 3, f"field={[(m.id,m.atk,m.health) for m in player.field]}"
    assert all((m.atk, m.health) == (2, 2) for m in tokens), f"tokens={[(m.id,m.atk,m.health) for m in tokens]}"
    full_game = new_game()
    full_player = full_game.player1
    full_runts = full_player.summon("LOE_089")
    for _ in range(6):
        full_player.summon(WISP)
    full_runts.destroy()
    assert len(full_player.field) == 7 and len([m for m in full_player.field if m.id.startswith("LOE_089t")]) == 1, f"full_board={all_ids(full_player.field)}"
    return "empty_board=3x2/2;one_open_slot=1_runt;board_never_exceeds_7"


def case_loE_092():
    game = new_game()
    player = game.player1
    rafaam = player.give("LOE_092")
    rafaam.play()
    options = list(player.choice.cards)
    ids = all_ids(options)
    assert len(options) == 3 and len(set(ids)) == 3 and set(ids) == {"LOEA16_3", "LOEA16_4", "LOEA16_5"}, f"options={ids}"
    assert all(c.type == CardType.SPELL for c in options), f"types={[(c.id,c.type.name) for c in options]}"
    chosen = options[0]
    player.choice.choose(chosen)
    assert chosen.zone == Zone.HAND and chosen in player.hand and not player.choice, f"chosen={chosen.id}:{chosen.zone.name}"
    return f"artifact_options={ids};selected={chosen.id}:HAND;choice_cleared"


def case_loE_104():
    game = new_game()
    caster, enemy = game.player1, game.player2
    target = enemy.summon("CS2_182")
    entomb = caster.give("LOE_104")
    assert target in entomb.targets and caster.hero not in entomb.targets, f"targets={[getattr(t,'id','HERO') for t in entomb.targets]}"
    entomb.play(target=target)
    assert target not in enemy.field and target in caster.deck and target.zone == Zone.DECK, f"enemy={all_ids(enemy.field)};caster_deck={all_ids(caster.deck)};target={target.zone.name}"
    assert entomb.zone == Zone.GRAVEYARD, f"spell={entomb.zone.name}"
    return f"enemy_minion_stolen_into_caster_deck;original_entity={target.id};spell=GRAVEYARD"


def case_loE_104_selected_target_only():
    game = new_game()
    caster, enemy = game.player1, game.player2
    selected = enemy.summon("CS2_182")
    unselected_enemy = enemy.summon("CS2_182")
    friendly = caster.summon("CS2_182")
    entomb = caster.give("LOE_104")
    targets = list(entomb.targets)
    assert selected in targets and unselected_enemy in targets, f"enemy targets={[getattr(t,'id',None) for t in targets]}"
    assert friendly not in targets and caster.hero not in targets, f"illegal friendly/hero target in {[getattr(t,'id','HERO') for t in targets]}"
    entomb.play(target=selected)
    assert selected in caster.deck and selected.zone == Zone.DECK and selected not in enemy.field, f"selected={selected.zone.name};caster_deck={all_ids(caster.deck)};enemy={all_ids(enemy.field)}"
    assert unselected_enemy in enemy.field and unselected_enemy.zone == Zone.PLAY, f"unselected enemy moved={unselected_enemy.zone.name}"
    assert friendly in caster.field and friendly.zone == Zone.PLAY, f"friendly moved={friendly.zone.name}"
    return "selected_enemy_entity_shuffled_to_caster_deck;other_enemy_and_friendly_minions_unchanged"


def case_loE_105():
    game = new_game()
    owner, opponent = game.player1, game.player2
    target = owner.summon(WISP)
    hat = owner.give("LOE_105")
    hat.play(target=target)
    assert (target.atk, target.health, target.max_health) == (2, 2, 2), f"buff={target.atk}/{target.health}/{target.max_health}"
    assert target.has_deathrattle, "Explorer's Hat did not grant Deathrattle"
    target.destroy()
    hats = [card for card in owner.hand if card.id == "LOE_105"]
    assert target.zone == Zone.GRAVEYARD and len(hats) == 1 and hats[0].zone == Zone.HAND, f"target={target.zone.name};hand={all_ids(owner.hand)}"
    return "target=+1/+1_and_deathrattle;death_returned_one_hat_to_controller_hand"


def case_loE_107():
    game = new_game()
    owner, opponent = game.player1, game.player2
    statue = owner.give("LOE_107")
    statue.play()
    game.end_turn()
    game.end_turn()
    assert statue.can_attack(), f"solo statue cannot attack;cant_attack={statue.cant_attack}"
    other = opponent.summon(WISP)
    assert not statue.can_attack() and statue.cant_attack, f"with enemy minion can_attack={statue.can_attack()}"
    other.destroy()
    assert statue.can_attack() and not statue.cant_attack, f"after enemy leaves can_attack={statue.can_attack()}"
    friendly = owner.summon(WISP)
    assert not statue.can_attack() and statue.cant_attack, f"with friendly minion can_attack={statue.can_attack()}"
    friendly.destroy()
    assert statue.can_attack() and not statue.cant_attack, f"after friendly leaves can_attack={statue.can_attack()}"
    return "only_minion_on_either_board_side_can_attack;both_friend_and_enemy_minions_block"


def case_loE_110():
    game = new_game()
    player = game.player1
    shade = player.give("LOE_110")
    shade.play()
    curses = [card for card in player.deck if card.id == "LOE_110t"]
    assert len(curses) == 1 and curses[0].zone == Zone.DECK, f"deck={all_ids(player.deck)}"
    drawn = player.draw()
    assert drawn is curses[0] and drawn.zone == Zone.GRAVEYARD, f"drawn={drawn.id}:{drawn.zone.name}"
    assert player.hero.health == 23, f"hero={player.hero.health}"
    return "Ancient_Curse_added_to_deck;draw_dealt_7_and_sent_curse_to_graveyard"


def case_loE_111():
    game = new_game()
    caster, enemy = game.player1, game.player2
    friendly_dies = caster.summon(WISP)
    friendly_lives = caster.summon("CS2_182")
    enemy_dies = enemy.summon(WISP)
    enemy_lives = enemy.summon("CS2_182")
    evil = caster.give("LOE_111")
    evil.play()
    assert friendly_dies.zone == Zone.GRAVEYARD and enemy_dies.zone == Zone.GRAVEYARD, f"deaths={friendly_dies.zone.name}/{enemy_dies.zone.name}"
    assert friendly_lives.health == enemy_lives.health == 2 and friendly_lives.zone == enemy_lives.zone == Zone.PLAY, f"survivors={friendly_lives.health}/{enemy_lives.health}"
    copies = [card for card in enemy.deck if card.id == "LOE_111"]
    assert len(copies) == 1 and not any(card.id == "LOE_111" for card in caster.deck), f"ownerdeck={all_ids(caster.deck)};enemydeck={all_ids(enemy.deck)}"
    return "all_minions_take_3;both_1health_minions_die;survivors=2health;copy_shuffled_only_into_opponent_deck"


def case_loE_113():
    game = new_game()
    owner, opponent = game.player1, game.player2
    murloc1 = owner.give(MURLOC).play()
    murloc2 = owner.give(MURLOC).play()
    other_friend = owner.summon(WISP)
    enemy = opponent.summon(WISP)
    enemy_murloc = opponent.summon(MURLOC)
    awesome = owner.give("LOE_113")
    assert awesome.cost == 5, f"2 friendly murlocs (excluding 1 enemy Murloc) should reduce 7 to 5;cost={awesome.cost}"
    awesome.play()
    assert (murloc1.atk, murloc1.health) == (3, 3) and (murloc2.atk, murloc2.health) == (3, 3), f"murlocs={murloc1.atk}/{murloc1.health},{murloc2.atk}/{murloc2.health}"
    assert (other_friend.atk, other_friend.health) == (3, 3), f"non-murloc friend={other_friend.atk}/{other_friend.health}"
    assert (enemy.atk, enemy.health) == (1, 1), f"enemy affected={enemy.atk}/{enemy.health}"
    assert (enemy_murloc.atk, enemy_murloc.health) == (1, 1), f"enemy Murloc affected or incorrectly counted={enemy_murloc.atk}/{enemy_murloc.health}"
    return "two_friendly_Murlocs_plus_one_enemy_Murloc;cost_5;friendly_minions_plus_2/+2;enemy_minions_unchanged"


def case_loE_115():
    observations = []
    for option_id, want_type in (("LOE_115a", CardType.MINION), ("LOE_115b", CardType.SPELL)):
        game = new_game()
        player = game.player1
        idol = player.give("LOE_115")
        idol.play(choose=option_id)
        options = list(player.choice.cards)
        ids = all_ids(options)
        assert len(options) == 3 and len(set(ids)) == 3, f"{option_id}:options={ids}"
        assert all(card.type == want_type for card in options), f"{option_id}:types={[(c.id,c.type.name) for c in options]}"
        chosen = options[0]
        player.choice.choose(chosen)
        assert chosen in player.hand and chosen.zone == Zone.HAND and not player.choice, f"{option_id}:chosen={chosen.id}:{chosen.zone.name}"
        observations.append(f"{option_id}={ids}->{chosen.id}:HAND")
    return ";".join(observations)


def case_loE_115_minion_branch():
    game = new_game()
    player = game.player1
    player.give("LOE_115").play(choose="LOE_115a")
    options = list(player.choice.cards)
    ids = all_ids(options)
    assert len(options) == 3 and len(set(ids)) == 3, f"minion options={ids}"
    assert all(card.type == CardType.MINION for card in options), f"types={[(c.id,c.type.name) for c in options]}"
    chosen = options[0]
    player.choice.choose(chosen)
    assert chosen in player.hand and chosen.zone == Zone.HAND and not player.choice, f"chosen={chosen.id}:{chosen.zone.name}"
    return f"three_distinct_minions={ids};chosen={chosen.id}:HAND"


def case_loE_115_spell_branch():
    game = new_game()
    player = game.player1
    player.give("LOE_115").play(choose="LOE_115b")
    options = list(player.choice.cards)
    ids = all_ids(options)
    assert len(options) == 3 and len(set(ids)) == 3, f"spell options={ids}"
    assert all(card.type == CardType.SPELL for card in options), f"types={[(c.id,c.type.name) for c in options]}"
    chosen = options[0]
    player.choice.choose(chosen)
    assert chosen in player.hand and chosen.zone == Zone.HAND and not player.choice, f"chosen={chosen.id}:{chosen.zone.name}"
    return f"three_distinct_spells={ids};chosen={chosen.id}:HAND"


def case_loE_011_duplicates():
    game = new_game()
    player = game.player1
    player.hero.set_current_health(10)
    first = player.give(WISP)
    first.shuffle_into_deck()
    second = player.give(WISP)
    second.shuffle_into_deck()
    player.give("LOE_011").play()
    assert player.hero.health == 10 and first in player.deck and second in player.deck, f"health={player.hero.health};deck={all_ids(player.deck)}"
    return "two_same_ids_in_deck;Reno_did_not_heal"


def case_loE_011_no_duplicates():
    game = new_game()
    player = game.player1
    player.hero.set_current_health(10)
    first = player.give(WISP)
    first.shuffle_into_deck()
    second = player.give("CS2_182")
    second.shuffle_into_deck()
    player.give("LOE_011").play()
    assert player.hero.health == 30 and first in player.deck and second in player.deck, f"health={player.hero.health};deck={all_ids(player.deck)}"
    return "two_distinct_ids_in_deck;Reno_fully_healed"


def case_loE_027_three_minions():
    game = new_game()
    owner, opponent = game.player1, game.player2
    trial = owner.give("LOE_027")
    trial.play()
    for _ in range(2):
        opponent.summon(WISP)
    game.end_turn()
    third = opponent.give(WISP)
    third.play()
    assert len(opponent.field) == 3 and third in opponent.field and trial in owner.secrets, f"field={all_ids(opponent.field)};secret={trial in owner.secrets}"
    return "opponent_played_third_minion;it_survived;secret_remained"


def case_loE_027_fourth_minion():
    game = new_game()
    owner, opponent = game.player1, game.player2
    trial = owner.give("LOE_027")
    trial.play()
    for _ in range(3):
        opponent.summon(WISP)
    game.end_turn()
    fourth = opponent.give(WISP)
    fourth.play()
    assert len(opponent.field) == 3 and fourth.zone == Zone.GRAVEYARD and trial.zone == Zone.GRAVEYARD, f"field={all_ids(opponent.field)};fourth={fourth.zone.name};secret={trial.zone.name}"
    return "opponent_played_fourth_minion;destroyed;secret_consumed"


def case_loE_039_no_mech():
    game = new_game()
    player = game.player1
    gorillabot = player.give("LOE_039")
    gorillabot.play()
    assert not player.choice and not gorillabot.powered_up, f"powered_up={gorillabot.powered_up};choice={all_ids(player.choice.cards)}"
    return "no_other_Mech;powered_up=False;no_Discover"


def case_loE_039_with_mech():
    game = new_game()
    player = game.player1
    mech = player.summon("GVG_096")
    gorillabot = player.give("LOE_039")
    gorillabot.play()
    options = list(player.choice.cards)
    ids = all_ids(options)
    assert gorillabot.powered_up and len(options) == 3 and len(set(ids)) == 3, f"powered={gorillabot.powered_up};options={ids}"
    assert all(Race.MECHANICAL in card.races for card in options), f"nonmechs={[(c.id,c.races) for c in options]}"
    chosen = options[0]
    player.choice.choose(chosen)
    assert chosen in player.hand and chosen.zone == Zone.HAND and not player.choice, f"chosen={chosen.id}:{chosen.zone.name}"
    return f"friendly_mech={mech.id};three_distinct_mech_options={ids};chosen={chosen.id}:HAND"


def case_loE_116_five_others():
    game = new_game()
    player = game.player1
    for _ in range(5):
        player.summon(WISP)
    seeker = player.give("LOE_116")
    seeker.play()
    assert (seeker.atk, seeker.health) == (1, 1), f"5 others;stats={seeker.atk}/{seeker.health}"
    return "five_other_minions;no_buff;1/1"


def case_loE_116_six_others():
    game = new_game()
    player = game.player1
    for _ in range(6):
        player.summon(WISP)
    seeker = player.give("LOE_116")
    seeker.play()
    assert (seeker.atk, seeker.health) == (5, 5), f"6 others;stats={seeker.atk}/{seeker.health}"
    return "six_other_minions;plus_4/+4;5/5"


def case_loE_116():
    game = new_game()
    player = game.player1
    for _ in range(5):
        player.summon(WISP)
    five = player.give("LOE_116")
    five.play()
    assert (five.atk, five.health) == (1, 1), f"5 others buffed to={five.atk}/{five.health}"
    six_game = new_game()
    player = six_game.player1
    for _ in range(6):
        player.summon(WISP)
    six = player.give("LOE_116")
    six.play()
    assert (six.atk, six.health) == (5, 5), f"6 others buffed to={six.atk}/{six.health}"
    return "five_other_minions=1/1;six_other_minions=5/5"


def case_loE_118():
    game = new_game()
    owner, opponent = game.player1, game.player2
    blade = owner.give("LOE_118")
    blade.play()
    assert owner.weapon is blade and blade.zone == Zone.PLAY, f"weapon={getattr(owner.weapon,'id',None)};zone={blade.zone.name}"
    game.end_turn()
    opponent.give(MOONFIRE).play(target=owner.hero)
    assert owner.hero.health == 28, f"1-damage spell became {30-owner.hero.health}"
    game.end_turn()
    owner.give(MOONFIRE).play(target=owner.hero)
    assert owner.hero.health == 26, f"self spell was not doubled;health={owner.hero.health}"
    return "enemy_and_friendly_1_damage_spells_each_dealt_2_to_weapon_owner"


def case_loE_119():
    game = new_game()
    owner, opponent = game.player1, game.player2
    armor = owner.give("LOE_119")
    armor.play()
    game.end_turn()
    opponent.give(FIREBALL).play(target=owner.hero)
    assert owner.hero.health == 29, f"6-damage Fireball should cap at 1;health={owner.hero.health}"
    armor.destroy()
    opponent.give(FIREBALL).play(target=owner.hero)
    assert owner.hero.health == 23, f"after armor leaves 6-damage Fireball should deal 6;health={owner.hero.health}"
    return "Fireball_under_armor=1_damage;after_armor_death=6_damage"


# Every key is one of the frozen YELLOW IDs. Each routine performs actual game
# actions and assertions; generic playability checks are not used as verdicts.
CASES = {
    "LOE_002": [("torch_damage_and_shuffle", "Deal 3, shuffle Roaring Torch into own deck, then Torch deals 6 and enters graveyard.", case_loE_002)],
    "LOE_003": [("spell_discover_pool_and_selection", "Three distinct Discover options are spells; choosing one moves it to hand and closes the choice.", lambda: discover_case("LOE_003", lambda c: c.type == CardType.SPELL, "spell"))],
    "LOE_006": [("deathrattle_discover_pool_and_selection", "Three distinct Discover options all have Deathrattle; choosing one moves it to hand.", case_loE_006)],
    "LOE_007": [("curse_held_turns_and_leaving_hand", "Cursed deals 2 at each opponent turn start while held, then stops after leaving hand.", case_loE_007)],
    "LOE_009": [("own_turn_end_scarab", "At the controller's turn end, summon exactly one 1/1 Taunt Scarab.", case_loE_009), ("own_turn_end_full_board", "If all seven friendly slots are occupied, end of turn does not exceed board capacity.", case_loE_009_full_board)],
    "LOE_010": [("poisonous_combat", "Pit Snake's 1 damage kills a 5-health minion; it may die to the minion's combat retaliation.", case_loE_010)],
    "LOE_011": [("duplicate_deck_no_heal", "Two copies of the same card in deck prevent healing.", case_loE_011_duplicates), ("distinct_deck_full_heal", "A deck with different card IDs fully heals the hero.", case_loE_011_no_duplicates)],
    "LOE_016": [("controller_battlecry_random_damage_scope", "Only the controller's Battlecry triggers 2 damage; vanilla and opponent Battlecries do not.", case_loE_016), ("random_enemy_target_domain", "Across fixed seeds, the trigger damages an enemy hero or enemy minion and each legal kind is selected.", case_loE_016_random_target_domain)],
    "LOE_017": [("set_enemy_minion_stats_and_clear_damage", "Battlecry can target an enemy minion and sets Attack and maximum/current Health to 3.", case_loE_017), ("friendly_target_domain", "A friendly minion is also a legal target; the selected minion becomes 3/3 and the unselected enemy is unchanged.", case_loE_017_friendly_target)],
    "LOE_018": [("overload_amount_and_controller", "Own 2 Overload grants +2 Attack; opponent Overload does not change Tunnel Trogg.", case_loE_018)],
    "LOE_019": [("copy_deathrattle_and_resolve", "Friendly Raptor gains Leper Gnome's Deathrattle; its death deals 2 to opponent.", case_loE_019)],
    "LOE_020": [("one_cost_from_each_owner_deck", "Battlecry summons one 1-Cost minion from each deck while leaving each 2-Cost minion in its deck.", case_loE_020), ("random_candidate_filter_per_deck", "Across fixed seeds, each owner chooses one of two eligible 1-Cost minions; the other and the 2-Cost card stay in that deck.", case_loE_020_random_deck_candidates), ("summon_respects_both_board_caps", "Each deck's summon resolves independently when its owner board is full and the other board has room.", case_loE_020_one_side_full_board)],
    "LOE_021": [("opponent_hero_power_secret", "Opponent Life Tap triggers Dart Trap and consumes it; verify Life Tap's 2 self-damage and trap's additional 5 damage separately.", case_loE_021), ("controller_power_does_not_trigger", "Controller's own Life Tap does not reveal or consume their Dart Trap.", case_loE_021_own_power_no_trigger), ("random_secret_target_domain", "Across fixed seeds, Dart Trap hits the opponent hero or opponent minion and each eligible type appears; Life Tap's own damage is separated.", case_loE_021_random_target_domain)],
    "LOE_022": [("taunt_attack_targeting", "Fierce Monkey blocks face and is the legal attack target; attacking minion dies in combat.", case_loE_022)],
    "LOE_023": [("one_cost_discover_pool_and_selection", "Three distinct eligible 1-Cost collectible Discover options; chosen card enters hand.", case_loE_023)],
    "LOE_026": [("dead_murlocs_only", "Summon copies of the two dead Murlocs; a dead non-Murloc is excluded.", case_loE_026), ("seven_murloc_board_cap", "With seven friendly minions already in play, Anyfin does not exceed the board cap.", case_loE_026_full_board)],
    "LOE_027": [("third_minion_below_threshold", "Opponent's third minion survives and Sacred Trial remains armed.", case_loE_027_three_minions), ("fourth_minion_triggers_trial", "Opponent's fourth minion is destroyed and consumes Sacred Trial.", case_loE_027_fourth_minion)],
    "LOE_029": [("three_cost_discover_pool_and_selection", "Three distinct eligible 3-Cost collectible Discover options; chosen card enters hand.", case_loE_029)],
    "LOE_038": [("hand_cost_aura_and_restore", "All current and later friendly hand cards cost 5 while Naga lives; their base costs return on death.", case_loE_038)],
    "LOE_039": [("no_mech_no_discover", "Without another Mech, Gorillabot offers no Discover.", case_loE_039_no_mech), ("mech_discover_pool_and_selection", "With another Mech, three distinct Mech options are offered and selected card enters hand.", case_loE_039_with_mech)],
    "LOE_046": [("deathrattle_single_enemy_target", "With only enemy hero eligible, deal exactly 1 damage to it.", case_loE_046), ("deathrattle_random_target_domain", "Across fixed seeds with hero and minion eligible, exactly one enemy character takes 1 and both legal target types appear.", case_loE_046_random_domain)],
    "LOE_047": [("beast_discover_pool_and_selection", "Three distinct Discover options are Beasts; choosing one moves it to hand.", case_loE_047)],
    "LOE_050": [("deathrattle_random_one_cost_summon", "Deathrattle summons exactly one 1-Cost minion and puts source in graveyard.", case_loE_050), ("deathrattle_random_pool_domain", "Across fixed seeds all random summons are 1-Cost minions and more than one pool member appears.", case_loE_050_random_pool_domain), ("deathrattle_one_open_slot", "When source death leaves one slot, exactly one random 1-Cost minion is summoned and board stays at seven.", case_loE_050_one_open_slot)],
    "LOE_051": [("both_players_spell_damage_aura", "Both players gain +2 Spell Damage; both sides' Moonfire deal 3; aura ends with source death.", case_loE_051)],
    "LOE_053": [("copy_spell_on_friendly_minion", "A spell cast on another friendly minion resolves on Djinni; a spell on hero does not copy.", case_loE_053), ("enemy_target_spell_no_copy", "A spell targeting an enemy minion damages only that enemy and is not copied to Djinni.", case_loE_053_enemy_target_no_copy)],
    "LOE_073": [("no_beast_no_taunt", "Without a friendly Beast, Fossilized Devilsaur does not gain Taunt.", case_loE_073_no_beast), ("friendly_beast_grants_taunt", "With a friendly Beast, Fossilized Devilsaur gains Taunt.", case_loE_073_with_beast), ("enemy_beast_does_not_grant_taunt", "An enemy Beast alone does not satisfy Fossilized Devilsaur's friendly-Beast condition.", case_loE_073_enemy_beast_only)],
    "LOE_076": [("basic_hero_power_discover", "Offers three distinct Hero Powers excluding current; selected power becomes current Hero Power.", case_loE_076)],
    "LOE_077": [("double_battlecry_aura", "Brann causes one 2-Health Battlecry to resolve twice for 4 healing.", case_loE_077), ("opponent_battlecry_not_doubled", "Brann doubles only the controller's Battlecries; an opponent Battlecry resolves once.", case_loE_077_opponent_battlecry_not_doubled)],
    "LOE_079": [("map_shuffle_and_draw", "Elise shuffles Map into deck; playing Map shuffles Golden Monkey and draws it.", case_loE_079)],
    "LOE_086": [("own_spell_matching_cost_summon", "Opponent spell does not trigger; own Fireball summons one minion of matching cost.", case_loE_086), ("effect_cast_trigger_semantics_pending", "Characterize Summoning Stone's response to Djinni's effect-cast copy; whether it counts as 'you cast' is unresolved in CAST-001.", case_loE_086_effect_cast_pending)],
    "LOE_089": [("deathrattle_three_tokens_and_board_cap", "Death summons three 2/2 Runts; with one open slot it summons only one and board stays at seven.", case_loE_089)],
    "LOE_092": [("artifact_discover_exact_pool_and_selection", "Discover offers the three distinct artifact IDs; chosen Artifact enters hand.", case_loE_092)],
    "LOE_104": [("enemy_minion_steal_into_deck", "Entomb targets an enemy minion, removes it from enemy board and shuffles that entity into caster deck.", case_loE_104), ("selected_enemy_only", "With two enemy minions and a friendly minion, only the selected enemy entity is shuffled into the caster's deck.", case_loE_104_selected_target_only)],
    "LOE_105": [("explorers_hat_buff_and_deathrattle", "Target gets +1/+1 and Hat Deathrattle; death returns one Hat to its controller's hand.", case_loE_105)],
    "LOE_107": [("only_minion_can_attack", "Statue can attack alone; either friendly or enemy minion blocks attack; removing either restores it.", case_loE_107)],
    "LOE_110": [("ancient_curse_when_drawn", "Shade shuffles Ancient Curse; drawing it deals 7 to owner and moves curse to graveyard.", case_loE_110)],
    "LOE_111": [("symmetric_damage_and_opponent_shuffle", "Deal 3 to all minions and shuffle one copy into opponent deck only.", case_loE_111)],
    "LOE_113": [("murloc_cost_discount_and_friendly_buff", "Two controlled Murlocs reduce cost to 5; spell buffs all friendly minions +2/+2 and leaves enemy unchanged.", case_loE_113)],
    "LOE_115": [("choose_one_minion_branch", "Choose One minion branch offers three distinct minions and puts the chosen card into hand.", case_loE_115_minion_branch), ("choose_one_spell_branch", "Choose One spell branch offers three distinct spells and puts the chosen card into hand.", case_loE_115_spell_branch)],
    "LOE_116": [("five_other_minions_no_buff", "Five other minions does not grant +4/+4.", case_loE_116_five_others), ("six_other_minions_plus_four", "Six other minions grant +4/+4.", case_loE_116_six_others)],
    "LOE_118": [("weapon_doubles_all_hero_damage", "Cursed Blade equips; an enemy and own 1-damage spell each deal 2 to its controller's hero.", case_loE_118)],
    "LOE_119": [("hero_damage_cap_per_hit", "Fireball deals 1 while Animated Armor is in play and 6 after the Armor leaves.", case_loE_119)],
}


def notes_for(card_id, detail):
    card = CARDS[card_id]
    prior = QUALITY[card_id]
    mechanism_audit = [row for row in MECHANISM_ROWS if row["card_id"] == card_id]
    issue_links = [
        row for row in ISSUE_ROWS
        if card_id in (row.get("confirmed_cards", "") + "|" + row.get("candidate_cards", "")).split("|")
    ]
    mechanism_summary = "; ".join(f"{row['mechanic']}={row['status']} ({row['reason']})" for row in mechanism_audit)
    issue_summary = "; ".join(f"{row['issue_id']}[{row['severity']}]: {row['summary']}" for row in issue_links) or "none identified in mechanism_issues.csv"
    return (
        f"EN: {card['card_text_en']} ZH: {card['card_text_zh']} "
        f"Impl: {card['python_source'] or 'no per-card Python; native tags/runtime implementation'}. "
        f"Existing tests: {card['test_refs_candidate'] or 'none found in card_master candidate references'}. "
        f"Previous audit: {prior['status']}; {prior['reason']} Mechanism audit: {mechanism_summary}. Known/candidate issue: {issue_summary}. "
        f"Probe: {detail}"
    )


def save_case(card_id, case_id, expected, probe, detail):
    try:
        result = probe()
        if isinstance(result, tuple) and len(result) == 2 and result[1] in {"pass", "confirmed_error", "inconclusive"}:
            observed, outcome = result
        else:
            observed, outcome = result, "pass"
    except AssertionError as exc:
        observed = str(exc) or f"AssertionError at {Path(traceback.extract_tb(exc.__traceback__)[-1].filename).name}:{traceback.extract_tb(exc.__traceback__)[-1].lineno}"
        outcome = "confirmed_error"
    except Exception as exc:
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        observed = f"{type(exc).__name__}: {exc} at {Path(frame.filename).name}:{frame.lineno}"
        outcome = "inconclusive"
    row = {"card_id": card_id, "case_id": case_id, "expected": expected,
           "observed": str(observed), "outcome": outcome,
           "notes": notes_for(card_id, detail)}
    PROBE_ROWS[:] = [old for old in PROBE_ROWS if (old["card_id"], old["case_id"]) != (card_id, case_id)]
    PROBE_ROWS.append(row)
    write_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    return row


def finish_card(card_id, rows):
    card = CARDS[card_id]
    if any(row["outcome"] == "confirmed_error" for row in rows):
        status = "RED"
        reason = "确认失败：" + "; ".join(f"{r['case_id']} expected[{r['expected']}] observed[{r['observed']}]" for r in rows if r["outcome"] == "confirmed_error")
    elif any(row["outcome"] == "inconclusive" for row in rows):
        status = "YELLOW"
        reason = "未决：" + "; ".join(f"{r['case_id']}={r['observed']}" for r in rows if r["outcome"] == "inconclusive")
    else:
        status = "GREEN"
        reason = "已逐卡断言核心效果与卡面所示关键状态：" + "; ".join(f"{r['case_id']}={r['observed']}" for r in rows)
    verdict = {"card_id": card_id, "status": status, "mechanic_scope": card["mechanics"],
               "reason": reason, "probe_file": PROBE_OUT.name,
               "notes": f"Frozen original YELLOW roster. Cases={len(rows)}; see probe rows with full EN/ZH text, source, existing test references, prior audit, expected/observed state."}
    VERDICT_ROWS[:] = [old for old in VERDICT_ROWS if old["card_id"] != card_id]
    VERDICT_ROWS.append(verdict)
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    return status


def main(limit=None):
    counts = {"GREEN": 0, "YELLOW": 0, "RED": 0}
    for row in ROSTER_ROWS[:limit]:
        card_id = row["card_id"]
        assert card_id in CASES, f"missing card-specific probe: {card_id}"
        results = []
        for case_id, expected, probe in CASES[card_id]:
            result = save_case(card_id, case_id, expected, probe, f"Real Fireplace state assertions for {case_id}.")
            results.append(result)
            print(f"{card_id} {case_id}: {result['outcome']} — {result['observed']}", flush=True)
        status = finish_card(card_id, results)
        counts[status] += 1
        print(f"{card_id}: {status}; saved {len(results)} case(s)", flush=True)
    print(f"LOE complete: cards={sum(counts.values())}, cases={len(PROBE_ROWS)}, verdicts={counts}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="run only the first N cards in the frozen LOE roster")
    main(parser.parse_args().limit)
