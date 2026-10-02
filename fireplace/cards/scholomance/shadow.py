"""Scholomance Academy Shadow cards.

The scripts in this module describe the launch (18.0.0.54613) behaviour of
the Priest, Warlock, Demon Hunter and dual-class cards assigned to the Shadow
group.  The XML overlay owns the printed metadata; this file only supplies
runtime behaviour and the related launch-era enchantments and tokens.
"""

from ..utils import *


SOUL_FRAGMENT = FRIENDLY_DECK + ID("SCH_307t")


class CastSpellOnSelfIfPossible(CastSpell):
    """Cast a spell from a deck, preferring the Spellburst minion as target."""

    def choose_target(self, source, card):
        if source in card.targets:
            return source
        return super().choose_target(source, card)


class CycleOfHatred(GameAction):
    """Damage every minion, then summon one Spirit for each resulting death."""

    def do(self, source):
        victims = tuple(ALL_MINIONS.eval(source.game, source))
        history_start = len(source.game.death_history)
        source.game.queue_actions(source, [Hit(ALL_MINIONS, 3), Deaths()])
        dead_ids = {
            card.entity_id for card in source.game.death_history[history_start:]
        }
        killed = sum(card.entity_id in dead_ids for card in victims)
        if killed:
            source.game.queue_actions(
                source, [Summon(CONTROLLER, "SCH_253t") * killed]
            )


class GlideAction(GameAction):
    """Shuffle the caster's hand, then draw four cards."""

    def do(self, source):
        source.game.queue_actions(
            source,
            [Shuffle(CONTROLLER, FRIENDLY_HAND), Draw(CONTROLLER) * 4],
        )


class StelinaChoice(Choice):
    """Choose one of the three opponent cards to shuffle away."""

    def choose(self, card):
        super().choose(card)
        if card.zone == Zone.HAND:
            self.source.game.queue_actions(
                self.source,
                [Shuffle(self.source.controller.opponent, card)],
            )


class StelinaLookAt(GameAction):
    def do(self, source):
        opponent = source.controller.opponent
        cards = list(opponent.hand)
        if not cards:
            return
        cards = source.game.random.sample(cards, min(3, len(cards)))
        StelinaChoice(CONTROLLER, cards).trigger(source)


class FelosophyCopy(GameAction):
    """Copy the lowest-cost Demon in hand and optionally buff both copies."""

    def do(self, source):
        demons = [card for card in source.controller.hand
                  if card.type == CardType.MINION and Race.DEMON in card.races]
        if not demons:
            return
        lowest = min(card.cost for card in demons)
        choices = [card for card in demons if card.cost == lowest]
        original = source.game.random.choice(choices)
        # Felosophy creates an exact copy, including any buffs already on the
        # lowest-cost Demon in hand.  The outcast enchantment is then applied
        # to both the original and that copied state.
        copied = ExactCopy(SELF).copy(source, original)
        source.game.queue_actions(source, [Give(CONTROLLER, copied)])
        if source.play_outcast and copied.zone == Zone.HAND:
            source.game.queue_actions(
                source,
                [Buff(original, "SCH_702e"), Buff(copied, "SCH_702e")],
            )


class InitiationAction(GameAction):
    """Deal four damage and copy a minion only when that damage kills it."""

    def do(self, source):
        target = source.target
        if target is None:
            return
        history_start = len(source.game.death_history)
        source.game.queue_actions(source, [Hit(target, 4), Deaths()])
        killed = any(
            card.entity_id == target.entity_id
            for card in source.game.death_history[history_start:]
        )
        if killed:
            # Initiation summons a fresh printed copy.  Damage, silence and
            # temporary buffs on the destroyed minion do not carry over.
            source.game.queue_actions(source, [Summon(CONTROLLER, target.id)])


