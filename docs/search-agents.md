# Radical and MCTS agents

These Python agents adapt the algorithm structure investigated in
[xjw580/Hearthstone-Script](https://github.com/xjw580/Hearthstone-Script),
parent revision `9d8c7ad94bd52ce9d4812e40f7b45b052ae3f047` (v4.16.4-GA).
They use Tavern's action and rule interfaces, rather than running or embedding
that project's client automation. They are experimental policies, not measured
win-rate improvements.

## Selecting an opponent

The regular battle lobby offers `radical` and `mcts`, with Radical as the
default. The browser remembers the selection locally; old heuristic
preferences fall back to Radical. Arena always uses MCTS, regardless of the
normal battle preference or an opponent field sent by an older client.
The heuristic entry is disabled; its implementation remains available for
internal fallbacks and algorithm experiments. The terminal example accepts
the two search policies:

```sh
python examples/human_vs_heuristic.py --opponent radical --seed 7
python examples/human_vs_heuristic.py --opponent mcts --seed 7
```

Programmatic use goes through `GameSession`, which supplies the optional search
interface when a player has a main-phase decision:

```python
from fireplace.agent_factory import create_agent
from fireplace.controller import GameSession

session = GameSession(game, {
    game.players[0]: create_agent("radical", seed=7),
    game.players[1]: create_agent("mcts", seed=8),
})
session.run()
```

## Algorithm structure

**Radical:** select an affordable hand subset using a 0/1 knapsack objective
of cost plus card weight. Compare the extra resource from the Coin and order
selected cards using a separate play-priority weight. Card targeting has a
heuristic fallback. Its combat search evaluates sequences of visible attacks;
when budget permits, it estimates attacks by the visible opposing board.
That reply minimizes the original player's score, so the blend expressed in
the original player's perspective is `0.6 * current + 0.4 * worst_reply`.
Card selection and combat planning remain separate stages.

The default card weight and play-priority weight are both `1.0`. Configure
them independently by card ID when experimenting with a deck:

```python
from fireplace.radical_agent import RadicalAgent

agent = RadicalAgent(
    seed=7,
    card_weights={"CS2_029": 3.0},
    power_weights={"CS2_029": 5.0},
)
```

Here Fireball receives a larger knapsack value and an earlier play priority;
its mana cost still consumes four mana. The Coin is used only if the extra
mana produces a better card subset. The agent executes one legal action at a
time and recalculates affordability and targets from the actual state.

**Legacy MCTS (`legacy_v1`):** jointly explore legal card plays, targets, placement, attacks,
hero powers, and ending the turn. UCT balances observed score-improvement
frequency against exploration. Random rollouts provide a binary improvement
signal; this is not a whole-game win probability. The agent uses the best
completed line found and returns one current legal action. It replans after
the controller executes that action. Unlike the inspected reference code,
UCT uses floating-point division and makes a fresh sibling comparison at
each level. Direct `MCTSAgent()` construction retains this version for existing
callers. Unversioned archived matches also resume with this policy.

**Tactical MCTS (`tactical_v2`):** new matches created through
`create_agent("mcts")`, including Arena, use this version. It uses the same
MCTS flow with the following tactical stages:

- Before MCTS, a deterministic tactical probe searches at most 64 transitions
  and eight actions for a verified current-turn victory. It executes only the
  first legal action and searches again from the actual state on every decision.
- Before randomized MCTS continuation, a separate unified candidate pass
  first makes one fixed-seed, no-reply transition for each prioritized root,
  then spends the remaining slice on projected END/reply scores and uncertain
  samples. This keeps basic immediate scores for all legal spell variants
  available even when a later projection is cut off. It always includes a
  legal `END_TURN` baseline. Targeted spells, area effects, no-target spells,
  placement variants, and choose branches remain distinct legal candidates;
  the pass does not collapse them into a same-card target check. It covers at
  most 64 roots and records planned roots, actual basic coverage, projected
  completions, omitted roots, failures, uncertainty, and cooperative cutoffs
  explicitly.
- Candidate transitions use a fixed seed on detached `SearchPosition` values,
  so the pass does not consume the agent RNG or live-game RNG. Deterministic
  prepared children seed MCTS's first root expansions, including when their
  later projection was cut off. Tactical MCTS expands roots in descending
  finite immediate score with legal-order ties, while retaining negative
  roots for deeper combinations. Uncertain branches use up to three fixed
  samples and a conservative (minimum-sample) score; they can guide selection
  but never certify a lethal.
- The hero-health coefficient falls from 12 to 7. Completed turn-end branches
  also estimate visible opponent attacks, bounded by 32 transitions and depth
  eight. The engine enforces taunt, Freeze, Divine Shield, and weapon rules;
  a discovered lethal reply outweighs ordinary board value.
  Tactical scoring also values each public hand resource at 2.5 points,
  including unknown draws without invented identities. Bounded bonuses for
  public keywords, triggered/aura script presence, and readiness distinguish
  silence/transform targets. These residual bonuses are heuristics; actual
  spell effects, fatigue, overflow, and board limits come from the engine.
- Rollouts use seeded action biases and a continuous, bounded score reward.
  A certain terminal victory outranks every ordinary improving line. Simple
  decisions retain the 0.2-second budget; complex decisions can use 1.0 second,
  still capped at 128 MCTS iterations and depth 12. The lethal probe uses that
  base budget. The candidate pass has an additional 0.35-second simple or
  0.65-second complex slice, followed by MCTS with its own base budget. A
  decision can therefore take longer than `time_budget`; each stage has a
  cooperative deadline and records its elapsed time and cutoffs.
- Terminal transitions are recognized before deadline checks. Victories from
  effects that destroy a hero are recognized from engine outcomes even if the
  hero's displayed health remains positive.

Archives save the MCTS policy version, search configuration, and agent RNG
state. Resume validates the version/configuration before replay. A new game
is needed to use tactical v2 when continuing an old legacy match.

The candidate comparison uses detached branches and its own fixed seed. An
immediately harmful spell remains available to MCTS so a later combo can still
win; a completed MCTS turn-end score is compared fairly before the one-step
candidate replaces it. If every modeled spell is harmful compared with the
`END_TURN` baseline, the baseline is retained. Friendly healing, buffs, and
beneficial deathrattles remain eligible when their tactical score is positive.
Every tactical decision exposes a JSON-safe `decision_trace` with each covered
action, source card, target, finite score/sample values, uncertainty,
completion reason, coverage, and final selection.

The candidate pass runs before randomized continuation and compares a spell
followed by END with the END baseline and the same visible reply estimate.
It cannot guarantee the best target for every future combo. Already certified
winning lines bypass it. Seeded random triggers and
unknown draws can contribute approximate scores; those scores do not certify
a lethal or predict an actual future random outcome.
Discover stops at a labeled incomplete choice boundary; the real controller
resolves the visible choice and replans. Private per-action archive storage and
retention are described in [game-archives.md](game-archives.md).

Both policies use manually chosen weights. MCTS evaluates board, heroes,
weapons, hand, resources, deck counts, and secrets. Search budgets and depth
limits keep synchronous browser decisions finite; iteration-only settings
are useful for reproducible algorithm tests. A seed alone does not promise
identical decisions when a wall-clock budget changes how much search finishes.

Both constructors default to a base `time_budget` of 0.2 seconds, at most 128
search iterations/nodes, depth 12, and at most 64 main actions in a turn.
Radical's opposing attack estimate additionally defaults to depth 2.
Use `time_budget=None` for an iteration-only experiment, or zero to disable
lookahead. One engine transition can finish after the time limit; this is a
cooperative deadline rather than a process timeout.
These are search budgets: creating the isolated root position and executing
the chosen real action add to the total decision time. Depth/time cutoffs
are tracked separately from completed MCTS lines; if no line finishes,
the best partial path supplies a legal fallback decision.

## Search boundary and information limits

`Agent.choose_action(observation, legal_actions)` is unchanged. Search-capable
agents additionally implement `choose_action_with_search` and receive a
`SearchPosition` handle. This interface returns detached observations and
value actions, and creates a new position for every transition. Agents do not
need live game, player, card, observer, or RNG objects.

`EngineSearchPosition` uses a copied engine state. It excludes real observers
and installs a separate entity index, so speculative decisions neither create
real action-log entries nor send effects to the browser timeline. Search RNG
is independent of the live game's future stream.
Speculative engine messages are also suppressed in the search's execution
context, while real actions retain their normal logs.

Unknown identities are deliberately not used:

- Both decks and the rival hand are replaced by inert, unplayable placeholders.
- Rival concealed Secrets keep their public count but do not trigger predicted
  effects. Public quests and visible card effects remain available.
- Unknown draws count as cards but cannot be played in the search branch.

Tactical lethal certification is conservative: concealed Secrets, consumed
search RNG, movement of unknown cards, or a public effect that might depend on
hidden cards make a branch uncertain. Hidden-zone selectors are checked even
when placeholder types cause their simulated candidate set to be empty.
Opaque custom callbacks also prevent certification while unknown cards exist.
These branches can guide approximate MCTS scoring but cannot be labeled a
deterministic lethal. This check may reject a safe line when an unrelated
effect is present; it never reads the replaced cards' original identities.

This is an approximate information model, not belief sampling or a complete
prediction of hidden-card interactions. Effects that inspect, copy, tutor, or
summon unknown cards may be unavailable or only approximately evaluated.
Visible effects still depend on Tavern's existing card-script coverage.

A branch stops at game over, ending the player's turn, or an unresolved
choice. Ending the turn applies engine end-turn effects before stopping.
Pending choices are never copied and executed speculatively because their
Python callback closures may reference another state. Callback captures that
still reference the source game are rejected. The real controller resolves
choices and the policy then searches the resulting actual state. If a root
state cannot safely be copied, the ordinary legal-action policy is used.

## Verification surfaces

`tests/test_search_simulation.py` covers branch isolation, observer locks,
RNG and action-log preservation, masked hidden zones, unknown draws, choice
boundaries, end-turn effects, and attacks-only opposing replies.
`tests/test_search_agents.py` covers policy decisions and search budgets.
Lobby, Arena, and browser acceptance checks cover selection propagation.

`tests/test_mcts_tactical.py` covers tactical ordering, rewards, deadlines,
configuration validation, and scripted terminal outcomes.
`tests/test_mcts_tactical_integration.py` uses real engine turns for multi-attack
and spell lethal, taunt and shield handling, Coin, survival against two/three
Yetis, frozen attackers, random effects, hidden Secrets, Saboteur's hidden-spell
interaction, and Mecha'thun's destruction victory. Archive tests verify policy
selection and reject contradictory saved settings.
`tests/test_search_targeting.py` covers the retained compatibility helper for
bounded target comparisons, ties, unsupported continuations, and
choice/placement grouping. `tests/test_search_candidates.py` covers unified
root category coverage, END fallback, stable ties, uncertain sampling,
explicit failures/cutoffs, deterministic child-cache reuse, combo exemption,
and agent-RNG preservation.
`tests/test_spell_targeting_integration.py` reproduces the reported friendly
Flamewaker Polymorph, checks the full policy on that board, and verifies that
friendly healing/buffs/Sylvanas triggers and spell lethal remain available.

The paired tactical benchmark runs complete AI turns, checking legal actions,
live-state isolation, and live-RNG preservation:

```sh
PYTHONWARNINGS=ignore venv/bin/python tools/benchmark_mcts.py --seeds 8 \
  --output /tmp/tavernlab-mcts-benchmark.json
```

It compares legacy 0.2-second search, legacy fixed 128 iterations, and tactical
v2 on six fixtures. These are tactical regressions, not a full-game win-rate
measurement. The scoring weights and visible-only opponent reply remain
heuristics; hidden-hand prediction and whole-game planning are not implemented.

Before the unified candidate pass, the 2026-10-03 local paired run completed 144 fixture turns without illegal
actions, live-state/RNG mutation, or action-limit failures. Observed results:

| Objective | Legacy 0.2 s | Legacy 128 iterations | Tactical v2 |
| --- | --- | --- | --- |
| Four lethal fixtures combined | 25/32 | 32/32 | 32/32 |
| Clear a Yeti to survive visible attacks | 0/8 | 0/8 | 8/8 |
| Frostbolt controls the threatening Raptor | 0/8 | 0/8 | 7/8 |

The 48 fixed-iteration legacy action sequences, final states, and outcomes
matched the pre-upgrade baseline exactly. Timed results depend on scheduling:
the final Frostbolt run still included one face decision, so short-budget
control choices are improved rather than guaranteed.

After the unified candidate pass, a separate 2026-10-03 verification passed
230 search, spell, archive, and Arena compatibility tests. Six complete-turn
fixtures across four seeds produced 16/16 lethal successes, 4/4 Yeti survival
results, and 4/4 Frostbolt control results, with no illegal actions or live
state/RNG changes. The corresponding 24 fixed-iteration legacy runs matched
the pre-upgrade golden action sequences, final states, and outcomes exactly.
These small deterministic fixtures establish regressions, not general win rate.

On the archived friendly-Flamewaker Polymorph scene, all five legal Polymorph
targets received finite immediate scores across four seeds, and none of those
runs selected the friendly target. Basic coverage was 22/33 roots for one seed
and 33/33 for the other three. No projected endpoint completed within the
candidate budget on that scene; those rows explicitly report cutoff. Decisions
took approximately 2.2–2.5 seconds, and live state and RNG stayed unchanged.
