# -*- coding: utf-8 -*-
"""Unit tests for trftrunc.truncate(). See this directory's README.md, "The
truncation transform", for the specification. Covers: column arithmetic,
points/rank recomputation, record 142 preservation, ``keep_rounds == 0``, the
full-length case (identity on points, not necessarily on rank -- see
trftrunc.truncate's own docstring), and filtering per-round records
(240/300/320/330) to rounds <= keep_rounds.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import trftrunc  # noqa: E402


def player_line(cid, name, points, rank, rounds):
    """Build one record-001 line with the exact TRF-2026 column layout, the
    same widths trf2json.output_trf_player writes: startno at [4:8], points
    at [80:84], rank at [85:89], round blocks of 10 chars from [89:] on."""
    line = (
        "001 "
        + f"{cid:>4} "
        + "m"
        + "   "
        + " "
        + f"{name:<33}"
        + " "
        + f"{0:>4}"
        + " "
        + f"{'':<3}"
        + " "
        + f"{'':>11}"
        + " "
        + f"{'':>10}"
        + " "
        + f"{points:>4.1f}"
        + " "
        + f"{rank:>4}"
    )
    for opp, col, res in rounds:
        opp_field = "0000" if opp == 0 else f"{opp:>4}"
        line += "  " + opp_field + " " + col + " " + res
    return line


def two_player_trf(numrounds=2):
    # Player 1 beats player 2 in round 1, draws in round 2.
    l1 = player_line(1, "A, A", 1.5, 1, [(2, "w", "1"), (2, "w", "=")])
    l2 = player_line(2, "B, B", 0.5, 2, [(1, "b", "0"), (1, "b", "=")])
    return "\n".join(["142 %d" % numrounds, "152 W", l1, l2]) + "\n"


def _player_lines(text):
    return {line[4:8].strip(): line for line in text.split("\n") if line[:3] == "001"}


def _points(line):
    return line[80:84].strip()


def _rank(line):
    return line[85:89].strip()


# -- column arithmetic -------------------------------------------------------


def test_round_block_truncated_to_exact_column():
    text = two_player_trf()
    out = trftrunc.truncate(text, 1)
    players = _player_lines(out)
    # 89 + 10*1 = 99 characters kept: header plus exactly one round block.
    assert len(players["1"]) == 99
    assert players["1"].endswith("2 w 1")


def test_keep_rounds_zero_drops_all_round_blocks():
    text = two_player_trf()
    out = trftrunc.truncate(text, 0)
    players = _player_lines(out)
    for line in players.values():
        assert len(line) == 89


# -- points / rank recomputation ---------------------------------------------


def test_points_recomputed_from_surviving_rounds_only():
    text = two_player_trf()
    out = trftrunc.truncate(text, 1)
    players = _player_lines(out)
    assert _points(players["1"]) == "1.0"  # only the round-1 win counts now
    assert _points(players["2"]) == "0.0"


def test_points_recomputed_to_zero_at_keep_rounds_zero():
    text = two_player_trf()
    out = trftrunc.truncate(text, 0)
    players = _player_lines(out)
    assert _points(players["1"]) == "0.0"
    assert _points(players["2"]) == "0.0"


def test_rank_reflects_recomputed_points_order():
    text = two_player_trf()
    out = trftrunc.truncate(text, 1)
    players = _player_lines(out)
    # Player 1 (1.0) now strictly outranks player 2 (0.0).
    assert int(_rank(players["1"])) < int(_rank(players["2"]))


def test_rank_ties_share_a_rank():
    text = two_player_trf()
    out = trftrunc.truncate(text, 0)  # both players at 0.0 points
    players = _player_lines(out)
    assert _rank(players["1"]) == _rank(players["2"])


def test_points_recomputation_uses_the_files_declared_score_system():
    # A 3/1/0 match-point-style game score via record 162 changes what a win
    # is worth; recomputation must follow it rather than assuming 1/0.5/0.
    l1 = player_line(1, "A, A", 3.0, 1, [(2, "w", "1")])
    l2 = player_line(2, "B, B", 0.0, 2, [(1, "b", "0")])
    text = "\n".join(
        ["142 1", "152 W", "162  W 3.0    D 1.0    L 0.0    A 0.0    P 1.5    X 0.0", l1, l2]
    ) + "\n"
    out = trftrunc.truncate(text, 1)
    players = _player_lines(out)
    assert _points(players["1"]) == "3.0"
    assert _points(players["2"]) == "0.0"


# -- record 142 (scheduled round count) is never rewritten -------------------


def test_record_142_preserved_verbatim():
    text = two_player_trf(numrounds=7)
    for keep_rounds in (0, 1, 2):
        out = trftrunc.truncate(text, keep_rounds)
        assert "142 7" in out.split("\n")
        # And it is not silently dropped to "142 %d" % keep_rounds either.
        assert ("142 %d" % keep_rounds) not in out.split("\n") or keep_rounds == 7


# -- 152 / other untouched records pass through unchanged --------------------


def test_untouched_records_pass_through():
    text = two_player_trf()
    out = trftrunc.truncate(text, 1)
    assert "152 W" in out.split("\n")


# -- full-length truncation is the identity transform -------------------------


def test_full_length_truncation_is_identity():
    text = two_player_trf(numrounds=2)
    out = trftrunc.truncate(text, 2)
    assert out == text


def test_full_length_truncation_is_identity_on_a_larger_fixture():
    # A few more players and rounds, still hand-built so the test has no
    # dependency on the corpus.
    lines = ["142 3", "152 B"]
    rounds_by_player = {
        1: [(2, "w", "1"), (3, "w", "="), (4, "w", "0")],
        2: [(1, "b", "0"), (4, "b", "1"), (3, "b", "=")],
        3: [(4, "w", "="), (1, "b", "="), (2, "w", "=")],
        4: [(3, "b", "="), (2, "w", "0"), (1, "b", "1")],
    }
    points = {1: 1.5, 2: 1.5, 3: 1.5, 4: 1.5}
    for cid in (1, 2, 3, 4):
        # All four tie on points, so the recomputed rank (tie-broken by
        # starting rank) is 1 for everyone -- matching that here is what
        # makes this the identity transform.
        lines.append(player_line(cid, "P%d, P%d" % (cid, cid), points[cid], 1, rounds_by_player[cid]))
    text = "\n".join(lines) + "\n"
    out = trftrunc.truncate(text, 3)
    assert out == text


# -- keep_rounds validation ----------------------------------------------------


def test_negative_keep_rounds_rejected():
    text = two_player_trf()
    try:
        trftrunc.truncate(text, -1)
    except ValueError:
        pass
    else:
        assert False, "expected ValueError for a negative keep_rounds"


# -- per-round records (240 / 300 / 320 / 330) are filtered, not just carried --
#
# The present corpus carries none of these records at all, so these are
# hand-built rather than corpus-derived.


def test_record_240_bye_filtered_by_round():
    # Bye type 'Z' (zero-point bye), round at line[6:9], competitor list after.
    text = two_player_trf(numrounds=3) + "240 Z   1  003\n" + "240 Z   3  003\n"
    out = trftrunc.truncate(text, 1)
    kept = [line for line in out.split("\n") if line[:3] == "240"]
    assert kept == ["240 Z   1  003"]


def test_record_300_out_of_order_filtered_by_round():
    # Out-of-order record: round at line[4:7].
    text = two_player_trf(numrounds=3) + "300   1   5   6\n" + "300   3   5   6\n"
    out = trftrunc.truncate(text, 2)
    kept = [line for line in out.split("\n") if line[:3] == "300"]
    assert kept == ["300   1   5   6"]


def test_record_330_forfeited_filtered_by_round():
    # Forfeited match: round at line[7:10].
    text = two_player_trf(numrounds=3) + "330 WL   1   5   6\n" + "330 WL   3   5   6\n"
    out = trftrunc.truncate(text, 1)
    kept = [line for line in out.split("\n") if line[:3] == "330"]
    assert kept == ["330 WL   1   5   6"]


# -- a pre-declared exemption in the round about to be paired survives -------
#
# A player's requested/forced bye for a round not yet played is known and
# written into the file in advance of that round -- opponent "0000" with a
# non-blank result code sitting in that round's own column block. Dropping it
# along with the rest of the not-yet-played rounds loses information the
# pairing engine needs to correctly pair that round: the C.04.3 self-validation
# gate (this engine's own -c oracle vs. -p on the truncated file) caught this.


def test_pair_round_exemption_survives_truncation():
    # Player 2 has a pre-declared half-point bye ("H") in round 2. Truncating
    # to pair round 2 (keep_rounds=1) must keep that round-2 slot even though
    # round 2 has not been "played" in the ordinary sense.
    l1 = player_line(1, "A, A", 1.0, 1, [(2, "w", "1"), (0, "-", " ")])
    l2 = player_line(2, "B, B", 0.5, 2, [(1, "b", "0"), (0, "-", "H")])
    text = "\n".join(["142 2", "152 W", l1, l2]) + "\n"
    out = trftrunc.truncate(text, 1)
    players = _player_lines(out)
    # Player 1's round-2 slot carries no exemption, so it is dropped as usual.
    assert len(players["1"]) == 99
    # Player 2's round-2 slot is a pre-declared exemption, so it survives.
    assert len(players["2"]) == 109
    assert players["2"].endswith("0000 - H")


def test_pair_round_exemption_points_folded_into_declared_total():
    # This repository's own reader (scoresystem.py) sums every result
    # character present anywhere in the line -- not just through the current
    # round -- against the declared points field ("Incorrect score for
    # player" otherwise). So a preserved exemption's points must be folded
    # into the recomputed total, or the truncated file fails to reconcile
    # even though the exemption itself is legitimately present.
    l1 = player_line(1, "A, A", 1.0, 1, [(2, "w", "1"), (0, "-", " ")])
    l2 = player_line(2, "B, B", 0.5, 2, [(1, "b", "0"), (0, "-", "H")])
    text = "\n".join(["142 2", "152 W", l1, l2]) + "\n"
    out = trftrunc.truncate(text, 1)
    players = _player_lines(out)
    assert _points(players["2"]) == "0.5"


def test_pairing_allocated_bye_result_not_preserved():
    # 'U' (pairing-allocated bye) in round k's own slot is the *output* of
    # pairing round k -- exactly what's being asked for -- not a fact known
    # in advance of it. the external reader treats 'U' (and '+', a
    # forfeit win) as advancing how many rounds the file has "played", so
    # preserving either makes the external engine pair the round *after* the one
    # being asked about. Confirmed against a real corpus divergence: this
    # was previously misclassified as a pre-declared exemption and inflated
    # the interop sweep's divergence rate to ~40-50%.
    l1 = player_line(1, "A, A", 1.0, 1, [(2, "w", "1"), (0, "-", " ")])
    l2 = player_line(2, "B, B", 0.5, 2, [(1, "b", "0"), (0, "-", "U")])
    text = "\n".join(["142 2", "152 W", l1, l2]) + "\n"
    out = trftrunc.truncate(text, 1)
    players = _player_lines(out)
    assert len(players["2"]) == 99
    assert _points(players["2"]) == "0.0"


def test_forfeit_win_result_not_preserved():
    l1 = player_line(1, "A, A", 1.0, 1, [(2, "w", "1"), (0, "-", " ")])
    l2 = player_line(2, "B, B", 1.0, 2, [(1, "b", "0"), (0, "-", "+")])
    text = "\n".join(["142 2", "152 W", l1, l2]) + "\n"
    out = trftrunc.truncate(text, 1)
    players = _player_lines(out)
    assert len(players["2"]) == 99
    assert _points(players["2"]) == "0.0"


def test_real_game_opponent_never_preserved_past_keep_rounds():
    # opponent != "0000" is always dropped for a not-yet-played round, no
    # matter what the result byte holds -- only "0000" is unambiguous.
    l1 = player_line(1, "A, A", 1.0, 1, [(2, "w", "1"), (2, "w", "1")])
    l2 = player_line(2, "B, B", 0.0, 2, [(1, "b", "0"), (1, "b", "0")])
    text = "\n".join(["142 2", "152 W", l1, l2]) + "\n"
    out = trftrunc.truncate(text, 1)
    players = _player_lines(out)
    assert len(players["1"]) == 99
    assert len(players["2"]) == 99


def test_record_320_pab_slots_truncated_by_round():
    # PAB record: matchPoints [4:8], gamePoints [9:13], then one 4-column
    # (3-digit competitor + separator) slot per round starting at column 17.
    text = two_player_trf(numrounds=3) + "320 1.0  0.5  003  000  005\n"
    out = trftrunc.truncate(text, 1)
    kept = [line for line in out.split("\n") if line[:3] == "320"]
    assert len(kept) == 1
    # 13 + 4*1 = 17 characters kept: header plus exactly round 1's slot.
    assert len(kept[0]) == 17
    assert kept[0] == "320 1.0  0.5  003"
