# Human and Codex battles

The browser game uses the local Codex App Server as a card-playing controller. It sends the selected seat's filtered observation, visible historical card definitions, and current legal-action menu. Codex selects an action ID; the game engine revalidates and executes that action. The browser presents the same events and animations as other matches.

## Requirements

- Activate the project's Python environment and run `python -m pip install -e .` to refresh dependencies after upgrading.
- Install Codex CLI with App Server support. Development is verified against `codex-cli 0.159.2`.
- Run `codex login` if needed. `codex login status` should show a valid local login. The game does not ask for or store your ChatGPT password or OAuth token.
- Start the game with `python -m fireplace.web_gui`, then sign into a local game account.

Using a ChatGPT login consumes the account's Codex allowance. Using an API-key login follows that authentication method's billing. A successful login check alone does not prove that a selected model is available; model access is verified when a decision completes.

## Human versus Codex

Choose Codex as the opponent in the normal-battle lobby. The model field is optional: leave it empty to use the local Codex configuration, or enter a model available to your Codex account. Random and saved complete decks are supported. Arena keeps its MCTS opponent.

Codex decisions run in the background. The match displays a thinking state while you can still inspect cards and surrender. A connection, model, protocol, or timeout failure pauses the opponent and exposes Retry. It does not silently replace Codex with a local policy. Resuming a saved match creates a fresh Codex session from the restored game state.

## Codex versus MCTS

Choose the Codex versus MCTS battle mode. The first seat uses Codex and its optional model setting; the second seat uses the existing MCTS search policy. The GUI is a spectator: ordinary card controls and surrender are hidden.

The game starts paused. Continue runs both controllers, Pause stops accepting their pending results, and Step accepts exactly one action before pausing again. A choice, attack, card play, or end-turn each counts as one action. Controller work runs outside the match lock, and paused results cannot advance the match later.

End observation abandons the match and returns to the lobby, keeping its history. To continue a saved unfinished match after a server restart, resume it from match history; it opens paused with fresh Codex sessions and the archived controller configuration.

## Codex versus Codex

Choose Codex versus Codex and optionally select a model for each seat. Both seats have independent agents and App Server conversations, even when using the same model. Both use the server machine's local Codex authentication.

The spectator controls work as above. Each controller receives its own visible hand, secrets, choices, and public opponent information. Retry replaces the failing seat's session while preserving the other controller. A restored match keeps both model settings and starts paused.

## Human versus human

Choose Human versus human in the lobby. One signed-in game account creates a room and shares its invitation code; a different account joins with that code. Each player chooses a nickname and can use a random deck or a saved complete deck. Rooms have exactly two seats.

Both browsers show the same match through their own seat's view. The server binds seats to authenticated accounts, keeps the opponent's hand and secrets private, and validates all actions against the shared game revision. Refreshing or signing in again reconnects the account to its current room. A server restart restores the accepted actions of an unfinished room. A completed room keeps each player's result until that player leaves.

Cancel a waiting room to return to the lobby. During a match, surrender before leaving. Logging out does not surrender or remove the other player. Invitation codes are shown once to the creator and remembered in that browser while the room is waiting; if that browser's storage is cleared, cancel and create a new waiting room to obtain another code.

For two players on one computer, use separate browser profiles or a private window so their game account cookies are independent. For two computers, start the server with an explicit LAN host allowlist:

```sh
python -m fireplace.web_gui --host 0.0.0.0 --allow-host 192.168.1.20 --advertised-host 192.168.1.20 --port 8765
```

Replace `192.168.1.20` with the server computer's LAN address, then open `http://192.168.1.20:8765/` on each computer. Add another `--allow-host` for each additional hostname used to reach the server. The default command accepts only local browser access.

To serve HTTPS, additionally pass `--tls-cert /path/server.crt --tls-key /path/server.key` and use the resulting `https://` address. The certificate must be trusted by the browsers; HTTPS sets Secure account cookies. Host and Origin checks remain enabled in both HTTP and HTTPS modes.

## Codex server configuration

- `TAVERNLAB_CODEX_BINARY`: path to a Codex executable when it is not on `PATH`.
- `TAVERNLAB_CODEX_MODEL`: optional default model.
- `TAVERNLAB_CODEX_TIMEOUT`: decision timeout in seconds; default 90.

Only the model selection and timeout enter game archives. Credentials and Codex conversations are not included in downloadable game logs. Card-playing sessions disable unrelated coding, browser, plugin, connector, and search tools; they use the provided seat observation rather than reading the live game or another player's data.

Replay validation remains strict. The recorded replay signature must match the current signature in every field except `source_sha256`; the source digest must be equal, or must be one of the two explicit, reviewed predecessor-to-current pairs maintained in [replay_compatibility.py](../fireplace/replay_compatibility.py). Python, dependency, schema, and other nested metadata are never relaxed, and a Git commit ID alone does not establish compatibility. Recovery replays setup and every accepted action, checks each action context, then verifies the normalized state and exact RNG checkpoint. Only after the complete prefix and checkpoints validate is an accepted old signature replaced in the restored in-memory log. Personal normal/Arena archives save that migration before their controller continues; shared room restore defers persistence until the next accepted action. Unknown differences and any action, state, or RNG divergence remain rejected, leaving the original archive unchanged. Command-line replay is read-only: it checks the final result and normalized state, plus the exact RNG when a checkpoint is present; early completed logs may lack that checkpoint. The storage boundary and full archive rules are documented in [game-archives.md](game-archives.md).

An older archive whose live RNG was already advanced by the former `powered_up` observation bug cannot be repaired by signature migration; its exact replay remains divergent and is rejected. Observation, UI projection, and search code must preserve the live game's RNG, using detached state or fixed seeds for any speculative estimate.

## References

- [Codex App Server](https://learn.chatgpt.com/docs/app-server)
- [Codex authentication](https://learn.chatgpt.com/docs/auth)
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
