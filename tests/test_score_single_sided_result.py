# -*- coding: utf-8 -*-
"""
Regression test for chessjson.get_score() / is_vur() on a one-sided game record.

Both methods branch on the presence of "<colour>Result" in the result dict:

    if color[0] + "Result" in result:
        res = result[color[0] + "Result"]
    elif result["black"] > 0:
        res = self.reverse[result[color[0] + "Result"]]   # same missing key -- KeyError

The elif is only reached when that exact key is already known to be absent, so the
old code read it anyway and crashed. This is reachable through public TRF parsing,
not just by poking the dict by hand: trf2json.parse_trf_game() builds a game record
from only one side's perspective at a time --

    if color == "b":
        game["bResult"] = points
    else:
        game["wResult"] = points

-- and append_result() only fills in the other side's key when a second, reciprocal
record for the same (round, white) pair shows up from the *other* player's own "001"
row. A player whose row ends early (e.g. they withdrew) leaves no such reciprocal
record, so a game where they were named as an opponent by someone else keeps only
that someone else's half. trf2json.parse_file() calls update_board_number() on every
individual tournament, which calls get_score() unconditionally for "white" on every
game -- so this crashes on ordinary parsing, not just on tie-break computation.

Reaching self.reverse is only half of the contract. The other half is that it has an
entry for the letter it is handed. self.reverse was written in the alphabet of the TRF
result column -- it keys "U" and "A", the codes of a 001 record -- while the letters that
reach it are the ones trf2json.parse_trf_game() stores, which are the *score system's*
letters. The two alphabets are not the same one: the reader translates the TRF code "U",
a pairing-allocated bye, into the score-system letter "P", and "P" was not a key of
self.reverse at all. Guarding the elif turned a certain KeyError into a narrower one
rather than removing it.
"""
import decimal

import pytest

import trf2json


def player_line(startno, name, rating, points, games):
    line = "001 "
    line += "%4d " % startno                 # start number
    line += "m    "                          # sex + title
    line += "%-33s " % name                  # name
    line += "%4d " % rating                  # rating
    line += "NOR "                           # federation
    line += "%11d " % 0                      # fide id
    line += "1990/01/01 "                    # birth date
    line += "%4s " % points                  # points
    line += "%4d  " % startno                # rank
    return line + "  ".join(["%4d %s %s" % game for game in games])


def one_sided_round_two(result="1", points="1.0"):
    # Player 1's row ends after round 1, as if they withdrew. Player 2's row
    # continues into round 2, playing black against player 1 -- who has no round-2
    # entry at all. Only one side of that round-2 game is ever recorded: white=1,
    # black=2, bResult set, no wResult.
    #
    # "result" is what player 2's round-2 column says and "points" is the total their
    # 001 record then declares; the two have to agree or the reader cannot solve the
    # score system, and the file fails for a reason that has nothing to do with this.
    lines = ["012 One-sided result test", "042 2026-03-01", "XXR 2"]
    lines.append(player_line(1, "One, Player", 2000, "1.0", [(2, "w", "1")]))
    lines.append(player_line(2, "Two, Player", 1900, points, [(1, "b", "0"), (1, "b", result)]))
    return lines


def test_parsing_a_one_sided_game_record_does_not_crash():
    chessfile = trf2json.trf2json()
    chessfile.parse_file("\n".join(one_sided_round_two()), True)

    assert chessfile.get_status() == 0
    tournament = chessfile.get_tournament(1)
    games = {(game["round"], game["white"], game["black"]): game for game in tournament["gameList"]}

    round_two = games[(2, 1, 2)]
    assert round_two["bResult"] == "W"
    assert "wResult" not in round_two


def test_one_sided_game_still_reports_a_score_for_the_recorded_side():
    # get_score() itself, exercised through the public entry point: a competitor's
    # own points total must still come out right even though only their opponent's
    # half of the round-2 game was ever recorded.
    chessfile = trf2json.trf2json()
    chessfile.parse_file("\n".join(one_sided_round_two()), True)
    tournament = chessfile.get_tournament(1)

    competitor_two = next(c for c in tournament["competitors"] if c["cid"] == 2)
    # Player 2 lost round 1 (0 points) then won round 2 (1 point) -- reported directly
    # off their own "001" row, unaffected by the one-sided game record.
    assert competitor_two["gamePoints"] == 1


