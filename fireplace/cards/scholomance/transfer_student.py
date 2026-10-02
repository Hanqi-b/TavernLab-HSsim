from ..utils import *


##
# Minions


TRANSFER_STUDENT_FOR_BOARD = {
    BoardEnum.STORMWIND: "SCH_199t",
    BoardEnum.ORGRIMMAR: "SCH_199t2",
    BoardEnum.PANDARIA: "SCH_199t3",
    BoardEnum.STRANGLETHORN: "SCH_199t4",
    BoardEnum.NAXXRAMAS: "SCH_199t5",
    BoardEnum.GOBLINS_VS_GNOMES: "SCH_199t6",
    BoardEnum.BLACKROCK_MOUNTAIN: "SCH_199t7",
    BoardEnum.THE_GRAND_TOURNAMENT: "SCH_199t8",
    BoardEnum.EXCAVATION_SITE: "SCH_199t24",
    BoardEnum.THE_MUSEUM: "SCH_199t9",
    BoardEnum.WHISPERS_OF_THE_OLD_GODS: "SCH_199t10",
    BoardEnum.KARAZHAN: "SCH_199t11",
    BoardEnum.GADGETZAN: "SCH_199t12",
    BoardEnum.UNGORO: "SCH_199t13",
    BoardEnum.ICECROWN_CITADEL: "SCH_199t14",
    BoardEnum.THE_CATACOMBS: "SCH_199t15",
    BoardEnum.THE_WITCHWOOD: "SCH_199t16",
    BoardEnum.THE_BOOMSDAY_PROJECT: "SCH_199t17",
    BoardEnum.GURUBASHI_ARENA: "SCH_199t18",
    BoardEnum.DALARAN: "SCH_199t19",
    BoardEnum.ULDUM_TOMB: "SCH_199t20",
    BoardEnum.ULDUM_CITY: "SCH_199t25",
    BoardEnum.DRAGONBLIGHT: "SCH_199t21",
    BoardEnum.OUTLAND: "SCH_199t22",
    BoardEnum.SCHOLOMANCE: "SCH_199t23",
    None: "SCH_199t",
}

TRANSFER_STUDENT_EFFECT = Switch(
    GAME_SKIN,
    {board: Morph(SELF, card_id) for board, card_id in TRANSFER_STUDENT_FOR_BOARD.items()},
)


class SCH_199:
    """Transfer Student"""

    @staticmethod
    def resolve_card_id(player):
        if not hasattr(player.game, "skin"):
            return "SCH_199"
        return TRANSFER_STUDENT_FOR_BOARD.get(player.game.skin, "SCH_199t")

    # Initial decks are created before the board is selected.
    class Hand:
        events = GameStart().on(TRANSFER_STUDENT_EFFECT)

    class Deck:
        events = GameStart().on(TRANSFER_STUDENT_EFFECT)


class SCH_199t2:
    """Transfer Student"""

    # <b>Battlecry:</b> Deal 2 damage.
    requirements = {PlayReq.REQ_TARGET_IF_AVAILABLE: 0}
    play = Hit(TARGET, 2)


class SCH_199t3:
    """Transfer Student"""

    # <b>Battlecry:</b> Give a friendly minion +1/+2.
    requirements = {
        PlayReq.REQ_TARGET_IF_AVAILABLE: 0,
        PlayReq.REQ_FRIENDLY_TARGET: 0,
        PlayReq.REQ_MINION_TARGET: 0,
    }
    play = Buff(TARGET, "SCH_199t3e")


SCH_199t3e = buff(+1, +2)


class SCH_199t5:
    """Transfer Student"""

    # <b>Deathrattle:</b> Add a random <b>Deathrattle</b> minion to your_hand.
    deathrattle = Give(CONTROLLER, RandomMinion(deathrattle=True))


class SCH_199t6:
    """Transfer Student"""

    # <b>Battlecry and Deathrattle:</b> Add a <b>Spare Part</b> card to your
    # hand.
    play = deathrattle = Give(CONTROLLER, RandomCard(spare_part=True, is_standard=False))


class SCH_199t7:
    """Transfer Student"""

    # At the end of your turn, reduce the Cost of a random card in your hand by
    # (2).
    events = OWN_TURN_END.on(Buff(RANDOM(FRIENDLY_HAND), "SCH_199t7e"))


class SCH_199t7e:
    tags = {GameTag.COST: -2}
    events = REMOVED_IN_PLAY


class SCH_199t8:
    """Transfer Student"""

    # <b>Inspire:</b> Draw a card.
    inspire = Draw(CONTROLLER)


class SCH_199t9:
    """Transfer Student"""

    # <b>Battlecry:</b> <b>Discover</b> a new basic Hero Power.
    play = GenericChoice(
        CONTROLLER, RandomBasicHeroPower(exclude=FRIENDLY_HERO_POWER) * 3
    )


