# -*- coding: utf-8 -*-
"""Value regression over the TRF corpus.

``test_corpus.py`` asks whether the engine *accepts or rejects* each tournament. It
compares the computed rank order against the order the file declares, and it is
therefore blind to any change that leaves the ordering intact -- and blind, too, to
every tie-break the file does not happen to rank by. A tie-break value can move on
thousands of tournaments without that test noticing.

This module asks what the engine *computed*: every tie-break in
``regen_tiebreak_values.tiebreaks_for()``, for every competitor, against a checked-in
baseline. Both are wanted. The verdict test catches crashes and validity regressions
that a value baseline cannot see, and this one catches arithmetic that moved.

Each tournament is measured twice, stamped with a start date on either side of
2026-03-01, because ``tiebreak.find_tmversion`` picks the rule set from that date and
the corpus files carry no ``042`` record of their own. Without the stamp these values
would follow whatever today's date happens to be.

When a value legitimately changes, regenerate with::

    python tests/corpus/regen_tiebreak_values.py

and say in the commit message which tie-breaks moved and why.
"""
import gzip
import json

import pytest

import _harness
import regen_tiebreak_values as baseline

BASELINE_PATH = baseline.BASELINE


def load_baseline():
    header, rows = None, {}
    with gzip.open(BASELINE_PATH, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if header is None:
                header = entry
            else:
                rows[entry["name"]] = entry
    return header, rows


_HEADER, _ROWS = load_baseline()


def test_the_baseline_matches_the_tiebreaks_being_asked_for():
    # A tie-break added to or removed from the generator shifts every digest along by
    # one column, so the baseline has to be regenerated with it. Fail on the list rather
    # than on six thousand unreadable digest mismatches.
    assert _HEADER["common"] == baseline.COMMON
    assert _HEADER["team_only"] == baseline.TEAM_ONLY
    assert _HEADER["eras"] == dict(baseline.ERAS)


def test_the_baseline_covers_the_whole_corpus():
    # Read the corpus directly rather than through _harness.load_corpus, which samples
    # and shards: every shard should check the baseline covers all of it, not an eighth.
    missing = [record["name"] for record in baseline.load_records()
               if record["name"] not in _ROWS]
    assert missing == [], "%d corpus records have no baseline entry" % len(missing)


@pytest.mark.parametrize("record", [pytest.param(record, id=record["name"])
                                    for record in _harness.load_corpus()])
def test_corpus_record_values(record):
    expected = _ROWS[record["name"]]["values"]
    names = baseline.tiebreaks_for(record["category"])
    for era, startdate in baseline.ERAS:
        got, broken = baseline.column_digests(record["trf"], startdate, names)
        if got == expected[era]:
            continue
        mine = baseline.split(got, names)
        theirs = baseline.split(expected[era], names)
        moved = [name for name in names if mine[name] != theirs[name]]
        pytest.fail(
            "%s: tie-break values changed under the %s rules (start date %s).\n"
            "  moved: %s\n"
            "  tie-breaks that raised: %s\n"
            "  If the change is intended, regenerate the baseline with\n"
            "    python tests/corpus/regen_tiebreak_values.py\n"
            "  and record in the commit message which tie-breaks moved and why."
            % (record["name"], era, startdate, ", ".join(moved) or "(none - digest only)",
               ", ".join(broken) or "none"))
