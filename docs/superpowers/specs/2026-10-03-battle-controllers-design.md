# GUI battle controllers

> Historical approved design (2026-10-03). The four modes described here are implemented in the current source tree. This document preserves the design rationale; [Battle modes](../../codex-battles.md) documents current operation and limitations.

Approved scope: deliver these modes in order: human versus Codex, Codex versus MCTS, Codex versus Codex, and human versus human in LAN rooms. Existing normal battles, Arena rules, accounts, and archives remain compatible.

## Architecture

The server owns each two-seat `GameSession`. A seat is controlled by a human, a local search agent, or a Codex agent. Each agent receives its own filtered observation and current legal actions. GUI viewing is independent of agent information: a spectator view never becomes model input. The engine validates every accepted action again before execution.

Codex runs through a lazy, persistent local App Server process using stdio JSON-RPC and existing Codex authentication. Each controlled seat uses an independent session. Model selection is optional; omitted selection uses the local Codex configuration. Prompts contain visible card definitions from the bundled historical card data and enumerated legal actions. A structured response selects one action ID. Card-playing sessions disable unrelated shell, browser, connector, plugin, and agent tools.

External inference never holds the game lock. The scheduler snapshots the decision under the lock, releases it for inference, and validates generation, revision, decision seat, and legal action on completion. At most one decision is pending per match. Cancellation, shutdown, surrender, or a new generation invalidates late results. Errors pause the opponent and expose a retry control, without silently substituting another policy.

Accepted moves retain existing public events and animation frames. A bounded frame history lets polling clients animate unseen moves and reconcile to authoritative state if a gap occurs. Archives retain action logs and controller configuration; credentials and model conversations do not enter downloadable archives. Resuming starts fresh Codex sessions from restored game state.

## Delivery and acceptance

1. Human versus Codex: lobby selection, model setting, async thinking/error/retry, legal play and choice handling, concession while thinking, restart/resume, protocol tests, HTTP tests, and browser verification. Attempt a real local Codex decision after deterministic tests.
2. Codex versus MCTS: independently configured seats, spectator controls for pause/resume/single step, bounded automatic turns, and tests against duplicate execution or late completion after pause.
3. Codex versus Codex: separate sessions/configuration and private observations, per-seat failure handling, automated completion tests and real two-session smoke verification where account access permits.
4. Human versus human: authenticated room creation/join, participant-to-seat binding, two filtered views, room synchronization, participant reconnection, shared match ownership/resume, concession and outcome, configurable LAN bind/host/origin checks. Invitations use room codes; ranking and automatic matchmaking are outside this scope. Test two isolated browser contexts and unauthorized room/action access.

Each stage is verified before the next starts. Final review covers concurrency, hidden-information filtering, archive integrity, LAN authentication, and existing mode regressions.
