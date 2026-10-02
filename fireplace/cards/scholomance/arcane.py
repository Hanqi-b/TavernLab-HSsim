"""Mage, Rogue, Warrior and their remaining dual-class launch cards."""
from ..utils import *


class SCH_234:
    spellburst = Give(CONTROLLER, RandomCollectible(combo=True))


class DevolveMissile(GameAction):
    def do(self, source):
        enemies = [m for m in source.controller.opponent.field if not m.dormant]
        if not enemies:
            return
        target = source.game.random.choice(enemies)
        ids = RandomMinion(cost=target.cost - 1).evaluate(source)
        if ids:
            source.game.queue_actions(source, [Morph(target, ids[0])])


class SCH_235:
    play = DevolveMissile(), DevolveMissile(), DevolveMissile()


class SCH_237:
    play = Buff(CONTROLLER, "SCH_237e"), DISCOVER(RandomMinion(rush=True))


class SCH_237e:
    update = Refresh(FRIENDLY_HAND + MINION + RUSH, {GameTag.COST: -1})
    events = Play(CONTROLLER, MINION + RUSH).on(Destroy(SELF))


class SCH_238:
    spellburst = Buff(SELF, "SCH_238e")


class SCH_238e:
    tags = {GameTag.TAG_ONE_TURN_EFFECT: True}
    events = Attack(FRIENDLY_HERO).on(Hit(ADJACENT(Attack.DEFENDER), ATK(FRIENDLY_HERO)))


class SCH_241:
    spellburst = Hit(RANDOM_ENEMY_MINION, 1) * 4


class SCH_243:
    spellburst = Summon(CONTROLLER, "NEW1_012") * 2


class SpellDamageMinionPicker(RandomCardPicker):
    def find_cards(self, source, **filters):
        from .. import db
        return [cid for cid in super().find_cards(source, **filters) if db[cid].tags.get(GameTag.SPELLPOWER, 0) > 0]


class SCH_270:
    play = Buff(CONTROLLER, "SCH_270e"), DISCOVER(
        SpellDamageMinionPicker(collectible=True, type=CardType.MINION)
    )


class SCH_270e:
    update = Refresh(FRIENDLY_HAND + MINION + SPELLPOWER, {GameTag.COST: -1})
    events = Play(CONTROLLER, MINION + SPELLPOWER).on(Destroy(SELF))


class SCH_273:
    events = OWN_TURN_END.on(Hit(ENEMY_CHARACTERS, SPELL_DAMAGE(1)))


class OpenPassage(GameAction):
    def do(self, source):
        player = source.controller
        original = list(player.hand)
        for card in original:
            card.zone = Zone.SETASIDE
        borrowed = []
        for _ in range(min(5, len(player.deck))):
            card = player.deck[-1]
            card.zone = Zone.HAND  # This is replacement, not a draw.
            borrowed.append(card)
        enchantment = source.buff(player, "SCH_305e3")
        enchantment.passage_original = original
        enchantment.passage_borrowed = borrowed


class ClosePassage(GameAction):
    def do(self, source):
        player = source.owner
        # Nested replacements unwind newest first. Otherwise the earlier
        # borrowed hand is still SETASIDE when its return trigger runs.
        passages = [buff for buff in player.buffs if buff.id == "SCH_305e3"]
        for passage in reversed(passages):
            for card in passage.passage_borrowed:
                if card.zone == Zone.HAND and card.controller is player:
                    source.game.queue_actions(source, [Shuffle(player, card)])
            for card in passage.passage_original:
                if card.zone == Zone.SETASIDE:
                    source.game.queue_actions(source, [Give(player, card)])
            passage.remove()


class SCH_305:
    play = OpenPassage()


class SCH_305e3:
    events = EndTurn(OWNER_CONTROLLER).on(ClosePassage())


class SCH_310:
    tags = {GameTag.SPELLPOWER: 1}


