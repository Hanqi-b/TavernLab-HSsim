"""Scholomance Academy neutral cards, using the 18.0 launch rules."""
from ..utils import *


class SCH_142:
    events = OWN_TURN_END.on(DrawUntil(CONTROLLER, 3))


class SCH_143:
    tags = {GameTag.DIVINE_SHIELD: True}


class SCH_145:
    tags = {GameTag.ATK: 1}


class SCH_146:
    update = Refresh(FRIENDLY_MINIONS, buff="SCH_146e")


SCH_146e = buff(cant_be_targeted_by_spells=True, cant_be_targeted_by_hero_powers=True)


class SCH_157:
    def spellburst(self):
        yield CastSpell(RandomSpell(cost=self.spellburst_cost))


class SCH_160:
    play = Give(CONTROLLER, RandomSpell(card_class=FRIENDLY_CLASS, cost=1))


class VectusWhelps(GameAction):
    def do(self, source):
        dead = [c for c in source.game.death_history
                if c.controller is source.controller and c.has_deathrattle]
        for _ in range(2):
            if len(source.controller.field) >= source.game.MAX_MINIONS_ON_FIELD:
                break
            whelp = source.controller.card("SCH_162t", source)
            source.game.queue_actions(source, [Summon(CONTROLLER, whelp)])
            if dead:
                donor = source.game.random.choice(dead)
                source.game.queue_actions(whelp, [CopyDeathrattleBuff(donor, "SCH_162e")])


class SCH_162:
    play = VectusWhelps()


class SCH_162e:
    tags = {GameTag.DEATHRATTLE: True}


class SCH_224:
    def spellburst(self):
        for minion in self.spellburst_deaths:
            yield Summon(CONTROLLER, minion.id)


class SCH_230:
    spellburst = Give(CONTROLLER, RandomSpell(card_class=FRIENDLY_CLASS)) * 2


class SCH_231:
    spellburst = Buff(SELF, "SCH_231e")


SCH_231e = buff(atk=2)


class SCH_232:
    spellburst = Buff(SELF, "SCH_232e")


SCH_232e = buff(atk=1, taunt=True)


class SCH_245:
    play = DISCOVER(RandomSpell())


class SCH_248:
    requirements = {PlayReq.REQ_TARGET_IF_AVAILABLE: 0}
    play = Hit(TARGET, 1)
    spellburst = Bounce(SELF)


class SphereChoice(Choice):
    def choose(self, card):
        if card not in self.cards:
            from ...exceptions import InvalidAction
            raise InvalidAction("Invalid Sphere of Sapience choice")
        top = self.cards[0]
        if card.id == "SCH_259t" and top in self.player.deck:
            self.player.deck.remove(top)
            self.player.deck.insert(0, top)
            self.source.damage += 1
        # Resolve movement before turn-start continuation performs the draw.
        super().choose(card)


class LookAtTop(GameAction):
    def do(self, source):
        if not source.controller.deck:
            return
        top = source.controller.deck[-1]
        alternative = source.controller.card("SCH_259t", source)
        choice = SphereChoice(CONTROLLER, [top, alternative])
        choice.trigger(source)


class SCH_259:
    events = OWN_TURN_BEGIN.on(LookAtTop())


class SCH_283:
    def play(self):
        if self.controller.hero.power.activations_this_turn:
            yield Draw(CONTROLLER)


class SCH_311:
    play = GiveRush(FRIENDLY_MINIONS - SELF)


class SCH_312:
    play = Buff(CONTROLLER, "SCH_312e")


class SCH_312e:
    update = Refresh(FRIENDLY_HERO_POWER, {GameTag.COST: SET(0)})
    events = Activate(CONTROLLER).on(Destroy(SELF))


class SCH_313:
    spellburst = Hit(ALL_MINIONS - SELF, 2)


class OrderDeck(GameAction):
    def do(self, source):
        # The top of a Fireplace deck is its last element. Randomize ties.
        source.game.random.shuffle(source.controller.deck)
        source.controller.deck.sort(key=lambda card: card.cost)


class SCH_428:
    play = OrderDeck()


class SCH_530:
    def play(self):
        if self.controller.spellpower:
            yield Summon(CONTROLLER, ExactCopy(SELF))


class SCH_605:
    events = Attack(SELF).on(CLEAVE)


class SCH_707:
    deathrattle = Give(CONTROLLER, "SCH_707t")


class SCH_708:
    deathrattle = Give(CONTROLLER, "SCH_708t")


class SCH_709:
    deathrattle = Give(CONTROLLER, "SCH_709t")


class SCH_710:
    events = Play(OPPONENT, SPELL).on(Summon(CONTROLLER, "SCH_710t"))


class SCH_711:
    deathrattle = Summon(CONTROLLER, RandomMinion(cost=7))


class SCH_713:
    play = Buff(OPPONENT, "SCH_713e")


class SCH_713e:
    update = Refresh(ENEMY_HAND + SPELL, {GameTag.COST: 1})
    events = EndTurn(OWNER_CONTROLLER).on(Destroy(SELF))


class SCH_714:
    events = Play(ALL_PLAYERS, SPELL).on(
        StoringBuff(SELF, "SCH_714e", Play.CARD)
    )
    def deathrattle(self):
        for enchantment in self.buffs:
            if enchantment.id == "SCH_714e":
                yield Shuffle(CONTROLLER, enchantment.store_card.id)


class SCH_714e:
    tags = {}


@custom_card
class FIREPLACE_SCH_717e:
    tags = {GameTag.CARDNAME: "Alabaster's Copy", GameTag.CARDTYPE: CardType.ENCHANTMENT}
    cost = SET(1)


class SCH_717:
    events = Draw(OPPONENT).on(
        Give(CONTROLLER, Copy(Draw.CARD)).then(Buff(Give.CARD, "FIREPLACE_SCH_717e"))
    )
