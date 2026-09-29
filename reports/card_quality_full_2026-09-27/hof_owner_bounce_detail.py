#!/usr/bin/env python3
"""Vanish ownership and Mind Control Tech board-capacity regression cases."""

from hearthstone.enums import CardClass, Zone
from utils import WISP

from hof_probe import fresh_game, record_case, record_verdict


def main():
    game = fresh_game(CardClass.ROGUE, CardClass.ROGUE)
    caster, original_owner = game.player1, game.player2
    victim = original_owner.summon(WISP)
    caster.steal(victim)
    assert victim.zone == Zone.PLAY and victim.controller is caster
    spell = caster.give("NEW1_004")
    spell.play()
    observed = (f"caster={caster.name};original_owner={original_owner.name};"
                f"stolen_victim={victim.zone.name}:{victim.controller.name};"
                f"in_original_owner_hand={victim in original_owner.hand};"
                f"in_caster_hand={victim in caster.hand};spell={spell.zone.name}")
    expected = "A stolen minion returns to its original owner's hand after Vanish."
    correct = (victim.zone == Zone.HAND and victim in original_owner.hand
               and victim.controller is original_owner and victim not in caster.hand
               and spell.zone == Zone.GRAVEYARD)
    record_case("NEW1_004", "stolen_minion_returns_original_owner", expected,
                observed, "pass" if correct else "confirmed_error",
                "CardDefs.xml enUS: Return all minions to their owner's hand; zhCN: 将所有随从移回其拥有者的手牌。 Source: fireplace/actions.py Bounce.do uses target.controller.hand.")
    record_verdict("NEW1_004", "GREEN" if correct else "RED", "Spell resolution",
                   "消失作用于被偷取的随从时，实际回到当前控制者手牌，违反回到原拥有者手牌的文案。" if not correct else "包括被偷取随从的回手分支通过。",
                   "原双方普通随从回手分支已通过；额外执行拥有者与当前控制者不同的对照。")
    print(f"NEW1_004 {'GREEN' if correct else 'RED'}: {observed}")

    board_game = fresh_game(CardClass.MAGE, CardClass.MAGE)
    owner, opponent = board_game.player1, board_game.player2
    for _ in range(6):
        owner.summon(WISP)
    for _ in range(4):
        opponent.summon(WISP)
    tech = owner.give("EX1_085")
    tech.play()
    board_observed = (f"owner_field={len(owner.field)};opponent_field={len(opponent.field)};"
                      f"tech={tech.zone.name};owner_board={[card.id for card in owner.field]}")
    board_correct = len(owner.field) <= 7 and len(opponent.field) <= 7 and tech.zone == Zone.PLAY
    record_case("EX1_085", "steal_when_battlecry_fills_own_board",
                "With six existing friendly minions, Mind Control Tech fills the seventh slot and must not steal an eighth minion.",
                board_observed, "pass" if board_correct else "confirmed_error",
                "Text: If your opponent has 4 or more minions, take control of one at random. Source: fireplace/actions.py Steal.do lacks target controller board-capacity check.")
    record_verdict("EX1_085", "GREEN" if board_correct else "RED", "Battlecry|Random effects",
                   "己方已有6个随从时，精神控制技师入场占满第7格，战吼仍夺取敌方随从，使己方场面达到8个。" if not board_correct else "四敌方候选随机范围与己方满场分支均通过。",
                   "三敌方不触发、四敌方随机候选均已通过；额外实测己方满场后的夺取。")
    print(f"EX1_085 {'GREEN' if board_correct else 'RED'}: {board_observed}")


if __name__ == "__main__":
    main()