class CopyRush(GameAction):
    def do(self, source, *args):
        played = source.event_args[1]
        if played.zone != Zone.PLAY or played.dead:
            return
        copied = ExactCopy(SELF).copy(source, played)
        copied.damage = max(0, copied.max_health - 1)
        source.game.queue_actions(source, [Summon(CONTROLLER, copied)])


class SCH_317:
    events = Play(CONTROLLER, MINION + RUSH).after(CopyRush())


class SummonAndAttack(GameAction):
    CARD = ActionArg()
    def do(self, source, card_id):
        if not source.controller.minion_slots:
            return
        minion = source.controller.card(card_id, source)
        source.game.queue_actions(source, [Summon(CONTROLLER, minion)])
        enemies = [e for e in source.controller.opponent.characters if not getattr(e, 'dormant', False)]
        if minion.zone == Zone.PLAY and enemies:
            source.game.queue_actions(source, [Attack(minion, source.game.random.choice(enemies))])


class SCH_337:
    events = OWN_TURN_END.on(SummonAndAttack("SCH_337t"), SummonAndAttack("SCH_337t"))


class Combust(GameAction):
    def do(self, source):
        target = source.target
        neighbors = tuple(target.adjacent_minions)
        amount = source.controller.get_spell_damage(4)
        excess = max(0, amount - target.health)
        source.game.queue_actions(source, [Hit(target, amount)])
        # The excess already includes spell damage, do not apply it twice.
        old = source.immune_to_spellpower
        source.immune_to_spellpower = True
        try:
            if excess:
                source.game.queue_actions(source, [Hit(neighbor, excess) for neighbor in neighbors])
        finally:
            source.immune_to_spellpower = old


class SCH_348:
    requirements = {PlayReq.REQ_TARGET_TO_PLAY: 0, PlayReq.REQ_MINION_TARGET: 0}
    play = Combust()


class SCH_350:
    combo = DISCOVER(RandomSpell(card_class=CardClass.MAGE))


class IllusionChoice(Choice):
    def choose(self, card):
        if card not in self.cards:
            from ...exceptions import InvalidAction
            raise InvalidAction("Invalid illusion selection")
        for minion in self.cards:
            enchantment = self.source.buff(minion, "SCH_351e")
            enchantment.store_card = minion is card
        super().choose(card)


class SummonIllusions(GameAction):
    def do(self, source):
        summoned = []
        for _ in range(2):
            if not source.controller.minion_slots:
                break
            ids = RandomMinion(cost=5).evaluate(source)
            if not ids:
                break
            minion = source.controller.card(ids[0], source)
            source.game.queue_actions(source, [Summon(CONTROLLER, minion)])
            if minion.zone == Zone.PLAY:
                summoned.append(minion)
        if summoned:
            IllusionChoice(CONTROLLER, summoned).trigger(source)


def illusion_damage(self, target, amount, damage_source):
    if getattr(self, "store_card", False) and amount:
        return Destroy(OWNER)


class SCH_351:
    play = SummonIllusions()


class SCH_351e:
    events = Damage(OWNER).on(illusion_damage)


class SCH_352:
    play = Give(CONTROLLER, ExactCopy(FRIENDLY_MINIONS)).then(Buff(Give.CARD, "SCH_352e"))


class SCH_352e:
    atk = SET(1)
    max_health = SET(1)
    cost = SET(1)


class SCH_353:
    play = Draw(CONTROLLER) * SPELL_DAMAGE(1)


class SCH_400:
    events = OWN_SPELL_PLAY.after(Buff(SELF, "SCH_400e2"))


SCH_400e2 = buff(spellpower=1)


class SCH_425:
    events = Attack(SELF).on(Buff(FRIENDLY_WEAPON, "SCH_425e"))


SCH_425e = buff(atk=1, health=1)


class SCH_426:
    deathrattle = SummonAndAttack("SCH_426t")


