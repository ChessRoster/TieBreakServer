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


# ==============================================================================
# The record 192 table
#
# One row per team code record 192 can carry, in the order trf2json.code192 lists
# them, and the same four columns the comment beside that dict writes out: the
# pairing system and the colour model in it, the primary score, and the secondary
# score. "-" in the comment is None here.
#
# This is a table of what the reader does today, not of what art. 1.7 asks for. The
# comment beside code192 sets out where the two part company -- FIDE_TEAM and
# FIDE_TEAM_BAKU read a missing TYPE token as the art. 1.7 type A default, while
# FIDE_TEAM_MP_GP and its siblings read the same missing token as "no colour
# preferences at all" -- and leaves the decision to the maintainer. Freezing the
# table is what makes that decision a visible one: whichever way it goes, it lands
# as a changed row here and not as a quietly different pairing.
# ==============================================================================

RECORD_192_TEAM_CODES = [
    # record 192 code,              pairing system,                 primary,  secondary
    ("FIDE_TEAM_TYPEA_MP_GP",       ["fideteam", "team_typea"],     "match",  "game"),
    ("FIDE_TEAM_TYPEA_GP_MP",       ["fideteam", "team_typea"],     "game",   "match"),
    ("FIDE_TEAM_TYPEA_MP",          ["fideteam", "team_typea"],     "match",  None),
    ("FIDE_TEAM_TYPEA_GP",          ["fideteam", "team_typea"],     "game",   None),
    ("FIDE_TEAM_TYPEB_MP_GP",       ["fideteam", "team_typeb"],     "match",  "game"),
    ("FIDE_TEAM_TYPEB_GP_MP",       ["fideteam", "team_typeb"],     "game",   "match"),
    ("FIDE_TEAM_TYPEB_MP",          ["fideteam", "team_typeb"],     "match",  None),
    ("FIDE_TEAM_TYPEB_GP",          ["fideteam", "team_typeb"],     "game",   None),
    ("FIDE_TEAM_MP_GP",             ["fideteam", "nocolor"],        "match",  "game"),
    ("FIDE_TEAM_GP_MP",             ["fideteam", "nocolor"],        "game",   "match"),
    ("FIDE_TEAM_MP",                ["fideteam", "nocolor"],        "match",  None),
    ("FIDE_TEAM_GP",                ["fideteam", "nocolor"],        "game",   None),
    ("FIDE_TEAM",                   ["fideteam", "team_typea"],     None,     None),
    ("CUSTOM_TEAM_SWISS_MP",        ["custom"],                     "match",  None),
    ("CUSTOM_TEAM_SWISS_GP",        ["custom"],                     "game",   None),
    ("FIDE_TEAM_TYPEA_MP_GP_BAKU",  ["fideteam", "team_typea"],     "match",  "game"),
    ("FIDE_TEAM_TYPEA_MP_BAKU",     ["fideteam", "team_typea"],     "match",  None),
    ("FIDE_TEAM_TYPEB_MP_GP_BAKU",  ["fideteam", "team_typeb"],     "match",  "game"),
    ("FIDE_TEAM_TYPEB_MP_BAKU",     ["fideteam", "team_typeb"],     "match",  None),
    ("FIDE_TEAM_MP_GP_BAKU",        ["fideteam", "nocolor"],        "match",  "game"),
    ("FIDE_TEAM_MP_BAKU",           ["fideteam", "nocolor"],        "match",  None),
    ("FIDE_TEAM_BAKU",              ["fideteam", "team_typea"],     None,     None),
    ("CUSTOM_TEAM_SWISS",           ["custom"],                     None,     None),
    ("BERGER_TEAM_ROUNDROBIN",      ["berger"],                     None,     None),
    ("BERGER_TEAM_DOUBLEROUNDROBIN", ["berger"],                    None,     None),
    ("FIDE_TEAM_ROUNDROBIN",        ["berger"],                     None,     None),
    ("FIDE_TEAM_DOUBLEROUNDROBIN",  ["berger"],                     None,     None),
    ("CUSTOM_TEAM_ROUNDROBIN",      ["custom"],                     None,     None),
    ("CUSTOM_TEAM_KNOCKOUT",        ["custom"],                     None,     None),
]

# The colour model each pairing system stands for, as pairing_fideteam builds it:
# art. 1.7.1 type A, art. 1.7.2 type B, or art. 1.7 no preferences at all.
COLOUR_MODELS = {
    "team_typea": {"usecolor": True, "typeb": False},
    "team_typeb": {"usecolor": True, "typeb": True},
    "nocolor": {"usecolor": False, "typeb": False},
}


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


def team_line(cid, name, players, matchpoints, gamepoints):
    # Record 310, at the columns TRF-2026 gives it: the pairing number in 5 - 7, the name
    # in 9 - 40, the match points in 55 - 60, the game points in 62 - 67, the rank in
    # 69 - 71, then the player ids from 74 on.
    line = list(" " * 73)
    line[0:3] = "310"
    line[4:7] = "%3d" % cid
    line[8 : 8 + len(name)] = name
    line[54:60] = "%6s" % matchpoints
    line[61:67] = "%6s" % gamepoints
    line[68:71] = "%3d" % cid
    return "".join(line) + " ".join(["%4d" % player for player in players])


