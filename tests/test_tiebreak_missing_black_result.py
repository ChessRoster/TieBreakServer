# -*- coding: utf-8 -*-
"""
Regression tests for tiebreak.prepare_result() on a ONE-SIDED game record.

trf2json builds a game record from one player's "001" row at a time, filling in only the
key for the colour that player had, and completes the record only when the opponent's own
row supplies the reciprocal half. A player whose row ends early -- a withdrawal -- leaves
a record with one half missing. Both halves can go missing, so both are covered here:

  * no "bResult" (the white player's row is the only one that ran that far), below; and
  * no "wResult" (the black player's row is the only one), further down.

prepare_result() already guarded the case where a real black player (black > 0) has
no "bResult" key -- but reported it by calling ``self.chessevent.put_status(451, err)``
followed by a bare ``raise``. tiebreak had no ``chessevent`` attribute at the time (it
holds one now, to reach chessjson's score lookups), so the put_status() call itself
raised AttributeError before the intended message was ever produced; and even if it had reached the bare ``raise``, that raises
"RuntimeError: No active exception to reraise" outside an except block. Either way the
diagnostic describing what was actually wrong with the input was destroyed.

Reached through the public entry point: constructing tiebreak.tiebreak() on a
non-team tournament calls prepare_competitors() -> prepare_result() for every game in
gameList, so a tournament with an incomplete game record crashes the moment tie-breaks
are computed for it, not from poking prepare_result() directly.
"""
import pytest

import errors
import tiebreak
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


def missing_black_result_round_two():
    # Player 2's row ends after round 1, as if they withdrew. Player 1's row
    # continues into round 2, playing white against player 2 -- who has no round-2
    # entry at all. Only one side of that round-2 game is ever recorded: white=1,
    # black=2, wResult set, no bResult.
    lines = ["012 Missing black result test", "042 2026-03-01", "XXR 2"]
    lines.append(player_line(1, "One, Player", 2000, "2.0", [(2, "w", "1"), (2, "w", "1")]))
    lines.append(player_line(2, "Two, Player", 1900, "0.0", [(1, "b", "0")]))
    return lines


def build_tournament():
    chessfile = trf2json.trf2json()
    chessfile.parse_file("\n".join(missing_black_result_round_two()), True)
    return chessfile.get_tournament(1)


def test_computing_tiebreaks_reports_the_missing_result_cleanly():
    tournament = build_tournament()
    # trf2json itself parses this fine -- get_score("black") is never called because
    # "bResult" not in result, so nothing crashes until tie-breaks are computed.
    round_two = next(g for g in tournament["gameList"] if g["round"] == 2)
    assert "bResult" not in round_two

    params = {"tiebreak": ["PTS"], "check": False, "unrated": None}
    with pytest.raises(errors.GacruxInputError) as excinfo:
        tiebreak.tiebreak(tournament, -1, params)

    # Not AttributeError ("'tiebreak' object has no attribute 'chessevent'") and not
    # "RuntimeError: No active exception to reraise" -- a message that actually
    # describes the malformed record.
    assert "No active exception" not in str(excinfo.value)
    assert "chessevent" not in str(excinfo.value)
    assert "black" in str(excinfo.value)
    assert "round 2" in str(excinfo.value)


def test_a_complete_game_record_still_computes_tiebreaks():
    lines = ["012 Complete game, control", "042 2026-03-01", "XXR 1"]
    lines.append(player_line(1, "One, Player", 2000, "1.0", [(2, "w", "1")]))
    lines.append(player_line(2, "Two, Player", 1900, "0.0", [(1, "b", "0")]))
    chessfile = trf2json.trf2json()
    chessfile.parse_file("\n".join(lines), True)
    tournament = chessfile.get_tournament(1)

    params = {"tiebreak": ["PTS"], "check": False, "unrated": None}
    tb = tiebreak.tiebreak(tournament, -1, params)
    result = tb.compute_tiebreaks(tournament, params)
    scores = {cmp["cid"]: cmp["tiebreakScore"] for cmp in result["competitors"]}
    assert scores[1][0] == 1
    assert scores[2][0] == 0


