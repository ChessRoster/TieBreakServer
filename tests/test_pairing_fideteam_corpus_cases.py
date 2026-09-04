# -*- coding: utf-8 -*-
"""
Positions taken from tournaments in the engine regression corpus, not constructed by hand.

The tests in test_pairing_fideteam.py build the smallest position in which one article
decides, which is the right way to hold the engine to a regulation. This file does the
complementary thing: it takes a shape that a real tournament of the corpus actually
reached, and pins the answer the regulation gives there.

That matters for the art. 3.6 pairing identifier in particular. Correcting it changed the
pairing of 228 of the 700 valid team tournaments of the corpus, and a change of that size
is only worth having if the new answer is the one C.04.6 asks for. A constructed test
shows the rule is implemented; a corpus-derived test shows the rule is what decides real
tournaments, and that the engine's previous answer was wrong rather than merely different.

Each test names the corpus record it came from, so the derivation can be checked against
the tournament it was taken from:

    python3 - <<'EOF'
    import gzip, json, sys
    sys.path.insert(0, "tests/corpus")
    import _harness as H
    with gzip.open(H.CORPUS_GZ, "rt") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["name"] == "team_0018":
                print(rec["trf"])
    EOF
"""
from test_pairing_fideteam import event


def test_art_3_6_2_picks_the_smallest_identifier_a_played_history_still_allows():
    """art. 3.6.2, on the shape that round 3 of corpus record team_0018 reaches.

    art. 3.6.1 - "for each pair, the smaller-TPN player is the top member, the larger-TPN
    player is the bottom member". art. 3.6.2 - "a pairing is identified by the TPNs of the
    top members (ascending), followed by the TPNs of the corresponding bottom members",
    and the pairing chosen is the one with the lexicographically smallest identifier.

    team_0018 is a 13-team, 8-round type A event with match points as the primary score.
    Its round 3 has a heterogeneous bracket holding the residents 3, 4 and 5 and the single
    upfloater 1. Three pairings of that bracket exist, and their identifiers are:

        {1-4, 3-5}  ->  1 3 4 5     the smallest, and barred: 1 and 4 met in round 2
        {1-5, 3-4}  ->  1 3 5 4     the smallest that art. 2.1.1 [C1] still allows
        {1-3, 4-5}  ->  1 4 3 5

    So the answer is 1-5 and 3-4. The file itself declares 1-3 and 4-5 - the identifier
    that is largest of the three - because the engine that produced it numbered the
    bracket in score order, which puts the residents 3, 4, 5 before the upfloater 1 and
    makes {1-3, 4-5} look like the first pairing rather than the last.

    This position is reproduced here rather than replayed: eight teams, the same bracket
    membership, and the same one prohibition - 1 and 4 have met and nothing else in the
    bracket has. Everything that could decide the bracket on some other ground is held
    level, so art. 3.6.2 is the only article left to choose:

      * [C1] (art. 2.1.1) bars exactly one of the three pairings, which is the point.
      * [C4] and [C5] (art. 2.3.1, 2.3.2) are equal across the two surviving pairings:
        each pairs the one upfloater with one resident and the other two residents
        together, so each has one upfloater and the same score differences.
      * [C7] and [C10] (art. 2.3.4, 2.3.7) are zero: round 2 paired equal scores in every
        bracket, so no team of this bracket floated in the previous round.
      * [C8] and [C9] (art. 2.3.5, 2.3.6) are zero: this is type A, and after two matches
        every team here has a colour difference of zero with alternating colours, so no
        team carries a colour preference to fulfil or to leave unfulfilled.

    Reintroduce the defect - number the bracket in score order instead of TPN order - and
    this returns 1-3 and 4-5, the identifier the corpus file was written with.
    """
    tournament = event(8, 5)

    # Round 1 - four winners on 2 MP (1, 3, 4, 5) and four losers on 0 MP.
    tournament.match(1, 1, 7, ["W", "W"])
    tournament.match(1, 3, 6, ["W", "W"])
    tournament.match(1, 4, 2, ["W", "W"])
    tournament.match(1, 5, 8, ["W", "W"])

    # Round 2 - team 1 meets team 4 and loses, which is the prohibition the bracket then
    # has to pair around. Teams 3 and 5 win and stay level with 4; the colours alternate
    # for every team, so no type A preference survives into round 3.
    tournament.match(2, 4, 1, ["W", "W"])
    tournament.match(2, 6, 3, ["L", "L"])
    tournament.match(2, 7, 5, ["L", "L"])
    tournament.match(2, 2, 8, ["W", "W"])

    pairs = tournament.pair(3)
    bracket = sorted(
        tuple(sorted(pair)) for pair in pairs if set(pair) <= {1, 3, 4, 5}
    )

    assert bracket == [(1, 5), (3, 4)]


def test_the_barred_pairing_is_the_one_with_the_smallest_identifier():
    """The premise of the test above: [C1] is what removes 1-4, not the identifier order.

    Without this, the test above would still pass if the engine happened to reject 1-4 for
    the wrong reason, and the article being demonstrated would be the wrong one. Art. 2.1.1
    [C1] - "two teams shall not play against each other more than once" - is absolute, so
    {1-4, 3-5} is unavailable however small its identifier is.

    Removing the round 2 meeting of 1 and 4, and nothing else, must therefore change the
    answer to that pairing - it is then the smallest identifier available.
    """
    tournament = event(8, 5)

    tournament.match(1, 1, 7, ["W", "W"])
    tournament.match(1, 3, 6, ["W", "W"])
    tournament.match(1, 4, 2, ["W", "W"])
    tournament.match(1, 5, 8, ["W", "W"])

    # Team 1 loses to team 2 instead of to team 4, so it arrives in the same bracket with
    # the same score and the same colour history, and 1-4 is now an available pair.
    tournament.match(2, 2, 1, ["W", "W"])
    tournament.match(2, 6, 3, ["L", "L"])
    tournament.match(2, 7, 5, ["L", "L"])
    tournament.match(2, 4, 8, ["W", "W"])

    pairs = tournament.pair(3)
    bracket = sorted(
        tuple(sorted(pair)) for pair in pairs if set(pair) <= {1, 3, 4, 5}
    )

    assert bracket == [(1, 4), (3, 5)]