@pytest.mark.parametrize(
    "trfresult, letter, points, whitescore",
    [
        ("F", "W", "1.0", "0.0"),   # forfeit win                 -> W, reversed to L
        ("+", "W", "1.0", "0.0"),   # forfeit win, other spelling -> W, reversed to L
        ("H", "D", "0.5", "0.5"),   # half-point bye              -> D, reversed to D
        ("U", "P", "1.0", "0.0"),   # pairing-allocated bye       -> P, reversed to Z
    ],
    ids=["F", "+", "H", "U"],
)
def test_one_sided_result_row_parses(trfresult, letter, points, whitescore):
    """A one-sided row parses whatever unplayed result it carries, and the side that
    was never recorded gets the score the reversed result is worth.

    TRF-2026 gives the result column of a 001 record one letter per game, and the
    unplayed ones are among them: "F" (and its older spelling "+") a forfeit win, "H" a
    half-point bye, "U" a pairing-allocated bye. trf2json.parse_trf_game() looks each one
    up in self.results and stores the *score system's* letter for it -- W, D and P
    respectively -- so "P" is a letter the reader produces and no TRF file ever contains.

    Each case here is the withdrawal above with that letter in player 2's round-2 column
    and nothing at all in player 1's, which is the shape that leaves a game with black > 0
    and only "bResult". Asking for White's score is what update_board_number() does for
    every game of every individual tournament as the file is read, and it is the call that
    goes through self.reverse. The parse completing at all is the first assertion; the
    second is that the letter reached the game record intact, and the third that the
    reverse of it is worth what the score system says -- 0 for the loss the forfeit win
    reverses to, half a point for the draw the half-point bye reverses to, and 0 for the
    zero-point bye a pairing-allocated bye leaves the phantom opponent with. A reverse map
    missing a letter fails the first of those with KeyError, and a map that guesses wrong
    fails the last.
    """
    chessfile = trf2json.trf2json()
    chessfile.parse_file("\n".join(one_sided_round_two(trfresult, points)), True)

    assert chessfile.get_status() == 0
    tournament = chessfile.get_tournament(1)
    games = {(game["round"], game["white"], game["black"]): game for game in tournament["gameList"]}

    round_two = games[(2, 1, 2)]
    assert round_two["bResult"] == letter
    assert "wResult" not in round_two
    assert chessfile.get_score(tournament["scoreSystem"]["game"], round_two, "white") == decimal.Decimal(whitescore)


def test_reverse_is_defined_for_every_result_letter():
    """self.reverse has to answer for every letter a game record can carry.

    The letters a game record carries are the keys of the score system: the played
    results W, D and L, and the unplayed ones F (forfeit win), H (half-point bye), Z
    (zero-point bye or forfeit loss), P (pairing-allocated bye), A (adjourned or unknown)
    and U. Which of them a given file uses is the file's business -- record 162 states
    the points of each, chessjson.default_score states the values when it does not -- and
    a JSON event handed to the engine directly may carry any of them, because the schema
    calls "wResult" a string and leaves the vocabulary to the score system.

    So the score system's own alphabet is the right yardstick, and this asserts the map
    covers all of it. Pinning it against default_score rather than against a list written
    out here means a letter added to the score system later fails this test instead of
    reaching self.reverse as a KeyError from inside a tie-break.
    """
    reader = trf2json.trf2json()

    assert set(reader.default_score["game"]) <= set(reader.reverse)
    assert set(reader.default_score["match"]) - {"FG", "HG", "ZG", "PG"} <= set(reader.reverse)

    # A forfeit win is a win the opponent did not turn up for, so the opponent forfeited:
    # the mirror of the "Z" -> "W" the map already had.
    assert reader.reverse["F"] == "Z"
    # A half-point bye is an unplayed half point for each side, the unplayed counterpart
    # of the "D" -> "D" the map already had.
    assert reader.reverse["H"] == "H"
    # A pairing-allocated bye is a game with no opponent at all. When a record names one
    # anyway, that opponent played nothing and scored nothing.
    assert reader.reverse["P"] == "Z"
