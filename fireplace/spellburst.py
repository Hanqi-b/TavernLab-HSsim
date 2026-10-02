"""One-use post-resolution triggers for spells played by a player.

Eligibility is fixed at cast start; entities summoned by the spell or another
Spellburst do not consume their own Spellburst. Card scripts expose
``spellburst`` in the same way as ``play`` and ``deathrattle``.
"""
from hearthstone.enums import CardType, Zone


def capture_spellburst(player, spell):
    if spell.type != CardType.SPELL:
        return None
    listeners = tuple(
        (entity, entity.play_counter)
        for entity in player.game.live_entities
        if entity.controller is player
        and entity.type in (CardType.MINION, CardType.WEAPON)
        and getattr(entity.data.scripts, "spellburst", ())
        and not entity.spellburst_used
        and not entity.ignore_scripts
    )
    if not listeners:
        return None
    return listeners, spell.cost, len(player.game.death_history)


def _after_choices(game, continuation):
    for participant in game.players:
        if participant.choice:
            participant.choice.choice_callback.append(lambda: _after_choices(game, continuation))
            return
    continuation()


def resolve_spellburst(player, spell, captured):
    if captured is None or spell.cant_play:
        return

    def resolve():
        player.game.refresh_auras()
        player.game.process_deaths()
        listeners, cost, previous_deaths = captured
        deaths = tuple(
            c for c in player.game.death_history[previous_deaths:]
        )

        def dispatch(index=0):
            if index == len(listeners):
                return
            entity, play_counter = listeners[index]
            if (
                entity.zone != Zone.PLAY
                or entity.controller is not player
                or entity.play_counter != play_counter
                or entity.ignore_scripts
                or entity.spellburst_used
                or getattr(entity, "dead", False)
            ):
                dispatch(index + 1)
                return
            # Consume first; a bounce in the effect can re-arm the next play.
            entity.spellburst_used = True
            entity.spellburst_spell = spell
            entity.spellburst_cost = cost
            entity.spellburst_deaths = deaths

            def finish():
                entity.spellburst_spell = None
                entity.spellburst_cost = 0
                entity.spellburst_deaths = ()
                dispatch(index + 1)

            try:
                player.game.trigger(entity, entity.get_actions("spellburst"), [spell])
            except Exception:
                entity.spellburst_spell = None
                entity.spellburst_cost = 0
                entity.spellburst_deaths = ()
                raise
            # A preceding Spellburst may itself Discover. Keep its context
            # alive and serialize the remaining triggers after that choice.
            _after_choices(player.game, finish)

        dispatch()

    # A Discover spell has not finished until its choices have been made.
    _after_choices(player.game, resolve)
