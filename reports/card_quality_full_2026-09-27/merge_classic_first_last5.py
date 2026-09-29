"""Merge independent EX1_183–187 cases into the first Classic verdict group."""

import csv
from pathlib import Path


HERE = Path(__file__).resolve().parent


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def write(name, fields, rows):
    with (HERE / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    ids = {"EX1_183", "EX1_184", "EX1_185", "EX1_186", "EX1_187"}
    for dest, source, key in (
        ("classic_probe_first.csv", "classic_probe_first_last5.csv", lambda row: (row["card_id"], row["case_id"])),
        ("classic_verdict_first.csv", "classic_verdict_first_last5.csv", lambda row: row["card_id"]),
    ):
        dest_fields, dest_rows = read(dest)
        source_fields, source_rows = read(source)
        assert dest_fields == source_fields
        assert {row["card_id"] for row in source_rows} == ids
        merged = {key(row): row for row in dest_rows}
        assert len(merged) == len(dest_rows)
        merged.update({key(row): row for row in source_rows})
        rows = sorted(merged.values(), key=key)
        write(dest, dest_fields, rows)
        print(dest, len(rows))
    _, verdicts = read("classic_verdict_first.csv")
    _, cases = read("classic_probe_first.csv")
    expected = sorted(row["card_id"] for row in read("expansion_yellow_baseline.csv")[1]
                      if row["set"] == "Classic (EXPERT1)")[:85]
    assert sorted(row["card_id"] for row in verdicts) == expected
    assert {row["card_id"] for row in cases} == set(expected)
    assert len(cases) == len({(row["card_id"], row["case_id"]) for row in cases})
    print(f"merged {len(verdicts)} card verdicts and {len(cases)} unique behavior cases")


if __name__ == "__main__":
    main()
