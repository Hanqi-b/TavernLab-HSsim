"""Scholomance Academy Druid, Hunter, and Shaman cards.

The card data in this repository is pinned to the Scholomance launch set.  The
scripts below intentionally follow that snapshot rather than later balance
changes.
"""

from hearthstone.enums import CardType, GameTag, Race, Zone

from ..utils import *


class MoltenBlast(TargetedAction):
    """Deal Molten Blast's spell-powered damage and summon that many Elementals."""

    TARGET = ActionArg()

    def do(self, source, target):
        # Hit returns the damage that actually got through shields and
        # immunity.  Molten Blast summons exactly that many Elementals.
        result = source.game.queue_actions(source, [Hit(target, 2)])
        amount = result[0][0] if result and result[0] else 0
        if amount:
            source.game.queue_actions(
                source, [Summon(CONTROLLER, "SCH_271t") * amount]
            )


class TrueaimCrescentAttack(TargetedAction):
    """Make every friendly minion that can attack strike the attacked minion."""

    TARGET = ActionArg()

    def do(self, source, target):
        if not target or target.zone != Zone.PLAY:
            return
        for minion in list(source.controller.field):
            # The target can die during an earlier forced attack.  Attack()
            # does not validate a stale defender, so stop before it can hit a
            # graveyard entity.
            if target.zone != Zone.PLAY or target.dead:
                break
            # This is a forced attack.  It may use an exhausted or sleeping
            # minion, and forced attacks bypass frozen/can't-attack flags.
            if (
                minion.zone == Zone.PLAY
                and minion.atk > 0
                and not minion.dormant
            ):
                source.game.queue_actions(source, [Attack(minion, target)])


class RememberFireheartSpell(TargetedAction):
    """Remember the spell selected by Instructor Fireheart's Discover."""

    TARGET = ActionArg()

    def do(self, source, target):
        player = source if source.type == CardType.PLAYER else source.controller
        pending = getattr(player, "_fireheart_spells", None)
        if pending is None:
            pending = player._fireheart_spells = []
        pending.append(target)

        # Fireheart's repeat belongs to the player for the rest of the turn,
        # so it survives the minion leaving play after the first Discover.
        repeat = RepeatFireheart(Play.CARD)
        repeat._fireheart_spell = target
        listener = Play(CONTROLLER, SPELL).after(repeat)
        listener._fireheart_listener = True
        listener._fireheart_spell = target
        end_turn = OWN_TURN_END.on(ClearFireheartSpell())
        end_turn._fireheart_listener = True
        player._events.extend((listener, end_turn))


class RepeatFireheart(TargetedAction):
    """Repeat Fireheart only when the selected spell was actually played."""

    TARGET = ActionArg()

    def do(self, source, target):
        player = source if source.type == CardType.PLAYER else source.controller
        pending = getattr(player, "_fireheart_spells", None)
        if not pending or self._fireheart_spell is not target:
            return
        try:
            pending.remove(target)
        except ValueError:
            return
        for event in list(player._events):
            if getattr(event, "_fireheart_spell", None) is target:
                player._events.remove(event)
        player.game.queue_actions(player, [FireheartDiscover()])


class ClearFireheartSpell(GameAction):
    def do(self, source):
        player = source if source.type == CardType.PLAYER else source.controller
        player._fireheart_spells = []
        for event in list(player._events):
            if getattr(event, "_fireheart_listener", False):
                player._events.remove(event)


def FireheartDiscover():
    """Discover and hand over a spell that costs at least one."""

    return Discover(CONTROLLER, RandomSpell(cost=range(1, 11))).then(
        Give(CONTROLLER, Discover.CARD),
        RememberFireheartSpell(Discover.CARD),
    )


class SCH_133:
    """Wolpertinger"""

    play = Summon(CONTROLLER, ExactCopy(SELF))


class SCH_182:
    """Speaker Gidra"""

    def spellburst(self):
        yield Buff(
            SELF,
            "SCH_182e",
            atk=self.spellburst_cost,
            max_health=self.spellburst_cost,
        )


class SCH_236:
    """Diligent Notetaker"""

    def spellburst(self):
        yield Bounce(self.spellburst_spell)


class SCH_239:
    """Krolusk Barkstripper"""

    spellburst = Destroy(RANDOM_ENEMY_MINION)


class SCH_242:
    """Gibberling"""

    spellburst = Summon(CONTROLLER, "SCH_242")


class SCH_244:
    """Teacher's Pet"""

    deathrattle = Summon(CONTROLLER, RandomBeast(cost=3))


class SCH_271:
    """Molten Blast"""

    requirements = {PlayReq.REQ_TARGET_TO_PLAY: 0}
    play = MoltenBlast(TARGET)


class SCH_279:
    """Trueaim Crescent"""

    events = Attack(FRIENDLY_HERO, MINION).after(
        TrueaimCrescentAttack(Attack.DEFENDER)
    )


class SCH_300:
    """Carrion Studies"""

    play = Discover(CONTROLLER, RandomMinion(deathrattle=True)).then(
        Give(CONTROLLER, Discover.CARD),
        Buff(CONTROLLER, "SCH_300e"),
    )


