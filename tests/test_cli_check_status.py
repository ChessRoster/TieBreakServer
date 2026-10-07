# -*- coding: utf-8 -*-
"""Check-mode status codes for the four combinations of analysis and pairing.

    -c          compares the declared and prescribed pairings
    -c -a -p    compares the declared and prescribed pairings
    -c -a       computes only the declared pairing; suppresses the verdict
    -c -p       computes only the prescribed pairing; suppresses the verdict

The old expression ``dopairing > 0 ^ doanalysis > 0`` parsed as a chained
comparison because XOR binds more tightly than comparisons. It was false for
all four 0/1 flag combinations, so one-sided runs incorrectly reported status 1.
These tests retain status 1 for actual differences in two-sided runs.

The fixture's two played rounds match the engine's prescribed pairings.
"""
import contextlib
import io
import os
import sys

import pytest

from gacrux import pairingchecker

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "no_colour_preference.trf")

# The four ways of asking `-c` for a verdict. The first two compare two computed sides;
# the last two have only one side and therefore no difference to report.
MODES = [
    pytest.param([], id="check"),
    pytest.param(["-p", "-a"], id="check-pairing-analysis"),
    pytest.param(["-p"], id="check-pairing"),
    pytest.param(["-a"], id="check-analysis"),
]

TWO_SIDED = [
    pytest.param([], id="check"),
    pytest.param(["-p", "-a"], id="check-pairing-analysis"),
]


def check(options, path=FIXTURE):
    """Run the real checker in check mode and return the status code it reports."""
    checker = pairingchecker.pairingchecker()
    saved = sys.argv
    sys.argv = ["pairingchecker", "-i", path, "-c"] + options
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                checker.common_main()
            except SystemExit:
                pass
    finally:
        sys.argv = saved
    return checker.resultjson.get("status", {}).get("code")


@pytest.mark.parametrize("options", MODES)
def test_check_with_pairing_exits_zero_on_a_matching_round(options):
    """All four modes report status 0 for a file whose rounds match."""
    assert check(options) == 0


def a_round_two_the_engine_pairs_the_other_way_round(tmp_path):
    """The fixture with the colours of one round-two pair the wrong way round.

    Players 1 and 4 drew in round two, 1 with White. Declaring the same game as 4-1
    leaves every result, every score and every board untouched, so the file still reads
    and still ranks the same way, but the pairing it declares is no longer the pairing
    the engine prescribes: the comparison has a real difference in it.
    """
    with open(FIXTURE, encoding="latin1") as handle:
        trf = handle.read()
    trf = trf \
        .replace("1.5    0     5 b 1     4 w =", "1.5    0     5 b 1     4 b =") \
        .replace("1.5    0     8 w 1     1 b =", "1.5    0     8 w 1     1 w =")
    path = tmp_path / "swapped.trf"
    path.write_text(trf, encoding="latin1")
    return str(path)


@pytest.mark.parametrize("options", TWO_SIDED)
def test_a_round_that_does_not_match_is_still_reported_as_a_difference(options, tmp_path):
    """Two-sided checks report status 1 for a changed pairing.

    One-sided modes suppress the verdict because they cannot compare the round.
    """
    path = a_round_two_the_engine_pairs_the_other_way_round(tmp_path)

    assert check(options + ["-n", "2"], path) == 1


@pytest.mark.parametrize("options", TWO_SIDED)
def test_an_exchanged_round_is_reported_as_a_difference(options):
    """`-T` rewrites the declared pairs of the round being checked.

    Round two of the fixture is 1-4 and 3-2. `-T 1-2 3-4` declares it as 1-2 and 3-4
    instead, the same four players with other opponents, which is not the pairing the
    engine prescribes. Both two-sided modes have to apply the exchange and report the
    round as a difference (status 1), not refuse the exchange as malformed (status 410).
    """
    assert check(options + ["-n", "2", "-T", "1-2", "3-4"]) == 1


@pytest.mark.parametrize("options", TWO_SIDED)
def test_an_exchange_that_undoes_a_swap_is_reported_as_a_match(options, tmp_path):
    """The reverse case: round two of the swapped file declares 4-1, and `-T 1-4` puts
    the pair back the way the engine prescribes it, so the round matches (status 0)."""
    path = a_round_two_the_engine_pairs_the_other_way_round(tmp_path)

    assert check(options + ["-n", "2", "-T", "1-4"], path) == 0
