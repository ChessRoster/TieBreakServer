# -*- coding: utf-8 -*-
"""Type B colour preferences cannot be applied without a declared round count.

C.04.6 art. 1.7.2 is the only part of the colour rules that asks a question the
results cannot answer. Four of its five clauses read the colour difference and
the last two played matches, both of which are written in the file. The fifth
does not (the regulation does not number the paragraphs of art. 1.7.2; they are
counted here):

    fifth paragraph  A team has no (Type B) colour preference when it has yet to
                     play a match, or when its CD is zero when pairing for the
                     LAST ROUND.

and the two mild clauses carry the same condition inside them:

    third paragraph  ... if its CD is -1, or, if it is zero AND IT IS NOT THE LAST
                     ROUND, the team had Black in the last played match.

"The last round" is the scheduled length of the event, which only record 142
states. Without it the reader has nothing to go on but the rounds already
played, and ``trf2json`` raises ``numRounds`` to the last played round - so the
engine would decide that every round it is asked to pair is past the end, and
the fifth paragraph would never fire. Every team with a colour difference of zero would be
given a mild preference the regulation does not give it, in the one round where
the regulation deliberately withholds one.

That is a wrong pairing produced silently from a file that never said how long
the tournament is, so it is refused instead. Type A has no such clause and is
unaffected, and neither is a competition that uses no colour preferences.
"""
import pytest

import errors
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


def test_type_b_without_a_round_count_is_refused():
    """The regression this file exists for."""
    with pytest.raises(errors.GacruxInputError) as excinfo:
        engine(team_file("FIDE_TEAM_TYPEB_MP_GP", rounds=""), 8)
    message = str(excinfo.value)
    assert "142" in message                  # the record the arbiter has to add
    assert "1.7.2" in message                 # the article that cannot be applied


def test_type_b_with_a_round_count_is_paired():
    """The same file, with the record it was missing, pairing its last round."""
    assert engine(team_file("FIDE_TEAM_TYPEB_MP_GP"), 7).typeb is True


def test_type_b_paired_past_the_declared_end_is_refused_too():
    """The guard cannot tell a missing record 142 from one that is too short, and
    it should not try: both leave the same question unanswerable. A file that
    declares seven rounds cannot say whether round eight is the last."""
    with pytest.raises(errors.GacruxInputError):
        engine(team_file("FIDE_TEAM_TYPEB_MP_GP"), 8)


def test_type_a_without_a_round_count_is_not_refused():
    """Art. 1.7.1 reads the colour difference and the last two played matches and
    nothing else, so a type A competition never needs to know which round is the
    last one. Refusing it would cost files that are perfectly readable."""
    assert engine(team_file("FIDE_TEAM_TYPEA_MP_GP", rounds=""), 8).typeb is False


def test_no_colour_preferences_without_a_round_count_is_not_refused():
    """A competition that uses no colour preferences at all reads none of art.
    1.7, so the round count is not needed for this."""
    assert engine(team_file("FIDE_TEAM_MP_GP", rounds=""), 8).usecolor is False