def resolve_192(code):
    """What the reader makes of a team file whose record 192 carries `code`.

    The smallest team event that can carry a 192 record at all: two teams of two, one
    round played, and record-310 totals that agree with it. Nothing in it depends on the
    code, so whatever comes out differently between two runs came out of record 192.
    """
    lines = ["012 Record 192", "042 2026-03-01", "XXR 1", "352 WB", "192 " + code]
    lines.append(team_line(1, "Team One", [1, 2], "2.0", "1.5"))
    lines.append(team_line(2, "Team Two", [3, 4], "0.0", "0.5"))
    lines.append(player_line(1, "One, Player", 2400, "1.0", [(3, "w", "1")]))
    lines.append(player_line(2, "Two, Player", 2300, "0.5", [(4, "b", "=")]))
    lines.append(player_line(3, "Three, Player", 2200, "0.0", [(1, "b", "0")]))
    lines.append(player_line(4, "Four, Player", 2100, "0.5", [(2, "w", "=")]))
    reader = trf2json.trf2json()
    reader.parse_file("\n".join(lines), 0)
    assert reader.get_status() == 0
    return reader.get_tournament(1)


@pytest.mark.parametrize(
    "code, pairingsystem, primary, secondary",
    RECORD_192_TEAM_CODES,
    ids=[row[0] for row in RECORD_192_TEAM_CODES],
)
def test_record_192_colour_model_table(code, pairingsystem, primary, secondary):
    """Record 192 resolves to the row the table beside code192 documents.

    TRF-2026 record 192 is the "Encoded Type Of Tournament", one token naming the whole
    of a tournament's pairing rules. For the team formats trf2json splits that token in
    two: code192 gives the pairing system and, with it, the C.04.6 art. 1.7 colour model,
    and parse_trf_typetournament() reads "_MP_GP" / "_GP_MP" / "_MP" / "_GP" off the code
    for the art. 1.2 primary and secondary score.

    Reading the code out of a real file, rather than the dict out of the reader, is what
    makes this an assertion about behaviour: it goes through both halves of the split, in
    the order the reader applies them, and it would catch a token rule that disagrees with
    the table as surely as a wrong dict entry -- "_GP" is a substring of "_GP_MP", so the
    order those four tests are written in is itself load-bearing.
    """
    tournament = resolve_192(code)

    assert tournament["pairingSystem"] == pairingsystem
    assert tournament["scoreSystem"].get("primary") == primary
    assert tournament["scoreSystem"].get("secondary") == secondary


def test_record_192_table_lists_every_team_code():
    """Every team code the reader knows has a row above.

    A code added to code192 without a row here is a code whose colour model and score
    system nothing states and nothing checks, which is how the table beside the dict would
    go stale. Comparing the two lists as sets makes that a failing test on the day the
    code is added.
    """
    known = [code for code in trf2json.trf2json().code192 if "TEAM" in code]

    assert [row[0] for row in RECORD_192_TEAM_CODES] == known


def engine_for(code):
    """The pairing engine a file with this record 192 gets, built on the real fixture.

    The fixture is a nine-team event that can actually be paired; the record-192 code is
    the only thing swapped into it, so what the engine ends up believing about colours and
    scores is what the code said and nothing else.
    """
    tournament = read()
    resolved = resolve_192(code)
    tournament["pairingSystem"] = resolved["pairingSystem"]
    tournament["tournamentInfo"]["typeOfTournament"] = resolved["tournamentInfo"]["typeOfTournament"]
    for key in ["primary", "secondary", "secondaryUsed"]:
        tournament["scoreSystem"].pop(key, None)
        if key in resolved["scoreSystem"]:
            tournament["scoreSystem"][key] = resolved["scoreSystem"][key]
    return pairing_fideteam(tournament, 7, copy.deepcopy(PARAMS))


@pytest.mark.parametrize(
    "code, pairingsystem, primary, secondary",
    [row for row in RECORD_192_TEAM_CODES if row[1][0] == "fideteam"],
    ids=[row[0] for row in RECORD_192_TEAM_CODES if row[1][0] == "fideteam"],
)
def test_record_192_colour_model_reaches_the_engine(code, pairingsystem, primary, secondary):
    """The row the reader resolves is the model C.04.6 is then paired with.

    Art. 1.7 is a decision of the competition's rules, and the engine holds it as two
    flags: `usecolor` is False for the third model, "colour preferences are not to be
    used at all", and `typeb` chooses between art. 1.7.1 and art. 1.7.2 for the other two.
    Art. 1.2 is the second decision, and the engine holds it as `secondary` - whether the
    score that does not rank the teams is used for the colour allocation of art. 4.2.2.

    Asserting on the engine and not only on the tournament dict is what closes the loop:
    a row of the table is only true if the flags C.04.6 is actually run with are the ones
    it names. Art. 1.2.2 is the case worth watching - a code naming no score at all
    ("FIDE_TEAM") leaves both unset, and the engine has to read that as "match points
    rank, game points decide the colour" rather than as "there is no secondary score".
    """
    built = engine_for(code)

    assert built.usecolor is COLOUR_MODELS[pairingsystem[1]]["usecolor"]
    assert built.typeb is COLOUR_MODELS[pairingsystem[1]]["typeb"]
    # art. 1.2 - a second score is in play unless the code named exactly one, which is
    # also what art. 1.2.2 asks for when the code names neither.
    assert built.secondary is (secondary is not None or primary is None)
