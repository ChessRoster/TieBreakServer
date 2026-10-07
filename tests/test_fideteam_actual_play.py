"""C.04.6 actual-play history and the public reproducer for issue #23.

The fixture retains Timothy Armes's original issue attachment unchanged:
https://github.com/OttoMilvang/TieBreakServer/issues/23
"""
import contextlib
import io
from decimal import Decimal
from pathlib import Path

import pytest

from gacrux.helpers import match_has_played_board
from gacrux.pairingchecker import pairingchecker
from gacrux.pairingfideteam import pairing_fideteam
from gacrux.tiebreak import tiebreak
from gacrux.trf2json import trf2json

FIXTURES = Path(__file__).parent / "fixtures"
PARAMS = {"experimental": [], "verbose": 0, "rank": False, "top_color": "w"}


def read(issue, text=None):
    reader = trf2json()
    reader.parse_file(text if text is not None else (FIXTURES / f"fideteam_issue{issue}.trf").read_text(), 0)
    return reader.get_tournament(1)


def pair(tournament, rnd=2):
    engine = pairing_fideteam(tournament, rnd, PARAMS)
    brackets = engine.compute_pairing(False)
    pairs = [pair for bracket in brackets for pair in bracket["pairs"]]
    return engine, brackets, pairs


def check(issue, rnd, monkeypatch):
    monkeypatch.setattr("sys.argv", ["pairingchecker", "-i", str(FIXTURES / f"fideteam_issue{issue}.trf"), "-c", "-n", str(rnd)])
    checker = pairingchecker()
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            checker.common_main()
        except SystemExit:
            pass
    return checker.resultjson


def test_issue23_all_forfeit_match_has_no_colour_and_uses_article_4_3_1(monkeypatch):
    tournament = read(23)
    match = next(m for m in tournament["matchList"] if m["round"] == 1 and m["white"]["cid"] == 1)
    assert match["played"] is True  # result-bearing cross-forfeit draw is retained
    games = {g["id"]: g for g in tournament["gameList"]}
    assert not any(games[i]["played"] for i in match["games"])
    engine, _, pairs = pair(tournament)
    for cid in (1, 4, 8):
        assert engine.competitors[cid]["csq"].strip() == ""
        assert engine.competitors[cid]["cod"] == 0
        assert engine.competitors[cid]["cop"] == "nc"
    allocation = next(p for p in pairs if {p["ca"], p["cb"]} == {4, 8})
    assert (allocation["w"], allocation["b"], allocation["colorrule"]) == (8, 4, "4.3.1")
    result = check(23, 2, monkeypatch)
    assert result["status"]["code"] == 0
    assert result["pairingResult"]["roundpairing"][0]["pairs"] == [(1, 5), (7, 2), (8, 4)]


def test_cross_forfeited_match_preserves_scores_and_direct_encounter():
    tb = tiebreak(read(23), 1, None)
    for cid in (1, 4):
        result = tb.cmps[cid]["rsts"][1]
        assert result["played"] is True
        assert result["mpoints"] == Decimal("1")
        assert result["gpoints"] == Decimal("1")
        assert sum(g["points"] for g in result["games"]) == Decimal("1")
    tb.compute_single_tiebreak(tb.parse_tiebreak(1, "DE"))
    # The default primary score is GP in this attachment; both tied teams retain
    # their result against each other for direct encounter.
    assert tb.cmps[1]["tbval"]["deval"] == Decimal("1")
    assert tb.cmps[4]["tbval"]["deval"] == Decimal("1")


@pytest.mark.parametrize("played_board", [0, 1])
def test_one_actual_board_supplies_the_scheduled_first_board_colour(played_board):
    tournament = read(23)
    match = next(m for m in tournament["matchList"] if m["round"] == 1 and m["white"]["cid"] == 1)
    games = {g["id"]: g for g in tournament["gameList"]}
    games[match["games"][played_board]]["played"] = True
    tb = tiebreak(tournament, 1, None)
    assert tb.cmps[1]["tbval"]["mpoints_csq"]["val"] == "w"
    assert tb.cmps[4]["tbval"]["mpoints_csq"]["val"] == "b"


def test_board_evidence_overrides_match_flag_and_byes_never_supply_colour():
    match = {"white": {"cid": 1}, "black": {"cid": 2}, "played": True}
    assert match_has_played_board(match, {}) is True  # legacy match-only JSON
    assert match_has_played_board(dict(match, games=[]), {}) is False
    assert match_has_played_board(dict(match, black=None), {}) is False
    games = {1: {"white": {"cid": 1}, "black": None, "played": True}}
    assert match_has_played_board(dict(match, games=[1]), games) is False