class SCH_300e:
    update = Refresh(FRIENDLY_HAND + MINION + DEATHRATTLE, {GameTag.COST: -1})
    events = Play(CONTROLLER, MINION + DEATHRATTLE).on(Destroy(SELF))


class SCH_301:
    """Rune Dagger"""

    events = Attack(FRIENDLY_HERO).after(Buff(CONTROLLER, "SCH_301e"))


class SCH_301e:
    tags = {GameTag.TAG_ONE_TURN_EFFECT: True}
    update = Refresh(CONTROLLER, {GameTag.SPELLPOWER: 1})


class SCH_333:
    """Nature Studies"""

    play = Discover(CONTROLLER, RandomSpell()).then(
        Give(CONTROLLER, Discover.CARD),
        Buff(CONTROLLER, "SCH_333e"),
    )


class SCH_333e:
    update = Refresh(FRIENDLY_HAND + SPELL, {GameTag.COST: -1})
    events = Play(CONTROLLER, SPELL).on(Destroy(SELF))


class SCH_340:
    """Bloated Python"""

    deathrattle = Summon(CONTROLLER, "SCH_340t")


class SCH_427:
    """Lightning Bloom"""

    play = ManaThisTurn(CONTROLLER, 2)


class SCH_507:
    """Instructor Fireheart"""

    play = FireheartDiscover()
    events = ()


class SCH_535:
    """Tidal Wave"""

    play = Hit(ALL_MINIONS, 3)


class SCH_538:
    """Ace Hunter Kreen"""

    update = Refresh(
        FRIENDLY_CHARACTERS - SELF,
        {GameTag.IMMUNE_WHILE_ATTACKING: True},
    )


class SCH_539:
    """Professor Slate"""

    poisonous_spells = True


class SCH_600:
    """Demon Companion"""

    play = Summon(CONTROLLER, RandomID("SCH_600t1", "SCH_600t2", "SCH_600t3"))


class SCH_600t3:
    update = Refresh(FRIENDLY_MINIONS - SELF, {GameTag.ATK: 1})


class SCH_604:
    """Overwhelm"""

    requirements = {
        PlayReq.REQ_TARGET_TO_PLAY: 0,
        PlayReq.REQ_MINION_TARGET: 0,
    }
    play = Hit(TARGET, Count(FRIENDLY_MINIONS + BEAST) + 2)


class SCH_606:
    """Partner Assignment"""

    play = Give(CONTROLLER, RandomBeast(cost=2)), Give(
        CONTROLLER, RandomBeast(cost=3)
    )


class SCH_607:
    """Shan'do Wildclaw"""

    choose = ("SCH_607a", "SCH_607b")


class SCH_607a:
    requirements = {
        PlayReq.REQ_TARGET_TO_PLAY: 0,
        PlayReq.REQ_MINION_TARGET: 0,
        PlayReq.REQ_FRIENDLY_TARGET: 0,
        PlayReq.REQ_TARGET_WITH_RACE: Race.BEAST,
    }
    play = Morph(SELF, ExactCopy(TARGET))


class SCH_607b:
    play = Buff(FRIENDLY_DECK + BEAST, "SCH_607e")


SCH_607e = buff(atk=1, health=1)


class SCH_609:
    """Survival of the Fittest"""

    play = Buff(
        (FRIENDLY_HAND + MINION)
        | (FRIENDLY_DECK + MINION)
        | FRIENDLY_MINIONS,
        "SCH_609e",
    )


SCH_609e = buff(atk=4, health=4)


class SCH_610:
    """Guardian Animals"""

    play = (
        Summon(CONTROLLER, RANDOM(FRIENDLY_DECK + BEAST + (COST <= 5))).then(
            GiveRush(Summon.CARD)
        )
        * 2
    )


class SCH_612:
    """Runic Carvings"""

    choose = ("SCH_612a", "SCH_612b")


class SCH_612a:
    play = Summon(CONTROLLER, "SCH_612t") * 4


class SCH_612b:
    play = (
        Summon(CONTROLLER, "SCH_612t").then(GiveRush(Summon.CARD))
        * 4
    )


class SCH_613:
    """Groundskeeper"""

    powered_up = Find(FRIENDLY_HAND + SPELL + (COST >= 5))
    play = powered_up & Heal(FRIENDLY_HERO, 5)


class SCH_614:
    """Forest Warden Omu"""

    spellburst = FillMana(CONTROLLER, USED_MANA(CONTROLLER))


class SCH_615:
    """Totem Goliath"""

    deathrattle = Summon(CONTROLLER, BASIC_TOTEMS)


class SCH_616:
    """Twilight Runner"""

    events = Attack(SELF).after(Draw(CONTROLLER) * 2)


class SCH_617:
    """Adorable Infestation"""

    requirements = {
        PlayReq.REQ_TARGET_TO_PLAY: 0,
        PlayReq.REQ_MINION_TARGET: 0,
    }
    play = (
        Buff(TARGET, "SCH_617e"),
        Summon(CONTROLLER, "SCH_617t").then(Give(CONTROLLER, "SCH_617t")),
    )


SCH_617e = buff(atk=1, health=1)


class SCH_618:
    """Blood Herald"""

    class Hand:
        events = Death(FRIENDLY + MINION).on(Buff(SELF, "SCH_618e"))


SCH_618e = buff(atk=1, health=1)