class SwapIlluciaHandsAndDecks(GameAction):
    """Temporarily exchange the two players' hands and decks.

    The launch card restored the original ownership at the controller's next
    turn.  Swapping the containers keeps order and card identity intact while
    updating each card's controller so selectors and draw effects follow the
    temporary owner.
    """

    @staticmethod
    def _swap(first, second):
        first.hand, second.hand = second.hand, first.hand
        first.deck, second.deck = second.deck, first.deck
        for owner in (first, second):
            for card in owner.hand + owner.deck:
                card.controller = owner

    def do(self, source):
        first = source.controller
        second = first.opponent
        self._swap(first, second)

        # ``Action.matches`` treats callable arguments as predicates; a Player
        # instance itself is not a selector and cannot be passed directly.
        listener = BeginTurn(lambda player: player is first).on(
            RestoreIlluciaHandsAndDecks(first, second)
        )
        listener.once = True
        first._events.append(listener)


class RestoreIlluciaHandsAndDecks(GameAction):
    def __init__(self, first, second):
        super().__init__()
        self.first = first
        self.second = second

    def do(self, source):
        # Each cast owns an independent listener.  This also handles a second
        # Illucia cast during the temporary exchange without suppressing it.
        SwapIlluciaHandsAndDecks._swap(self.first, self.second)


class SCH_120:
    spellburst = Steal(RANDOM(ENEMY_MINIONS + (ATK <= 2)))


class GandlingPlay(GameAction):
    def do(self, source):
        # The played minion is still pending destruction until Deaths() runs;
        # process that batch before attempting to summon the replacement.
        card = source.event_args[1] if source.event_args else None
        if card is None or card.zone != Zone.PLAY:
            return
        source.game.queue_actions(
            source,
            [Destroy(card), Deaths(), Summon(CONTROLLER, "SCH_126t")],
        )


class SCH_126:
    events = Play(CONTROLLER, MINION).after(GandlingPlay())


class SCH_135:
    events = Attack(SELF, MINION).on(Buff(Attack.DEFENDER, "SCH_135e"))


class SCH_135e:
    atk = SET(3)
    max_health = SET(3)


class SCH_136:
    requirements = {PlayReq.REQ_TARGET_TO_PLAY: 0, PlayReq.REQ_MINION_TARGET: 0}
    play = Buff(TARGET, "SCH_136e"), Buff(TARGET, "SCH_136e2")


class SCH_136e:
    tags = {GameTag.ATK: 2, GameTag.HEALTH: 2}


class SCH_136e2:
    # FullHeal delegates through its source card's ``heal`` convenience
    # method, which enchantments do not expose.  Healing exactly the owner's
    # current damage has the same result and keeps the action source valid.
    events = OWN_TURN_END.on(Heal(OWNER, DAMAGE(OWNER)), Destroy(SELF))


class SCH_137:
    # The XML carries no script for this vanilla minion, but its printed 1
    # Attack must still be explicit so the script layer is self-contained.
    tags = {GameTag.ATK: 1}


class SCH_138:
    requirements = {PlayReq.REQ_TARGET_TO_PLAY: 0, PlayReq.REQ_MINION_TARGET: 0}
    play = Buff(TARGET, "SCH_138e"), Buff(TARGET, "SCH_138e2")


class SCH_138e:
    tags = {GameTag.ATK: 8, GameTag.HEALTH: 8}


class SCH_138e2:
    tags = {GameTag.CANNOT_ATTACK_HEROES: True}


class SCH_139:
    cost_mod = -Count(CARDS_PLAYED_THIS_GAME + SPELL + CAST_ON_FRIENDLY_CHARACTERS)


class SCH_140:
    cost_mod = -Attr(CONTROLLER, "hero_health_changes_on_own_turn")


class SCH_141:
    spellburst = CastSpellOnSelfIfPossible(RANDOM(FRIENDLY_DECK + SPELL))


class SCH_147:
    deathrattle = Summon(CONTROLLER, "SCH_147t") * 2
    discard = deathrattle


class SCH_149:
    play = Buff(SELF, "SCH_149e")


class SCH_149e:
    def apply(self, target):
        board = target.game.board
        if board:
            self._xatk = max(card.atk for card in board)
            self._xhealth = max(card.health for card in board)

    atk = lambda self, _: getattr(self, "_xatk", 0)
    max_health = lambda self, _: getattr(self, "_xhealth", 0)


