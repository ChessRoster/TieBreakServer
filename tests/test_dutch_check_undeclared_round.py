# -*- coding: utf-8 -*-
"""Checking a Dutch round the file does not declare is not a program error.

The check reads each opponent's history to see who may meet. A round after the last
declared one has a history entry that is not a pairing number, and converting it with
int() raised ValueError (status 510). A non-numeric entry now means "cannot meet", like
the base crosstable, and no pairing is never reported as a successful check.
"""
import contextlib
import io
import sys

from gacrux import pairingchecker, trf2json
from gacrux.pairingdutch import pairing_dutch

# Four players, a complete round robin of three rounds, round 4 not declared. Player 1
# has met everybody, so round 4 has no legal pairing.
TRF = """012 Exhausted 4-player RR
042 2026-03-01
142 5
XXR 5
001    1 m    Player 1                          2390 NOR           0 1990/01/01  3.0    1     4 w 1     3 b 1     2 w 1
001    2 m    Player 2                          2380 NOR           0 1990/01/01  2.0    2     3 w 1     4 b 1     1 b 0
001    3 m    Player 3                          2370 NOR           0 1990/01/01  1.0    3     2 b 0     1 w 0     4 w 1
001    4 m    Player 4                          2360 NOR           0 1990/01/01  0.0    4     1 b 0     2 w 0     3 b 0
"""


def test_library_check_of_an_undeclared_round_does_not_raise():
    reader = trf2json.trf2json()
    reader.parse_file(TRF, True)
    params = {"experimental": [], "verbose": 0, "rank": False, "top_color": "w",
              "maxmeets": "0", "unpaired": []}
    engine = pairing_dutch(reader.get_tournament(1), 4, params)
    brackets = engine.compute_pairing(True, 0)
    assert all(bracket["pairs"] == [] for bracket in brackets)


def test_cli_check_of_an_undeclared_round_reports_a_failed_check(tmp_path):
    path = tmp_path / "rr4.trf"
    path.write_text(TRF, encoding="latin1")
    checker = pairingchecker.pairingchecker()
    saved = sys.argv
    sys.argv = ["pairingchecker", "-i", str(path), "-c"]
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                checker.common_main()
            except SystemExit:
                pass
    finally:
        sys.argv = saved
    assert checker.resultjson["status"]["code"] == 1
    assert checker.chessfile.result["check"] is False
