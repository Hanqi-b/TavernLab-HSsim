# Scholomance card data

The bundled `fireplace/cards/CardDefs.xml` remains the repository's baseline
card file (build `53261`).  Scholomance Academy is loaded as an additive XML
overlay at `fireplace/cards/Scholomance.xml`; the overlay contains only
`SCH_` entities, so base records from other sets are left untouched.  When an
ID is present in both files, the launch-era overlay is authoritative for that
ID.  This includes the existing `SCH_199` Transfer Student records.

The overlay is extracted from HearthSim's historical `hs-data` revision
`9b95dea77dbb4d116e861df8b650d80b1b4385d1`, corresponding to Hearthstone
build `54613` / patch `18.0.0.54613`:

`https://raw.githubusercontent.com/HearthSim/hsdata/9b95dea77dbb4d116e861df8b650d80b1b4385d1/CardDefs.xml`

The source file has 9,592 entities.  Selecting entities whose `CardID` starts
with `SCH_` produces 259 records: 135 collectible cards and 124 generated,
token, or enchantment records.  The checked-in overlay's SHA-256 is:

`28de307a73b208fd0a58fffcb021748978a9930b75e366248f57826b739f9998`

For provenance, the SHA-256 of the pinned upstream file before extraction is
`e04e474fab17364e4ec39fb89e04de50d0d90938b01e6713db2b12bfe842d86c`.

The extraction is reproducible with the following commands after downloading
the pinned source URL to `/tmp/CardDefs-54613.xml`:

```python
from pathlib import Path
import re

source = Path("/tmp/CardDefs-54613.xml")
target = Path("fireplace/cards/Scholomance.xml")
text = source.read_text(encoding="utf-8")
entities = re.findall(r'\t<Entity CardID="SCH_[^\n]+.*?</Entity>\n', text, re.S)
assert len(entities) == 259
target.write_text(
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<CardDefs build="54613">\n'
    + "".join(entities)
    + "</CardDefs>\n",
    encoding="utf-8",
)
```

`fireplace.card_data.load_card_data` is the shared metadata loader used by
the default game database and default web catalog.  It parses XML only and
does not import runtime card scripts.  A catalog constructed with an explicit
`source_path` loads exactly that path, which keeps fixture catalogs isolated
from the production overlay.  Localized fields from the source are retained;
`CardXML` continues to fall back to English when a requested locale is absent.

Gameplay implementation and behavioral validation are documented separately in
[scholomance-implementation.md](scholomance-implementation.md). Metadata coverage
alone is not evidence of correct gameplay.