class SCH_158:
    play = Buff(CONTROLLER, "SCH_158e"), DISCOVER(RandomDemon())


class SCH_158e:
    update = Refresh(FRIENDLY_HAND + DEMON, {GameTag.COST: -1})
    events = Play(CONTROLLER, DEMON).on(Destroy(SELF))


class SCH_158e2:
    tags = {GameTag.COST: -1}
    events = REMOVED_IN_PLAY


class SCH_159:
    play = SwapIlluciaHandsAndDecks()


class SCH_181:
    play = (
        Summon(CONTROLLER, RANDOM(FRIENDLY_HAND + DEMON)),
        Summon(CONTROLLER, RANDOM(FRIENDLY_DECK + DEMON)),
    )


class SCH_233:
    play = Buff(CONTROLLER, "SCH_233e"), DISCOVER(RandomDragon())


class SCH_233e:
    update = Refresh(FRIENDLY_HAND + DRAGON, {GameTag.COST: -1})
    events = Play(CONTROLLER, DRAGON).on(Destroy(SELF))


class SCH_233e2:
    tags = {GameTag.COST: -1}
    events = REMOVED_IN_PLAY


class SCH_247:
    play = Give(CONTROLLER, RandomMinion(cost=1)) * 2


class SCH_250:
    play = Buff(ENEMY_MINIONS, "SCH_250e")


class SCH_250e:
    atk = SET(1)
    events = EndTurn(OWNER_CONTROLLER).on(Destroy(SELF))


class SCH_252:
    play = Shuffle(CONTROLLER, "SCH_307t") * 2


class SCH_253:
    play = CycleOfHatred()


class SCH_276:
    events = Attack(SELF, MINION).on(Silence(Attack.DEFENDER))


class SCH_302:
    requirements = {PlayReq.REQ_TARGET_TO_PLAY: 0, PlayReq.REQ_MINION_TARGET: 0}
    play = GiveDivineShield(TARGET), Summon(CONTROLLER, ExactCopy(TARGET)).then(
        Buff(Summon.CARD, "SCH_302e")
    )


class SCH_302e:
    atk = SET(1)
    max_health = SET(1)


class SCH_307:
    play = Hit(ALL_MINIONS, 2), Shuffle(CONTROLLER, "SCH_307t") * 2


class SCH_307t:
    # Destroy the drawn fragment first, heal, and then draw its replacement.
    draw = Destroy(SELF), Heal(FRIENDLY_HERO, 2), Draw(CONTROLLER)


class SCH_343:
    play = Find(SOUL_FRAGMENT) & (
        Destroy(RANDOM(SOUL_FRAGMENT)), Buff(SELF, "SCH_343e")
    )


class SCH_343e:
    tags = {GameTag.ATK: 3, GameTag.HEALTH: 3}


class AncientVoidHoundEnd(GameAction):
    """Steal independently available Attack and Health from each enemy.

    A one-health minion may die when its Health is reduced.  Snapshotting the
    enemy list and the available stats before applying any enchantments keeps
    that death from changing the amount the Hound gains.
    """

    def do(self, source):
        enemies = tuple(ENEMY_MINIONS.eval(source.game, source))
        attack_gain = sum(card.atk > 0 for card in enemies)
        health_gain = sum(card.max_health > 0 for card in enemies)
        actions = []
        for card in enemies:
            if card.atk > 0:
                actions.append(Buff(card, "SCH_354ea"))
            if card.max_health > 0:
                actions.append(Buff(card, "SCH_354eb"))
        actions.extend(Buff(source, "SCH_354e2a") for _ in range(attack_gain))
        actions.extend(Buff(source, "SCH_354e2b") for _ in range(health_gain))
        if actions:
            source.game.queue_actions(source, actions)


class SCH_354:
    events = OWN_TURN_END.on(AncientVoidHoundEnd())


class SCH_354e:
    tags = {GameTag.ATK: -1, GameTag.HEALTH: -1}


class SCH_354e2:
    tags = {GameTag.ATK: 1, GameTag.HEALTH: 1}


