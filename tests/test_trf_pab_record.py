# -*- coding: utf-8 -*-
"""TRF-2026 record 320, the pairing-allocated-bye section.

Record 320 states what a pairing-allocated bye is worth and names the team
that received one in each round:

    320 1.0  1.0    1

reads as "a PAB is worth 1.0 match points and 1.0 game points, and in round 1
it went to team 1". Its points reach the score system, and the bye it declares
reaches the match list, so the record decides a team's score and therefore its
scoregroup and tie-breaks. It is not decoration.

Record 320 is team-only; an individual tournament must reject it clearly.

No fixture in the TRF corpus carries it: corpus fixtures are written out of the
engine's own JSON, and record 320 has no writer. These unit tests therefore hold
the path directly.

Records 240 and 320 both feed ``self.byelist`` and its match-building consumers,
so their entries must have the same core shape. Record 240 carries the result
letter under both ``wResult`` and ``score``; record 320 does the same for its
``P`` result.
"""
import pytest

import trf2json

# The column layouts the two parsers read, spelled out so the tests are not a
# row of magic strings. Record 240 (parse_trf_bye, idsize 4): the bye letter in
# column 4, the round in 6-8, then pairing numbers four wide from column 10.
# Record 320 (parse_trf_pab): match points in 4-7, game points in 9-12, then
# pairing numbers three wide from column 14, one per round in turn.
RECORD_240_FOR_PLAYER_1 = "240 H   1    1"
RECORD_320_FOR_TEAM_1 = "320 1.0  1.0    1"


def fixture_lines():
    """The eight-player, two-round tournament used across the reader tests.

    Every player has a game in both rounds and the declared totals reconcile, so
    anything that goes wrong below is the record under test and not the file.
    """
    with open("tests/fixtures/no_colour_preference.trf", encoding="latin1") as handle:
        return handle.read().rstrip("\n").split("\n")


def read(extra_lines, verbose=False):
    chessfile = trf2json.trf2json()
    chessfile.parse_file("\n".join(fixture_lines() + extra_lines), verbose)
    return chessfile


def read_team(extra_lines, verbose=False):
    with open("tests/fixtures/fideteam_nocolor.trf", encoding="latin1") as handle:
        chessfile = trf2json.trf2json()
        chessfile.parse_file(handle.read() + "\n" + "\n".join(extra_lines), verbose)
    return chessfile


def test_record_320_is_rejected_in_an_individual_tournament():
    with pytest.raises(trf2json.GacruxInputError) as excinfo:
        read([RECORD_320_FOR_TEAM_1])

    assert "Record 320" in str(excinfo.value)
    assert "team tournament" in str(excinfo.value)


def test_a_record_240_that_contradicts_a_black_game_is_reported_as_a_bye_score_error():
    """Player 1 is Black in round 1, so the check must compare ``bResult``."""
    chessfile = read([RECORD_240_FOR_PLAYER_1])
    status = chessfile.chessjson["status"]
    assert status["code"] == 405
    assert any("competitor 1" in message for message in status["error"])


def test_the_bye_list_entries_of_records_240_and_320_carry_the_same_keys():
    """The two records feed one consumer, so they have to agree on the shape.

    The individual and team consumers read the same core keys. This asserts the
    agreement directly, so that a future record writing to the list is measured
    against the shared contract rather than whichever consumer happens to run.

    The result letter of a pairing-allocated bye is "P": record 320 states the
    points a PAB is worth, and "P" is the score system's name for them.
    """
    from_240 = read([RECORD_240_FOR_PLAYER_1]).byelist
    from_320 = read_team([RECORD_320_FOR_TEAM_1]).byelist

    assert len(from_240) == 1 and len(from_320) == 1
    required = {"type", "competitor", "round", "score", "wResult"}
    assert required <= set(from_240[0])
    assert required <= set(from_320[0])

    assert from_320[0]["round"] == 1
    assert from_320[0]["competitor"] == 1
    assert from_320[0]["score"] == "P"
    assert from_320[0]["wResult"] == "P"


def test_a_record_320_naming_nobody_adds_no_bye():
    """The points half of the record without a competitor half.

    The loop that reads the pairing numbers starts past the two point fields, so
    a record that stops after them names no competitor and there is no bye to
    add. It still declares what a PAB is worth, so it is not an error.
    """
    assert read_team(["320 1.0  1.0"]).byelist == []
