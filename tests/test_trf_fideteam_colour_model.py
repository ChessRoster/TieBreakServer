# -*- coding: utf-8 -*-
"""
The colour model of a FIDE Swiss team tournament, from the file to the pairing.

C.04.6 art. 1.7 lets the rules of the competition choose one of three colour models: the
type A colour preferences of art. 1.7.1, the type B preferences of art. 1.7.2, "or colour
preferences are not to be used at all". TRF-2026 record 192 says which one a tournament
uses, and the third model has no marker of its own: it is the FIDE_TEAM_* codes that name
neither TYPEA nor TYPEB.

`tests/test_pairing_fideteam.py` holds the three models to their articles on positions
built by hand. These tests are the other end of the same wire - a complete tournament
file, read and paired by the real checker - and they hold the reader to selecting the
model the file declares, and the engine to pairing that file the way its model prescribes
and not the way the other two would.

The fixture is a nine-team, seven-round FIDE_TEAM_MP_GP event, taken from the team corpus.
Every round of it agrees with the pairing the no-preference model prescribes; round 2
disagrees with the one type B prescribes, and round 6 with both type A and type B, so the
one file tells all three models apart.
"""
import contextlib
import copy
import io
import os
import sys

import pytest

import pairingchecker
import trf2json
from pairingfideteam import pairing_fideteam

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "fideteam_nocolor.trf")

PARAMS = {"experimental": [], "verbose": 0, "rank": False, "top_color": "w"}


def read():
    reader = trf2json.trf2json()
    with open(FIXTURE, encoding="utf-8") as handle:
        reader.parse_file(handle.read(), 0)
    return reader.get_tournament(1)


def engine(rnd, pairingsystem=None):
    """The pairing engine for one round, optionally forced onto another colour model."""
    tournament = read()
    if pairingsystem is not None:
        tournament["pairingSystem"] = pairingsystem
    return pairing_fideteam(tournament, rnd, copy.deepcopy(PARAMS))


def pairs(rnd, pairingsystem=None):
    """The pairing of one round as (white team, black team, the art. 4.3 rule)."""
    roundpairing = engine(rnd, pairingsystem).compute_pairing(False)
    return sorted(
        (pair["w"], pair["b"], pair["colorrule"])
        for bracket in roundpairing
        for pair in bracket["pairs"]
    )


def check(argv):
    """Run the real pairingchecker over the fixture in check mode and return its status
    code: 0 when every declared round is the round the engine would have paired, 1 when
    one of them is not."""
    checker = pairingchecker.pairingchecker()
    saved = sys.argv
    sys.argv = ["pairingchecker", "-i", FIXTURE, "-c"] + argv
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                checker.common_main()
            except SystemExit:
                pass
    finally:
        sys.argv = saved
    return checker.resultjson.get("status", {}).get("code")


def declared(rnd):
    return sorted((match["white"], match["black"]) for match in read()["matchList"] if match["round"] == rnd)


def test_record_192_selects_the_no_colour_preference_model():
    """Art. 1.7 - FIDE_TEAM_MP_GP names neither type A nor type B, so the tournament is
    paired with no colour preferences at all."""
    assert read()["pairingSystem"] == ["fideteam", "nocolor"]

    built = engine(6)

    assert built.usecolor is False
    assert built.typeb is False


def built_engines(monkeypatch, argv):
    """The pairing engines the checker builds for a run - one per round it checks."""
    built = []
    original = pairing_fideteam.__init__

    def record(self, tournament, rnd, params):
        original(self, tournament, rnd, params)
        built.append(self)

    monkeypatch.setattr(pairing_fideteam, "__init__", record)
    check(argv)
    return built


@pytest.mark.parametrize(
    "method, usecolor, typeb",
    [
        ("fideteam", True, False),              # art. 1.7.1, the default
        ("fideteam-typeb", True, True),         # art. 1.7.2
        ("fideteam-nocolor", False, False),     # art. 1.7, no preferences at all
    ],
)
def test_the_method_option_reaches_the_engine(monkeypatch, method, usecolor, typeb):
    """`-m` names all three colour models of art. 1.7 on the command line.

    commonmain splits the value of `-m` on "-", so "fideteam-nocolor" arrives at the
    engine as the pairing system ["fideteam", "nocolor"] - the one record 192 writes for a
    FIDE_TEAM_MP_GP file - and pairingchecker still resolves the engine from it, because
    only "fideteam" is a key of its method table. The option overrides record 192: the
    fixture declares no colour preferences and `-m fideteam` pairs it with type A anyway.
    """
    engines = built_engines(monkeypatch, ["-m", method])

    assert len(engines) == 7                    # one per round of the fixture
    assert all(built.usecolor is usecolor for built in engines)
    assert all(built.typeb is typeb for built in engines)
    assert all(built.tournament["pairingSystem"] == method.split("-") for built in engines)


def test_the_declared_pairing_is_the_one_the_no_preference_model_prescribes():
    """Every round of the file agrees with the engine record 192 selects for it."""
    assert check([]) == 0


@pytest.mark.parametrize("method", ["fideteam", "fideteam-typeb"])
def test_forcing_a_colour_preference_model_rejects_the_same_file(method):
    """The three models are not relabellings of each other: the same file that the
    no-preference model reproduces exactly is a file that type A and type B would both
    have paired differently, so the checker rejects it under either of them."""
    assert check(["-m", method]) == 1


def test_art_4_3_2_cannot_grant_a_preference_that_does_not_exist():
    """Art. 4.3.2 - "if only one team has a colour preference, grant it" - against art.
    4.3.5 - "give White to the team with the lower colour difference".

    Round 6, the match between teams 2 and 3. Team 3 has played w,w,b,b: its colour
    difference is 0 and its last two played matches were Black, so art. 1.7.1 gives it a
    simple preference for White. Team 2 has played b,w,b,b,w: its colour difference is -1
    and its last two are not both Black, so under type A it has no preference. Art. 4.3.2
    then grants team 3 the White it wants.

    With no colour preferences at all, neither team wants anything, art. 4.3.2 cannot fire
    and the first rule that decides is art. 4.3.5: team 2 has the lower colour difference
    (-1 against 0) and takes White. The file has 2-3, which is what it declares itself to
    be paired by.
    """
    typea = engine(6, ["fideteam", "team_typea"])
    typea.compute_pairing(False)
    nocolor = engine(6)
    nocolor.compute_pairing(False)

    assert (typea.competitors[2]["cop"], typea.competitors[3]["cop"]) == ("nc", "w2")
    assert (nocolor.competitors[2]["cop"], nocolor.competitors[3]["cop"]) == ("nc", "nc")
    assert (typea.competitors[2]["cod"], typea.competitors[3]["cod"]) == (-1, 0)

    assert (3, 2, "4.3.2") in pairs(6, ["fideteam", "team_typea"])
    assert (2, 3, "4.3.5") in pairs(6)
    assert (2, 3) in declared(6)