class SCH_354e2a:
    tags = {GameTag.ATK: 1}


class SCH_354e2b:
    tags = {GameTag.HEALTH: 1}


class SCH_354ea:
    tags = {GameTag.ATK: -1}


class SCH_354eb:
    tags = {GameTag.HEALTH: -1}


class SCH_355:
    play = Find(SOUL_FRAGMENT) & (
        Destroy(RANDOM(SOUL_FRAGMENT)), Hit(ALL_MINIONS - SELF, 3)
    )


class SCH_356:
    play = GlideAction()
    outcast = (
        GlideAction(),
        Shuffle(OPPONENT, ENEMY_HAND),
        Draw(OPPONENT) * 4,
    )


class SCH_357:
    class Hand:
        events = Death(FRIENDLY_MINIONS).on(Buff(SELF, "SCH_357e"))

    play = Summon(CONTROLLER, "SCH_357t") * 3


class SCH_357e:
    tags = {GameTag.COST: -1}
    events = REMOVED_IN_PLAY


class SCH_422:
    play = ForceDraw(RANDOM(FRIENDLY_DECK + FilterSelector(
        lambda card, source: bool(
            card.tags.get(GameTag.OUTCAST)
            or (
                getattr(getattr(card, "data", None), "tags", {}).get(
                    GameTag.OUTCAST
                )
            )
        )
    )))


class SCH_512:
    requirements = {PlayReq.REQ_TARGET_TO_PLAY: 0, PlayReq.REQ_MINION_TARGET: 0}
    play = InitiationAction()


class SCH_513:
    requirements = {
        PlayReq.REQ_MINION_TARGET: 0,
        PlayReq.REQ_TARGET_IF_AVAILABLE_AND_PLAYER_HEALTH_CHANGED_THIS_TURN: 0,
    }
    play = Destroy(TARGET)


class RaiseDeadAction(GameAction):
    """Return two random friendly minions from the game's death history."""

    def do(self, source):
        dead = [
            card
            for card in source.game.death_history
            if card.type == CardType.MINION and card.controller is source.controller
        ]
        if not dead:
            return
        selected = source.game.random.sample(dead, min(2, len(dead)))
        actions = [
            Give(CONTROLLER, Copy(SELF).copy(source, card))
            for card in selected
        ]
        source.game.queue_actions(source, actions)


class SCH_514:
    play = Hit(FRIENDLY_HERO, 3), RaiseDeadAction()


class SCH_517:
    requirements = {
        PlayReq.REQ_TARGET_IF_AVAILABLE_AND_SOUL_FRAGMENT_IN_DECK: 0,
    }
    play = Find(SOUL_FRAGMENT) & (
        Destroy(RANDOM(SOUL_FRAGMENT)), Hit(TARGET, 3)
    )


class SCH_532:
    spellburst = GiveDivineShield(SELF)


class SCH_603:
    outcast = StelinaLookAt()


class SCH_700:
    play = Shuffle(CONTROLLER, "SCH_307t") * 2


class SCH_701:
    requirements = {PlayReq.REQ_TARGET_TO_PLAY: 0, PlayReq.REQ_MINION_TARGET: 0}
    play = (
        Hit(TARGET, 3),
        Shuffle(CONTROLLER, "SCH_307t") * 2,
    )


class SCH_702:
    play = FelosophyCopy()


class SCH_702e:
    tags = {GameTag.ATK: 1, GameTag.HEALTH: 1}


class SCH_703:
    play = Summon(CONTROLLER, "SCH_703t") * Count(SOUL_FRAGMENT)


class SCH_704:
    play = Find(SOUL_FRAGMENT) & (
        Destroy(RANDOM(SOUL_FRAGMENT)), Buff(FRIENDLY_HERO, "SCH_704e")
    )


class SCH_704e:
    tags = {GameTag.ATK: 5, GameTag.TAG_ONE_TURN_EFFECT: True}


class SCH_705:
    outcast = Summon(CONTROLLER, "SCH_705t") * 2


class SCH_712:
    tags = {GameTag.LIFESTEAL: True}
