# -*- coding: utf-8 -*-
"""Regenerate the tie-break value baseline used by ``test_corpus_values.py``.

    python tests/corpus/regen_tiebreak_values.py

For every corpus tournament the baseline records the value of every tie-break in
``tiebreaks_for()`` for every competitor, under both rule sets: the tournament is
stamped with a start date on either side of 2026-03-01, so neither era depends on
what today's date happens to be.

A tie-break that raises is recorded as ``ERROR`` in its own column and does not
disturb the others, so one broken tie-break cannot blank -- or shift -- a whole
record.

A partial run, for working on the generator itself, must say where to put its
output::

    python tests/corpus/regen_tiebreak_values.py --limit 50 --output /tmp/part.gz

``--limit`` without ``--output`` is refused: a fifty-record file written over the
checked-in baseline is not obviously wrong to look at, and the loss only surfaces
later as thousands of records with no baseline entry.

Rewrite the baseline only when a change of value is intended, and say in the commit
message which tie-breaks moved and why.
"""
import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

CORPUS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(CORPUS_DIR))
sys.path.insert(0, REPO_ROOT)

CORPUS_GZ = Path(CORPUS_DIR) / "corpus.jsonl.gz"
BASELINE = Path(CORPUS_DIR) / "tiebreak_values.jsonl.gz"

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
    column.

    Every returned list holds exactly one cell per name in *names*, in that order,
    whichever tie-breaks raised.  The alignment is what the caller relies on:
    ``column_digests`` reads cell *i* of every competitor as tie-break *i*, so a row
    one cell short does not lose one value, it renames every value after it.

    Building it in one pass over the collected results, rather than appending as the
    results arrive, is what guarantees that.  Appending could only fill a competitor
    the tie-break in hand had actually returned, so a tie-break that raised -- or that
    answered for fewer competitors than its neighbours -- left the row short from
    there on.  The first tie-break raising was the worst case: nothing was known about
    the competitors yet, so no cell was appended at all and the whole row shifted.
    """
    lines = [line for line in trf.split("\n") if not line.startswith("042 ")]
    lines.insert(0, "042 " + startdate)
    try:
        return _run(lines, names), []
    except Exception:
        pass

    singles, broken = [], []
    for name in names:
        try:
            singles.append(_run(lines, [name]))
        except Exception as exc:
            broken.append("%s=%s" % (name, type(exc).__name__))
            singles.append(None)

    cids = sorted(set(cid for single in singles if single for cid in single))
    columns = dict((cid, []) for cid in cids)
    for single in singles:
        for cid in cids:
            value = single.get(cid) if single else None
            columns[cid].append(value[0] if value else "ERROR")
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


def write_baseline(path, rows):
    """Write the header and one line per row to *path*.

    Separate from ``main`` so the destination is an argument rather than a module
    constant: the only way to write the checked-in baseline is to ask for it.
    """
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"common": COMMON, "team_only": TEAM_ONLY,
                                 "eras": dict(ERAS)}, sort_keys=True) + "\n")
        for name, eras, broken in rows:
            row = {"name": name, "values": eras}
            if broken:
                row["broken"] = broken
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Regenerate the tie-break value baseline for the whole corpus.")
    parser.add_argument(
        "--limit", type=int, default=0, metavar="N",
        help="measure only the first N records. For working on the generator: the "
             "result is not a baseline, so --output is required with it.")
    parser.add_argument(
        "--output", type=Path, default=None, metavar="PATH",
        help="where to write (default: the checked-in baseline, %s)"
             % BASELINE.name)
    args = parser.parse_args(argv)
    if args.limit and args.output is None:
        # Refused rather than defaulted: a truncated baseline written over the real
        # one is indistinguishable from a good one until the tests start reporting
        # thousands of records with no entry.
        parser.error("--limit produces a partial file, not a baseline; give it an "
                     "--output PATH of its own rather than overwriting %s"
                     % BASELINE.name)
    if args.output is None:
        args.output = BASELINE
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    records = load_records()
    available = len(records)
    if args.limit:
        records = records[:args.limit]
    started = time.time()
    with Pool() as pool:
        rows = pool.map(digest, records, chunksize=10)
    write_baseline(args.output, rows)
    print("%d records in %.1fs -> %s (%.1f kB)"
          % (len(rows), time.time() - started, args.output,
             os.path.getsize(args.output) / 1024.0))
    if args.limit:
        print("PARTIAL: %d of %d records. Not a baseline; do not commit it as one."
              % (len(rows), available))


if __name__ == "__main__":
    main()
