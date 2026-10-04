# Four GUI battle modes

> Historical implementation plan (2026-10-03). All four modes are implemented in the current source tree. The tasks below preserve the original delivery and acceptance plan, rather than a list of pending work. For current setup and limitations, see [Battle modes](../../codex-battles.md).

Deliver and verify in this order: human vs Codex, Codex vs MCTS, Codex vs Codex, human vs human. The approved design is in `../specs/2026-10-03-battle-controllers-design.md`.

## Human vs Codex

- A synchronous card agent speaks JSON-RPC to a persistent local Codex App Server.
- The GUI schedules its decision outside game locks, validates the returned action, and polls bounded presentation frames.
- Verify real inference, fake-process protocol failures, delayed HTTP responsiveness, account isolation, retry races, off-turn concession/replay, and pinned archive configuration.

## Codex vs MCTS

- Add `battle_mode: codex_mcts`; seat 0 is Codex, seat 1 is MCTS. The viewer has no playable actions.
- New matches start paused. `/api/automation` accepts `pause`, `resume`, `step`, and `stop` with the match session and revision.
- One step accepts exactly one engine action. Stop abandons the archive and returns to the lobby.
- Capture a detached search position under the match lock and run MCTS search outside it.
- Keep one worker per match across pause/resume; invalidate late decisions by generation and cancel only the captured old controller.
- Verify pause/resume races, single-step revision, actual MCTS search dispatch, human-action rejection, archive restore, and the production match class in a browser.

## Codex vs Codex

- Add `battle_mode: codex_codex` with independent controller objects and App Server sessions.
- Keep each model's filtered observation separate from GUI presentation.
- Preserve each seat's model/timeout in archives. Retry replaces only the failing controller.
- Verify private inputs, independent sessions, deterministic completion, restore, and a real two-session smoke test.

## Human vs human

- Add a server-wide room registry, independent of account-private AI matches. One room owns one GameSession, one lock, one revision/action log, and exactly two authenticated account-to-seat bindings.
- Create/join/current/leave room operations derive the account from authentication; clients cannot assign seats. An invitation only fills the second seat.
- Route state, action, concession, and lobby return to the current room when present. Waiting rooms remain in the lobby UI.
- Build observations, public events, effects, and presentation frames separately for both seats. Never share a seat's projection with its opponent.
- Persist waiting membership and live logs atomically at server scope. Reconnect by the same immutable account ID; restart restores the shared session before accepting actions. Raw live logs stay server-private.
- Keep loopback as the default; LAN serving is explicit and uses an exact Host/Origin allowlist. Support optional TLS with secure cookies when enabled.
- Verify two browser contexts, third-account denial, private hands/secrets/choices/events, stale/concurrent actions, consistent winner, reconnect, restart, and default loopback regressions.

## Final gate

Run relevant engine/web/archive/account regressions and browser checks, inspect the full diff, resolve independent review findings, and document launch/configuration and all four modes. Preserve existing user saves and unrelated files.
