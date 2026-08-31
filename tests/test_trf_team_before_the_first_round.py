# -*- coding: utf-8 -*-
"""Reading a team tournament that has not played a round yet.

This is the ordinary input to pairing round 1: the teams are entered, the boards
are filled, and no result exists anywhere. With no matches, the reader cannot
infer the board count from played games. It must take that count from record 352,
whose colour sequence has one character per board.

Record 310 is not a substitute. It lists a team's squad, which may include
reserves: the official TRF example has four boards and five players. The reader
therefore leaves ``teamSize`` unknown when neither matches nor record 352 provide
it, and the pairing engine reports the missing declaration instead of guessing.
"""
import pytest

import errors
from pairingfideteam import pairing_fideteam
import trf2json


def team_file(*extra):
    """Two teams with two-player squads, no result, and caller-supplied records."""
    return "\n".join([
        "012 before the first round",
        "062 4",
        "072 4",
        "082 2",
        "142 3",
        "152 W",
        "001    1      Alpha Board1                     2000                             0.0    0",
        "001    2      Alpha Board2                     1900                             0.0    0",
        "001    3      Beta Board1                      1950                             0.0    0",
        "001    4      Beta Board2                      1850                             0.0    0",
        "310   1 Alpha                                    2000    0.0    0.0   1     1    2",
        "310   2 Beta                                     1900    0.0    0.0   2     3    4",
    ] + list(extra))


def read(text, verbose=0):
    chessfile = trf2json.trf2json()
    chessfile.parse_file(text, verbose)
    return chessfile


def test_a_team_event_with_no_results_and_record_352_reads():
    """An explicit board sequence supplies the size before the first round."""
    chessfile = read(team_file("352 WB"))
    assert chessfile.chessjson["status"]["code"] != 510


def test_no_result_team_event_does_not_infer_size_from_record_310_rosters():
    """Without matches or record 352, board count remains explicitly unknown."""
    tournament = read(team_file()).chessjson["event"]["tournaments"][0]
    assert tournament["teamSize"] == 0
    assert len(tournament["competitors"]) == 2


def test_pairing_reports_missing_record_352_instead_of_faulting():
    tournament = read(team_file()).chessjson["event"]["tournaments"][0]
    with pytest.raises(errors.GacruxInputError, match="record 352"):
        pairing_fideteam(tournament, 1, {"experimental": set()})


def test_a_declared_colour_sequence_is_still_honoured():
    """Record 352 states the board colours outright.

    The sequence supplies both the size and the first-board colour, so both are
    read back here.
    """
    tournament = read(team_file("352 WB")).chessjson["event"]["tournaments"][0]
    assert tournament["teamSequence"] == "WB"
    assert tournament["teamColor"] == "W"


def test_record_352_wins_over_a_five_player_roster():
    """The official example has four boards but five players on a team."""
    lines = team_file().split("\n")
    lines.insert(10, "001    5      Alpha Reserve                    1800                             0.0    0")
    lines[11] += "    3    4    5"
    tournament = read("\n".join(lines + ["352 WBWB"])).chessjson["event"]["tournaments"][0]
    assert len(tournament["competitors"][0]["cplayers"]) == 5
    assert tournament["teamSize"] == 4


def test_a_team_event_with_matches_still_sizes_itself_from_them():
    """The fix must not cost the ordinary case.

    When matches do exist the size still comes from them, by the average games
    per match the code has always used. The shipped team fixture is a played
    event, so it exercises that branch rather than the squad one above.
    """
    with open("tests/fixtures/fideteam_nocolor.trf", encoding="latin1") as handle:
        tournament = read(handle.read()).chessjson["event"]["tournaments"][0]
    assert tournament["teamSize"] > 0
    assert len(tournament["matchList"]) > 0