def bresult_only_round_two():
    """The mirror of missing_black_result_round_two(): player 1 withdraws instead.

    Player 1's row ends after round 1. Player 2's row runs on into round 2, playing
    Black against player 1 -- who has no round-2 entry of their own. The resulting
    round-2 record is white=1, black=2 with "bResult" set and no "wResult" at all.
    """
    lines = ["012 One-sided result test", "042 2026-03-01", "XXR 2"]
    lines.append(player_line(1, "One, Player", 2000, "1.0", [(2, "w", "1")]))
    lines.append(player_line(2, "Two, Player", 1900, "1.0", [(1, "b", "0"), (1, "b", "1")]))
    return lines


def test_pts_handles_bresult_only_game():
    """PTS must complete, and be right, on a game recorded only from Black's side.

    tiebreak carried its own copies of get_score() and is_vur(), and both read
    ``self.reverse`` -- a lookup table that belongs to chessjson and that the tiebreak
    class never defined. Reaching the branch that needs it therefore raised a bare
    ``AttributeError: 'tiebreak' object has no attribute 'reverse'`` rather than any
    diagnostic, and the GacruxInputError guard in prepare_result() could not help: it
    tests for a missing "bResult", and here "bResult" is the half that IS present.

    The points are derived, not read from the "001" totals: prepare_result() builds each
    competitor's per-round record from the game list, so player 1's round-2 score has to
    come from reversing Black's result.

      round 1: 1 (White) beats 2          -> 1 scores 1.0, 2 scores 0.0
      round 2: 2 (Black) beats 1          -> recorded as bResult "W" only;
                                             White's half is reverse["W"] = "L" = 0.0
      totals:  player 1 = 1.0 + 0.0 = 1.0
               player 2 = 0.0 + 1.0 = 1.0

    Both totals agree with the players' own reported "001" points, so a wrong reversal
    (scoring the round-2 game for White as well) would show up as 2.0 for player 1.
    """
    chessfile = trf2json.trf2json()
    chessfile.parse_file("\n".join(bresult_only_round_two()), True)
    tournament = chessfile.get_tournament(1)

    round_two = next(g for g in tournament["gameList"] if g["round"] == 2)
    assert round_two["bResult"] == "W"
    assert "wResult" not in round_two

    params = {"tiebreak": ["PTS"], "check": False, "unrated": None}
    tb = tiebreak.tiebreak(tournament, -1, params)
    result = tb.compute_tiebreaks(tournament, params)

    scores = {cmp["cid"]: cmp["tiebreakScore"] for cmp in result["competitors"]}
    ranks = {cmp["cid"]: cmp["rank"] for cmp in result["competitors"]}
    # The standings are complete: every competitor got a score and a rank.
    assert sorted(scores) == [1, 2]
    assert scores[1][0] == 1
    assert scores[2][0] == 1
    assert sorted(ranks.values()) == [1, 1]


def test_pts_handles_wresult_only_game():
    """The mirrored one-sided record -- only "wResult" -- is a typed input error.

    This pins an ASYMMETRY, deliberately, so that it is on the record rather than
    accidental. A record missing "wResult" is recovered (test_pts_handles_bresult_only_game
    above); a record missing "bResult" is rejected by the GacruxInputError guard in
    prepare_result(), because a competitor entry for Black is built unconditionally from
    ``rst["bResult"]`` further down. Both records come from the same cause -- a withdrawn
    player leaving half a game behind -- so whether the file is accepted currently depends
    on which colour the withdrawing player had.

    What this test guarantees is the part that is not in doubt: the failure is the typed
    GacruxInputError naming the round and the colour, never an untyped AttributeError or
    KeyError leaking out of the score lookup. If the asymmetry is later resolved in favour
    of recovering both halves, this test is the one to change, and the message assertions
    below say exactly what a reader would be giving up.
    """
    tournament = build_tournament()
    round_two = next(g for g in tournament["gameList"] if g["round"] == 2)
    assert round_two["wResult"] == "W"
    assert "bResult" not in round_two

    params = {"tiebreak": ["PTS"], "check": False, "unrated": None}
    with pytest.raises(errors.GacruxInputError) as excinfo:
        tiebreak.tiebreak(tournament, -1, params)

    assert "black" in str(excinfo.value)
    assert "round 2" in str(excinfo.value)
