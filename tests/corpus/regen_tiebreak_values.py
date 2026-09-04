# -*- coding: utf-8 -*-
"""Regenerate the tie-break value baseline used by ``test_corpus_values.py``.

    python tests/corpus/regen_tiebreak_values.py

For every corpus tournament the baseline records the value of every tie-break in
``tiebreaks_for()`` for every competitor, under both rule sets: the tournament is
stamped with a start date on either side of 2026-03-01, so neither era depends on
what today's date happens to be.

A tie-break that raises is recorded as ``ERROR:<type>`` in its own column and does
not disturb the others, so one broken tie-break cannot blank a whole record.

Rewrite the baseline only when a change of value is intended, and say in the commit
message which tie-breaks moved and why.
"""
import gzip
import hashlib
import json
import os
import sys
import time
from multiprocessing import Pool

CORPUS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(CORPUS_DIR))
sys.path.insert(0, REPO_ROOT)

CORPUS_GZ = os.path.join(CORPUS_DIR, "corpus.jsonl.gz")
BASELINE = os.path.join(CORPUS_DIR, "tiebreak_values.jsonl.gz")

# Hex characters kept per tie-break digest. A false pass needs a collision on a
# cell that actually changed, which at 24 bits is about 6e-8 per changed cell.
DIGEST = 6

# One start date on each side of the day the March 2026 rules take effect, so the
# baseline pins both rule sets and never depends on when it is run.
ERAS = (("2024", "2026-02-28"), ("2026", "2026-03-01"))

# Wide enough to reach every family the engine computes, and in particular every path
# through the cut modifiers of article 14, which is where the unplayed-round rules of
# article 16 are applied.
COMMON = [
    "PTS", "WIN", "WON", "BWG", "BPG", "VUR", "NUM", "DE", "PS", "PS/C1", "KS",
    "BH", "BH/C1", "BH/C2", "BH/M1", "BH/M2", "ABH", "AOB", "FB",
    "SB", "SB/C1", "SB/C2", "SB/M1", "SB/M2", "ESB",
    "ARO", "ARO/C1", "TPR", "PTP", "APRO", "COP", "CSQ",
]
# Match points, game points and the team-only tie-breaks need a team tournament.
TEAM_ONLY = ["MPTS", "GPTS", "EDE", "BC", "BBE", "SSSC"]


def tiebreaks_for(category):
    return COMMON + TEAM_ONLY if category == "team" else list(COMMON)


def _run(tournament_lines, names):
    import tiebreak
    import trf2json
    chessfile = trf2json.trf2json()
    chessfile.parse_file("\n".join(tournament_lines), True)
    tournament = chessfile.get_tournament(1)
    params = {"tiebreak": list(names), "check": False, "unrated": None,
              "pre_determined": False, "swiss": False}
    result = tiebreak.tiebreak(tournament, -1, params).compute_tiebreaks(tournament, params)
    return dict((cmp["cid"], [str(v) for v in cmp["tiebreakScore"]])
                for cmp in result["competitors"])


def values(trf, startdate, names):
    """{competitor: [value per tie-break]}, computed in one pass where that works and
    tie-break by tie-break where it does not, so a raising tie-break costs only its own
    column."""
    lines = [line for line in trf.split("\n") if not line.startswith("042 ")]
    lines.insert(0, "042 " + startdate)
    try:
        return _run(lines, names), []
    except Exception:
        pass
    columns, broken = {}, []
    for name in names:
        try:
            single = _run(lines, [name])
        except Exception as exc:
            broken.append("%s=%s" % (name, type(exc).__name__))
            single = None
        for cid in set(list(columns) + list(single or {})):
            columns.setdefault(cid, []).append(single[cid][0] if single else "ERROR")
    return columns, broken


def column_digests(trf, startdate, names):
    """One short digest per tie-break, positionally aligned with ``names``.

    Per tie-break rather than per record so a failure can say which tie-break moved,
    which is the first thing anyone asks."""
    columns, broken = values(trf, startdate, names)
    order = sorted(columns)
    out = []
    for index, name in enumerate(names):
        payload = "|".join("%s=%s" % (cid, columns[cid][index]) for cid in order)
        out.append(hashlib.sha256(payload.encode()).hexdigest()[:DIGEST])
    return "".join(out), broken


def digest(record):
    names = tiebreaks_for(record["category"])
    eras, broken = {}, {}
    for era, date in ERAS:
        eras[era], failures = column_digests(record["trf"], date, names)
        if failures:
            broken[era] = failures
    return (record["name"], eras, broken)


def split(blob, names):
    """The inverse of the concatenation, as {tie-break: digest}."""
    return dict((name, blob[index * DIGEST:(index + 1) * DIGEST])
                for index, name in enumerate(names))


def load_records():
    with gzip.open(CORPUS_GZ, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    records = load_records()
    if limit:
        records = records[:limit]
    started = time.time()
    with Pool() as pool:
        rows = pool.map(digest, records, chunksize=10)
    with gzip.open(BASELINE, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"common": COMMON, "team_only": TEAM_ONLY,
                                 "eras": dict(ERAS)}, sort_keys=True) + "\n")
        for name, eras, broken in rows:
            row = {"name": name, "values": eras}
            if broken:
                row["broken"] = broken
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    print("%d records in %.1fs -> %s (%.1f kB)"
          % (len(rows), time.time() - started, os.path.basename(BASELINE),
             os.path.getsize(BASELINE) / 1024.0))


if __name__ == "__main__":
    main()
