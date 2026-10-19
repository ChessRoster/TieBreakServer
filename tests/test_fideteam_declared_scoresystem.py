# -*- coding: utf-8 -*-
"""A score system the caller declared survives a pairing system without a score token.

C.04.6 art. 1.2.1 lets the rules state the primary score and whether the other one is
used. A pairing system of ["fideteam"] (or none at all) names no score, so it must leave
the declared score system alone; art. 1.2.2 applies only when nothing was declared.
"""
import pytest

from gacrux.gacruxexeptions import GacruxInputError
from gacrux.pairingfideteam import (
    SECONDARY_UNUSED,
    SECONDARY_USED,
    pairing_fideteam,
    resolve_scoresystem,
)
from test_pairing_fideteam import event


@pytest.mark.parametrize("primary", ["game", "gp", "match", "mp"])
@pytest.mark.parametrize("pairingsystem", [[], ["fideteam"], ["fideteam", "typea"]])
def test_declared_primary_alone_is_left_untouched(pairingsystem, primary):
    scoresystem = {"primary": primary}
    assert resolve_scoresystem(pairingsystem, scoresystem) == SECONDARY_USED
    assert scoresystem == {"primary": primary}


def test_declared_unused_secondary_survives_without_a_score_token():
    scoresystem = {"primary": "gp", "secondary": None}
    assert resolve_scoresystem(["fideteam"], scoresystem) == SECONDARY_UNUSED
    assert scoresystem == {"primary": "gp", "secondary": None}


def test_declared_secondary_survives_without_a_score_token():
    scoresystem = {"primary": "match", "secondary": "game"}
    assert resolve_scoresystem(["fideteam"], scoresystem) == SECONDARY_USED
    assert scoresystem == {"primary": "match", "secondary": "game"}


def test_nothing_declared_falls_back_to_art_1_2_2():
    scoresystem = {}
    assert resolve_scoresystem(["fideteam"], scoresystem) == SECONDARY_USED
    assert (scoresystem["primary"], scoresystem["secondary"]) == ("match", "game")


@pytest.mark.parametrize("token,primary,secondary", [
    ("mp+gp", "match", "game"), ("gp+mp", "game", "match"),
    ("mp", "match", None), ("gp", "game", None),
])
def test_an_explicit_token_still_overrides_the_declaration(token, primary, secondary):
    scoresystem = {"primary": "game", "secondary": "match"}
    resolve_scoresystem(["fideteam", token], scoresystem)
    assert (scoresystem["primary"], scoresystem["secondary"]) == (primary, secondary)


def test_engine_keeps_a_declared_game_primary():
    tournament = event(4, 3, primary="game")
    engine = tournament.engine(1)
    assert engine.tournament["scoreSystem"]["primary"] == "game"


@pytest.mark.parametrize("pairingsystem", [["fideteam"], ["fideteam", "typea", "gp"]])
def test_game_primary_with_acceleration_is_still_rejected(pairingsystem):
    tournament = event(4, 3, primary="game")
    tournament.tournament["pairingSystem"] = pairingsystem
    tournament.tournament["accelerated"] = {"name": "Acc", "values": [
        {"matchPoints": 2, "gamePoints": 4, "firstRound": 1, "lastRound": 2,
         "firstCompetitor": 1, "lastCompetitor": 2}]}
    with pytest.raises(GacruxInputError, match="game points"):
        tournament.engine(1)