class SCH_199t10:
    """Transfer Student"""

    # <b>Battlecry:</b> Spend all your Mana. Summon a random minion of that
    # Cost.
    play = SpendMana(CONTROLLER, CURRENT_MANA(CONTROLLER)).then(
        Summon(CONTROLLER, RandomMinion(cost=Min(SpendMana.AMOUNT, 10)))
    )


class SCH_199t11:
    """Transfer Student"""

    # <b>Battlecry:</b> Add a <b>Karazhan</b> Portal spell to your hand.
    entourage = ["KAR_073", "KAR_077", "KAR_091", "KAR_075", "KAR_076"]
    play = Give(CONTROLLER, RandomEntourage())


class SCH_199t12:
    """Transfer Student"""

    # <b>Battlecry:</b> Give a random minion in your hand +2/+2.
    play = Buff(RANDOM(FRIENDLY_HAND + MINION), "SCH_199t12e")


SCH_199t12e = buff(+2, +2)


class SCH_199t13:
    """Transfer Student"""

    # <b>Battlecry:</b> <b>Adapt</b>.
    play = Adapt(SELF)


class SCH_199t14:
    """Transfer Student"""

    # [x]<b>Deathrattle:</b> Add a random <b>Death Knight</b> card to your
    # hand.
    entourage = LICH_KING_CARDS
    deathrattle = Give(CONTROLLER, RandomEntourage())


class SCH_199t15:
    """Transfer Student"""

    # <b>Battlecry:</b> <b>Recruit</b> a minion that costs (2) or less.
    play = Recruit(COST <= 2)


class SCH_199t17:
    """Transfer Student"""

    # [x]<b>Taunt</b>. <b>Battlecry:</b> If you have 10 Mana Crystals, gain
    # +5/+5.
    powered_up = AT_MAX_MANA(CONTROLLER)
    play = powered_up & Buff(SELF, "SCH_199t17e")


SCH_199t17e = buff(+5, +5)


class SCH_199t18:
    """Transfer Student"""

    # <b>Rush</b> <b>Overkill:</b> Draw a card.
    overkill = Draw(CONTROLLER)


class SCH_199t19:
    """Transfer Student"""

    # <b>Battlecry:</b> Add a <b>Lackey</b> to_your hand.
    play = Give(CONTROLLER, RandomLackey())


class SCH_199t21:
    """Transfer Student"""

    # <b>Battlecry:</b> <b>Discover</b> a Dragon.
    play = DISCOVER(RandomDragon())


class SCH_199t22:
    """Transfer Student"""

    # [x]<b>Dormant</b> for 2 turns. When this awakens, deal 3 damage to two
    # random enemy minions.
    tags = {GameTag.DORMANT: True}
    dormant_turns = 2
    awaken = Hit(RANDOM_ENEMY_MINION * 2, 3)


class SCH_199t23:
    """Transfer Student"""

    # <b>Battlecry:</b> Add a Dual Class card to your hand.
    play = Give(
        CONTROLLER,
        RandomCollectible(
            multi_class_group=[
                MultiClassGroup.PALADIN_PRIEST,
                MultiClassGroup.PRIEST_WARLOCK,
                MultiClassGroup.WARLOCK_DEMONHUNTER,
                MultiClassGroup.HUNTER_DEMONHUNTER,
                MultiClassGroup.DRUID_HUNTER,
                MultiClassGroup.DRUID_SHAMAN,
                MultiClassGroup.MAGE_SHAMAN,
                MultiClassGroup.MAGE_ROGUE,
                MultiClassGroup.ROGUE_WARRIOR,
                MultiClassGroup.PALADIN_WARRIOR,
                MultiClassGroup.MAGE_HUNTER,
                MultiClassGroup.HUNTER_DEATHKNIGHT,
                MultiClassGroup.DEATHKNIGHT_PALADIN,
                MultiClassGroup.PALADIN_SHAMAN,
                MultiClassGroup.SHAMAN_WARRIOR,
                MultiClassGroup.WARRIOR_DEMONHUNTER,
                MultiClassGroup.DEMONHUNTER_ROGUE,
                MultiClassGroup.ROGUE_PRIEST,
                MultiClassGroup.PRIEST_DRUID,
                MultiClassGroup.DRUID_WARLOCK,
                MultiClassGroup.WARLOCK_MAGE,
            ]
        ),
    )


class SCH_199t24:
    """Transfer Student"""

    # <b>Battlecry:</b> Add a random weapon to your hand.
    play = Give(CONTROLLER, RandomWeapon())


class SCH_199t25:
    """Transfer Student"""

    # <b>Battlecry:</b> Add an <b>Uldum</b> Plague spell to your hand.
    entourage = ["ULD_718", "ULD_717", "ULD_715", "ULD_172", "ULD_707"]
    play = Give(CONTROLLER, RandomEntourage())