class SCH_509:
    requirements = {PlayReq.REQ_TARGET_TO_PLAY: 0, PlayReq.REQ_MINION_TARGET: 0}
    play = Freeze(TARGET)
    combo = Freeze(TARGET), Hit(TARGET, 3)


class SCH_519:
    update = Refresh(FRIENDLY_WEAPON, {GameTag.ATK: 2})


class SCH_521:
    requirements = {PlayReq.REQ_TARGET_TO_PLAY: 0, PlayReq.REQ_MINION_TARGET: 0}
    def valid_target(self, target):
        return self.controller.combo or target.damage > 0
    play = combo = Destroy(TARGET)


class SCH_522:
    def play(self):
        if self.controller.weapon:
            yield Summon(CONTROLLER, RandomMinion(cost=self.controller.weapon.atk))


class MaulStudent(GameAction):
    def do(self, source):
        student = source.controller.card("SCH_523t", source)
        student.taunt = True
        student.atk = student.max_health = source.spellburst_cost
        source.game.queue_actions(source, [Summon(CONTROLLER, student)])


class SCH_523:
    spellburst = MaulStudent()


class SCH_524:
    requirements = {PlayReq.REQ_TARGET_TO_PLAY: 0, PlayReq.REQ_MINION_TARGET: 0,
                    PlayReq.REQ_DAMAGED_TARGET: 0}
    play = Buff(TARGET, "SCH_524e"), GiveDivineShield(TARGET)


SCH_524e = buff(atk=3)


class SCH_525:
    play = Give(CONTROLLER, RandomMinion(taunt=True)) * 2


class SCH_526:
    play = Buff(ALL_MINIONS - SELF, "SCH_526e")
    deathrattle = Hit(ALL_MINIONS, 1)


class SCH_526e:
    max_health = SET(1)


class SCH_533:
    play = Summon(CONTROLLER, RANDOM(FRIENDLY_DECK + MINION)).then(
        Buff(Summon.CARD, "SCH_533e"), GiveDivineShield(Summon.CARD)
    )


SCH_533e = buff(taunt=True)


class SCH_537:
    events = OWN_TURN_END.on(CastSpell(RandomSpell(cost=[0, 1, 2, 3])))


@custom_card
class FIREPLACE_SCH_621e:
    tags = {
        GameTag.CARDNAME: "Rattlegore's Return",
        GameTag.CARDTYPE: CardType.ENCHANTMENT,
    }


class SmallerRattlegore(GameAction):
    def do(self, source):
        generation = 1 + max(
            (buff.store_card for buff in source.buffs
             if buff.id == "FIREPLACE_SCH_621e"), default=0,
        )
        if generation >= 9:
            return
        card = source.controller.card("SCH_621", source)
        source.buff(
            card, "FIREPLACE_SCH_621e", atk=-generation,
            max_health=-generation, store_card=generation,
        )
        source.game.queue_actions(source, [Summon(CONTROLLER, card)])


class SCH_621:
    deathrattle = SmallerRattlegore()


class SCH_622:
    events = Attack(FRIENDLY_HERO).after(Buff(SELF, "SCH_622e"))


SCH_622e = buff(atk=1)


class SCH_623:
    cost_mod = -ATK(FRIENDLY_WEAPON)
    play = Draw(CONTROLLER) * 2


class PlagiarizeCopies(GameAction):
    def do(self, source):
        opponent = source.controller.opponent
        count = opponent.cards_played_this_turn
        # A bounced entity can appear in earlier turns too; its mutable
        # turn_played field cannot identify individual historical plays.
        played = opponent.cards_played_this_game[-count:] if count else []
        if not played:
            return
        source.game.queue_actions(source, [Reveal(SELF)])
        for card in played:
            source.game.queue_actions(source, [Give(CONTROLLER, card.id)])


class SCH_706:
    secret = EndTurn(OPPONENT).on(PlagiarizeCopies())
