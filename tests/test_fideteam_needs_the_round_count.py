# -*- coding: utf-8 -*-
"""A team tournament cannot be paired, or checked, within two rounds of an end
that was only inferred.

Three parts of C.04.6 ask a question the results cannot answer: where the end
of the event is. Two of them apply under every colour model:

    2.3.4  [C7]  With the exception of the LAST TWO ROUNDS, minimise the number
                 of upfloaters that were floaters in the previous round.
    2.3.7  [C10] With the exception of the LAST TWO ROUNDS, minimise the number
                 of upfloaters' opponents that were floaters in the previous
                 round.

and the third is art. 1.7.2, the type B colour preferences, four of whose five
clauses read the colour difference and the last two played matches, both of
which are written in the file. The fifth does not (the regulation does not
number the paragraphs of art. 1.7.2; they are counted here):

    fifth paragraph  A team has no (Type B) colour preference when it has yet to
                     play a match, or when its CD is zero when pairing for the
                     LAST ROUND.

and the two mild clauses carry the same condition inside them:

    third paragraph  ... if its CD is -1, or, if it is zero AND IT IS NOT THE LAST
                     ROUND, the team had Black in the last played match.

"The last round" is the scheduled length of the event, which only record 142
states (C.04.1 art. 1: "the number of rounds to be played is declared
beforehand"). Without it the reader has nothing to go on but the rounds already
played, and ``trf2json`` raises ``numRounds`` to the last played round and
marks the count as inferred - so the engine would decide that every round it is
asked for is within two of the end: [C7] and [C10] would be switched off on a
guess, and under type B every team with a colour difference of zero would be
given a mild preference the regulation withholds in the one round where it
deliberately withholds one.

That is a wrong pairing produced silently from a file that never said how long
the tournament is, so the round is refused instead, for every colour model,
whether it is being paired or checked: the constructor of the engine refuses,
and a check builds one engine per round. A complete file without record 142
therefore needs ``-N`` to have its last two rounds checked, and the message
says so. Rounds further from the inferred end are unaffected.
"""
import contextlib
import io
import sys

import pytest

import errors
import pairingchecker
from pairingfideteam import pairing_fideteam
import trf2json


def team_file(code, *, rounds="142 7"):
    """The shipped nine-team fixture, re-coded and optionally stripped of its
    round count."""
    with open("tests/fixtures/fideteam_nocolor.trf", encoding="latin1") as handle:
        lines = handle.read().rstrip("\n").split("\n")
    out = []
    for line in lines:
        if line.startswith("192"):
            out.append("192 " + code)
        elif line.startswith("142"):
            if rounds:
                out.append(rounds)
        else:
            out.append(line)
    return "\n".join(out)


def tournament_of(text):
    chessfile = trf2json.trf2json()
    chessfile.parse_file(text, 0)
    return chessfile.chessjson["event"]["tournaments"][0]


def engine(text, rnd):
    return pairing_fideteam(tournament_of(text), rnd, {"experimental": [], "verbose": 0})


def check(tmp_path, text, argv=()):
    """Run the real checker over the file in check mode and return it."""
    path = tmp_path / "team.trf"
    path.write_text(text, encoding="latin1")
    checker = pairingchecker.pairingchecker()
    saved = sys.argv
    sys.argv = ["pairingchecker", "-i", str(path), "-c"] + list(argv)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                checker.common_main()
            except SystemExit:
                pass
    finally:
        sys.argv = saved
    return checker


def rounds_checked(checker):
    return [item["round"] for item in checker.chessfile.result["roundpairing"]]


def test_type_b_without_a_round_count_is_refused():
    """The regression this file was written for: pairing round 8 of a type B file
    that accounts for seven rounds and has no record 142."""
    with pytest.raises(errors.GacruxInputError) as excinfo:
        engine(team_file("FIDE_TEAM_TYPEB_MP_GP", rounds=""), 8)
    message = str(excinfo.value)
    assert "142" in message                  # the record the arbiter has to add
    assert "-N" in message                   # or the flag
    assert "1.7.2" in message                # the article that cannot be applied
    assert "2.3.4" in message                # and the two that cannot either


