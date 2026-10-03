# Arena formats and the 2016 historical bundle

`custom_v1` keeps the existing Arena rules and draft implementation. The
historical format is `wild_2016_09_02`, with fixed sets
`BASIC`, `EXPERT1`, `NAXX`, `GVG`, `BRM`, `TGT`, `LOE`, `OG`, and `KARA`.
Its run limits are twelve wins or three losses.

During historical player drafting, each of the three candidates displays its
original Lightforge score for the chosen hero class, using the same provider
as AI drafting. The display retains values above 100 and source markers such
as `*`, without extra modifiers or normalization. All candidates tied for the
highest numeric score are labelled; the player can still choose any card.
The page identifies the rating source, class and format date. These annotations
are separate from card-effect validation badges. Custom drafting is unchanged.
Ratings are only projected for current player offers, never for an opponent's
private draft, and reading them does not modify the run or consume randomness.

This format freezes the draft pool and Lightforge ratings. Actual battles
continue to use the project's current Fireplace card definitions and scripts,
Discover and random-generation pools, and MCTS simulation. It does not create
a 2016 card registry or isolate battle rules by era. Historical scores can
therefore describe a different card effect from the one played in battle.
Offering weights are a documented approximation, and the date-specific
exclusion of `OG_281` remains uncertain.

The setup screen selects the format once. Existing v1 saves remain
`custom_v1`, including the legacy Classic-selection compatibility path.
Historical v2 saves include the format, immutable data fingerprints and each
opponent's complete draft. Match archives keep the draft privately; finished
or abandoned log downloads include it under `arena_draft`. Public run state
and unfinished match summaries do not expose the opponent's draft.

The historical source bundle lives under
`fireplace/arena/data/wild_2016_09_02/`:

| File | Purpose |
| --- | --- |
| `cardtier.raw.json` | Byte-preserved Lightforge rows and nine class columns. |
| `pool.json` | Derived 899-card legal pool and explicit exclusion records. |
| `offer_policy.json` | Reconstructed offering policy and its accuracy marker. |
| `provenance.json` | Pinned URLs, checksums, counts, and source fingerprints. |

The importer downloads the historical CardDefs source to resolve metadata and
current DBF IDs, verifies it, and records its checksum in `provenance.json`.
The XML is an import-time input and is intentionally not duplicated in the
runtime package.

The score source is
[Arena Helper `cardtier.json`](https://raw.githubusercontent.com/rembound/Arena-Helper/fb14acf093b4c5abb2bfb8fa1187ce497e06900b/data/cardtier.json),
SHA-256
`9a832ddff0bbdcb46612ced24948542d29f01feb6148f20d5d0c3feca7b1b447`.
The CardDefs source is
[hsdata `CardDefs.xml`](https://raw.githubusercontent.com/HearthSim/hsdata/ca84daa2932b1235f2f38da53e88a2aa2b190f4c/CardDefs.xml),
SHA-256
`e41ba3137a210361ef51839c03d66eccc37cdf16c249b25f004069dfd0168d6e`.

There are 922 source score rows. Four collectible rows have no score in any
class column and are explicitly outside the scored candidate boundary:
`EX1_062`, `EX1_112`, `NEW1_016`, and `PRO_001`. The remaining 918 collectible
minion, spell, and weapon records are the candidate boundary. The legal pool
contains 899 cards after the explicit policy exclusions below. Empty score
cells are preserved exactly; a requested empty card/class cell raises a
structured missing-score error. It is never replaced, rerolled, or silently
removed during an offer.

The reconstructed exclusion policy removes these 18 C'Thun-related records:

`OG_096`, `OG_131`, `OG_162`, `OG_188`, `OG_255`, `OG_280`, `OG_281`,
`OG_282`, `OG_283`, `OG_284`, `OG_286`, `OG_293`, `OG_301`, `OG_302`,
`OG_303`, `OG_321`, `OG_334`, and `OG_339`.

It also removes `KAR_013` (`Purify`). Every exclusion has a rationale, source,
and confidence entry in `pool.json`. `OG_281` is marked `uncertain` because
the precise date-specific ban evidence was not recovered. The policy is an
explicit reconstruction informed by the
[Blizzard Hearthside Arena announcement](https://hearthstone.blizzard.com/en-gb/news/20271286/hearthside-chat-upcoming-arena-changes-with-dean-ayala),
not a claim that all historical ban records were recovered.

Historical offers are three distinct cards within a round, while cards may
reappear in later rounds. The regular rarity weights are `68/20/9/3` for the
Basic/Common bucket, Rare, Epic, and Legendary. Picks 1, 10, 20, and 30 use a
Rare, Epic, or Legendary bucket for all three cards. Class cards have weight
two; ordinary cards have weight one. The reconstructed Karazhan multiplier is
one. These numbers are documented approximations because exact historical
offering rates were not sourced.

`historical_draft_rng` derives independent streams from SHA-256 over the
format, seed, pick number, and purpose. The AI draft chooses a hero different
from the human hero and drafts thirty rounds. It selects the highest numeric
class score from each offer, breaking ties by lexicographic card ID. Each
trace row stores the three IDs, original raw score cells, parsed finite
numeric scores, marker flags, the selected ID, and profile fingerprints.

`historical_profile()` performs the full source and pool preflight. New
historical runs persist that profile. Future offers compare a fresh profile
before generating anything. `AIDraft.from_dict()` validates an archived draft
shape, trace, finite values, and deck/selection consistency without loading
the historical files; this permits an already archived match to resume when
the optional historical bundle is unavailable.

To regenerate the package bundle from pinned sources:

```bash
python3 tools/import_arena_2016.py
```