def test_initial_colour_distinguishes_actual_witness_and_trf_152_omission():
    text = (FIXTURES / "fideteam_issue23.trf").read_text()
    tournament = read(23, "\n".join(line for line in text.splitlines() if not line.startswith("152")))
    assert not tournament.get("topColorExplicit", False)
    # TRF record 152 is optional when the initial colour equals that of the
    # highest-ranked participant paired in round one. That format convention
    # survives even when all those matches are forfeits.
    assert pairing_fideteam(tournament, 2, dict(PARAMS, top_color="b")).topcolor == "w"
    # Without either format-derived or explicit evidence, use the caller's default.
    tournament.pop("topColor")
    assert pairing_fideteam(tournament, 2, dict(PARAMS, top_color="b")).topcolor == "b"
    # A later actual board in the first round witnesses the lot and overrides inference/default.
    match = next(m for m in tournament["matchList"] if m["round"] == 1 and m["white"]["cid"] == 5)
    games = {g["id"]: g for g in tournament["gameList"]}
    games[match["games"][0]]["played"] = True
    assert pairing_fideteam(tournament, 2, dict(PARAMS, top_color="b")).topcolor == "w"


def test_explicit_and_legacy_json_initial_colours_are_preserved():
    tournament = read(23)
    assert pairing_fideteam(tournament, 2, dict(PARAMS, top_color="b")).topcolor == "w"
    tournament.pop("topColorExplicit")
    tournament["topColor"] = "b"
    assert pairing_fideteam(tournament, 2, PARAMS).topcolor == "b"


def cross_forfeit(event, rnd, white, black):
    event.match(rnd, white, black, ["W", "L"])
    board_ids = event.tournament["matchList"][-1]["games"]
    for game in event.tournament["gameList"]:
        if game["id"] in board_ids:
            game["played"] = game["rated"] = False


def test_pairing_history_allows_rematch_and_bye_priority_counts_actual_matches():
    """C.04.2 3.5 permits the unplayed rematch; C.04.6 3.4.3 counts actual matches."""
    from test_pairing_fideteam import event

    fixture = event(5, 5)
    cross_forfeit(fixture, 1, 1, 5)
    fixture.match(1, 2, 4, ["D", "D"])
    fixture.halfpointbye(1, 3)
    tournament = fixture.tournament
    engine, _, pairs = pair(tournament)
    assert engine.opponents[1][5]["canmeet"] is True
    assert engine.opponents[2][4]["canmeet"] is False
    assert engine.competitors[5]["num"]["val"] == 0
    assert engine.competitors[4]["num"]["val"] == 1
    assert [(p["w"], p["b"]) for p in pairs if p["b"] == 0] == [(4, 0)]
    # The pairing adapter must not alter standings or the source match classification.
    tb = tiebreak(tournament, 1, None)
    assert tb.cmps[5]["tbval"]["mpoints_num"]["val"] == 1
    assert tournament["matchList"][0]["played"] is True
    # If those boards had really been played, teams 4 and 5 tie on actual matches,
    # so art. 3.4.4 would give the bye to larger TPN 5.
    for game in tournament["gameList"]:
        game["played"] = True
    _, _, pairs = pair(tournament)
    assert [(p["w"], p["b"]) for p in pairs if p["b"] == 0] == [(5, 0)]


def test_unplayed_cross_forfeit_does_not_float_a_team():
    """C.04.6 art. 1.5 requires playing the differently-scoring opponent."""
    from test_pairing_fideteam import event

    fixture = event(4, 5)
    fixture.match(1, 1, 2, ["W", "W"])
    fixture.match(1, 3, 4, ["D", "D"])
    cross_forfeit(fixture, 2, 1, 3)  # scores 2 and 1 before this unplayed match
    fixture.match(2, 2, 4, ["D", "D"])
    engine, _, _ = pair(fixture.tournament, 3)
    assert engine.competitors[1]["flt"] == engine.competitors[3]["flt"] == 0
    for game in fixture.tournament["gameList"]:
        game["played"] = True
    # Inspect the crosstable independently: after actual matches all four teams need
    # their final new opponent, regardless of which bracket-search path finds it.
    engine, _, _ = pair(fixture.tournament, 3)
    competitors = engine.competitors
    assert competitors[1]["flt"] == 1  # played down
    assert competitors[3]["flt"] == 2  # played up


def test_issue23_original_six_round_attachment_passes(monkeypatch):
    assert check(23, -1, monkeypatch)["status"]["code"] == 0
