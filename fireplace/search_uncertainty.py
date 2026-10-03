"""Conservative hidden-zone dependency checks for lethal certification.

This inspects public effect definitions, never the replaced cards' identities.
It is deliberately stricter than execution: an opaque custom callback or a
possibly hidden selector prevents a proof even if its trigger does not fire.
Heuristic search can still use the resulting approximate branch.
"""

import operator
from types import FunctionType, MethodType

from hearthstone.enums import GameTag, Zone

from .actions import Action as EngineAction
from .dsl import selector as selectors


def _bounds(selector, unknown, source):
    """Lower/upper sets of unknown entities a selector could return."""
    universe = {card.entity_id for card in unknown}
    if isinstance(selector, selectors.EnumSelector):
        if isinstance(selector.tag_enum, Zone):
            result = {c.entity_id for c in unknown if c.zone == selector.tag_enum}
            return result, result
        return set(), universe  # Card type/race/tags are unknown.
    if isinstance(selector, selectors.ComparisonSelector):
        right = selector.right
        if (getattr(selector.left, "tag", None) == GameTag.CONTROLLER
                and isinstance(right, selectors.Controller) and right.child is None):
            controller = right.evaluate(source)
            result = {c.entity_id for c in unknown
                      if selector.op(c.controller, controller)}
            return result, result
        return set(), universe
    if isinstance(selector, selectors.SetOpSelector):
        lower_a, upper_a = _bounds(selector.left, unknown, source)
        lower_b, upper_b = _bounds(selector.right, unknown, source)
        if selector.op is operator.and_:
            return lower_a & lower_b, upper_a & upper_b
        if selector.op is operator.or_:
            return lower_a | lower_b, upper_a | upper_b
        if selector.op is operator.sub:
            return lower_a - upper_b, upper_a - lower_b
        return set(), universe
    if any(selector is known for known in (
            selectors.SELF, selectors.OWNER, selectors.TARGET,
            selectors.ATTACK_TARGET, selectors.CREATOR_TARGET)):
        # These refer to a public source/target rather than querying a zone.
        return set(), set()
    if isinstance(selector, (selectors.RandomSelector, selectors.SliceSelector,
                             selectors.DeDuplicate)):
        _, upper = _bounds(selector.child, unknown, source)
        return set(), upper
    if isinstance(selector, selectors.BoardPositionSelector):
        return set(), set()  # Adjacent battlefield entities are public.
    return set(), universe  # Opaque predicates are not safe to certify.


def _depends_on_hidden(effect, unknown, source, seen):
    if id(effect) in seen:
        return False
    seen.add(id(effect))
    if isinstance(effect, selectors.Selector):
        return bool(_bounds(effect, unknown, source)[1])
    if isinstance(effect, (FunctionType, MethodType)):
        return True  # May read hidden cards directly in Python.
    if isinstance(effect, EngineAction) and type(effect).__module__.startswith("fireplace.cards."):
        return True  # Custom do() methods cannot be audited structurally.
    if isinstance(effect, dict):
        children = effect.values()
    elif isinstance(effect, (tuple, list, set)):
        children = effect
    elif type(effect).__module__.startswith(("fireplace.actions", "fireplace.dsl.")):
        children = vars(effect).values() if hasattr(effect, "__dict__") else ()
    else:
        return False
    return any(_depends_on_hidden(child, unknown, source, seen) for child in children)


_SOURCE_SCRIPTS = (
    "play", "combo", "activate", "deathrattle", "draw", "discard", "inspire",
    "outcast", "overkill", "magnetic", "spellburst", "awaken", "reward",
)


def hidden_effect_possible(game, action):
    """Fail closed for visible effects that may query inert hidden cards."""
    unknown = [card for player in game.players
               for card in (*player.deck, *player.hand, *player.secrets)
               if card.id == "UNKNOWN"]
    if not unknown:
        return False
    source_id = action.source_entity_id
    for player in game.players:
        visible = [*player.characters, player.hero.power, *player.secrets]
        if player.weapon is not None:
            visible.append(player.weapon)
        visible.extend(card for card in player.hand if card.id != "UNKNOWN")
        for card in visible:
            if card.id == "UNKNOWN" or card.ignore_scripts:
                continue
            definitions = [card.events, tuple(card.update_scripts)]
            if card.zone == Zone.HAND:
                definitions = [card.data.scripts.Hand.events, card.data.scripts.Hand.update]
            else:
                definitions.extend((
                    card.data.scripts.deathrattle,
                    getattr(card, "additional_deathrattles", ()),
                    card.data.scripts.secret_deathrattles,
                ))
            if card.entity_id == source_id:
                definitions.extend(getattr(card.data.scripts, name, ())
                                   for name in _SOURCE_SCRIPTS)
            for buff in card.buffs:
                definitions.extend((
                    buff.events, tuple(buff.update_scripts),
                    buff.data.scripts.deathrattle,
                    getattr(buff, "additional_deathrattles", ()),
                    buff.data.scripts.secret_deathrattles,
                ))
            if _depends_on_hidden(definitions, unknown, card, set()):
                return True
    return False