def test_type_b_with_a_round_count_is_paired():
    """The same file, with the record it was missing, pairing its last round."""
    assert engine(team_file("FIDE_TEAM_TYPEB_MP_GP"), 7).typeb is True


def test_check_mode_stops_two_rounds_before_an_inferred_end(tmp_path):
    """[C7] art. 2.3.4 and [C10] art. 2.3.7 through the real checker, on a type A file.

    Seven rounds played, no record 142: the reader infers seven, and the last two of
    those - rounds 6 and 7 - cannot be checked, because nothing says they are the last
    two. Rounds 1 to 5 are checked; round 6 is refused with a status 401 that names the
    round and the -N flag. With -N 9 the event has nine rounds, round 7 is not within two
    of the end, and all seven rounds are checked.
    """
    text = team_file("FIDE_TEAM_TYPEA_MP_GP", rounds="")
    checker = check(tmp_path, text)
    tournament = checker.chessfile.get_tournament(1)
    assert tournament["numRounds"] == 7
    assert tournament["numRoundsExplicit"] is False
    assert rounds_checked(checker) == [1, 2, 3, 4, 5]
    assert checker.resultjson["status"]["code"] == 401
    message = checker.resultjson["status"]["error"][0]
    assert "round 6" in message
    assert "142" in message
    assert "-N" in message
    assert "2.3.4" in message

    checker = check(tmp_path, text, ["-N", "9"])
    assert checker.chessfile.get_tournament(1)["numRoundsExplicit"] is True
    assert rounds_checked(checker) == [1, 2, 3, 4, 5, 6, 7]
    assert checker.resultjson["status"]["code"] != 401


def test_type_b_check_mode_stops_two_rounds_before_an_inferred_end_as_well(tmp_path):
    """The type B twin: the earlier guard refused only the latest played round, which
    left round 6 checked as if it were not one of the last two."""
    checker = check(tmp_path, team_file("FIDE_TEAM_TYPEB_MP_GP", rounds=""))
    assert rounds_checked(checker) == [1, 2, 3, 4, 5]
    assert checker.resultjson["status"]["code"] == 401
    message = checker.resultjson["status"]["error"][0]
    assert "round 6" in message
    assert "1.7.2" in message


def test_type_b_paired_past_the_declared_end_is_refused_too():
    """The guard cannot tell a missing record 142 from one that is too short, and
    it should not try: both leave the same question unanswerable. A file that
    declares seven rounds cannot say whether round eight is the last."""
    with pytest.raises(errors.GacruxInputError) as excinfo:
        engine(team_file("FIDE_TEAM_TYPEB_MP_GP"), 8)
    assert "-N" in str(excinfo.value)


def test_type_a_without_a_round_count_is_refused():
    """Art. 1.7.1 never asks which round is the last, but [C7] and [C10] do, and they
    apply under type A as under any other model: round 8 of a type A file that accounts
    for seven rounds and has no record 142 is refused, naming the criteria and not the
    type B article."""
    with pytest.raises(errors.GacruxInputError) as excinfo:
        engine(team_file("FIDE_TEAM_TYPEA_MP_GP", rounds=""), 8)
    message = str(excinfo.value)
    assert "142" in message
    assert "2.3.4" in message
    assert "2.3.7" in message
    assert "1.7.2" not in message


def test_type_a_without_a_round_count_is_paired_further_from_the_end():
    """Round 5 of the same file is not within two of the inferred seven, and [C7] and
    [C10] apply to it whatever the true length of the event is."""
    built = engine(team_file("FIDE_TEAM_TYPEA_MP_GP", rounds=""), 5)
    assert built.typeb is False
    assert built.lasttworounds is False


def test_no_colour_preferences_without_a_round_count_is_refused():
    """A competition that uses no colour preferences reads none of art. 1.7, but [C7]
    and [C10] are not colour criteria: it is refused like the others."""
    with pytest.raises(errors.GacruxInputError) as excinfo:
        engine(team_file("FIDE_TEAM_MP_GP", rounds=""), 8)
    assert "2.3.7" in str(excinfo.value)


def test_no_colour_preferences_without_a_round_count_is_paired_further_from_the_end():
    built = engine(team_file("FIDE_TEAM_MP_GP", rounds=""), 5)
    assert built.usecolor is False
    assert built.lasttworounds is False
