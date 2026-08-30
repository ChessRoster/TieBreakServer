# -*- coding: utf-8 -*-
"""
Regression tests for record 299, Abnormal Assignment points.

TRF-2026 gives record 299 five fields: the type of the assignment in column 5, the match
points in 8-11, the game points in 14-17, the round in 20-22, and the pairing numbers it
applies to in 24-27, 29-32, and so on. A record that leaves the round and the pairing
numbers out applies to every round and every competitor; that is the form the
specification writes out in its own note.

Those two forms are not variations of one feature, and the engine treats them
differently on purpose.

  * A record with no round and no pairing numbers states what an abnormal result is
    worth for the whole tournament -- what a team gets for a forfeit win, what it loses
    by a forfeit. That is a score system, and the engine has one: the record goes into
    scoresystem.add_unplayed() and every result of that type is scored by it.

  * A record that names a round, or a competitor, or both is an assignment: these points,
    to this competitor, in this round, over and above what the result is worth. The
    engine does not do this. changelog.txt and commit 12d30a5 say so -- "This change is
    intentionally limited to parsing and retaining record 299. The engine does not
    currently consume aatlist" -- and that is a scope decision, not a defect.

    What the scope decision cannot mean is that the record is accepted and ignored. A
    file whose forfeit scoring is deliberately scoped to one round or one competitor,
    read with status 0 and then scored by the ordinary rules, is a file scored by rules
    it did not ask for and nothing said so. Of the three things the reader could do with
    a feature it has not implemented -- implement it, refuse it, or silently do something
    else -- the last is the only one that cannot be worked around by whoever handed the
    file over. So the reader refuses it, and says which record and which scope.

    But it refuses only the records it would actually get wrong. A record 299 assigns
    points to a named result -- its AAT letter in column 5 is a result code, the same
    vocabulary as the result column of a 001 record -- so it changes nothing unless the
    competitor it names really has that result in the round it names. An assignment that
    matches no result cannot fire whatever the engine does with it, and one whose points
    are the points the score system already gives that result fires and changes nothing.
    Both are read and accepted: refusing them would lose a file the engine scores exactly
    right, which is the same kind of mistake as accepting one it scores wrongly, only in
    the other direction.

A record 299 pairing number is read against the competitors the event actually has. In an
individual tournament that is the players. In a team tournament TRF-2026 labels the field
"(Team) Pairing Number" -- record 299 is the one record with that label; 300, 320 and 330
say "Team Pairing Number" and 240 says "Player/Team ID" -- and describes it as the "1st
team or individual (if any) getting this point distribution", which leaves open whether a
number is a team's or a player's. Files in the wild use it for the player, and the points
fields are match points and game points, so the reader accepts both readings there,
chooses the player reading where a number is valid under both (a choice of this reader,
not a rule of the specification), and refuses only a number that names nobody at all.

These tests hold all of it: the tournament-wide record still reaches the score system, an
assignment that would fire and change the score is refused with a diagnostic that names
it, and one that would not is read like any other record.
"""
import decimal

import pytest

import errors
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


def abnormal_line(aat, matchpoints, gamepoints, rnd, competitors):
    # Record 299, written at the columns TRF-2026 gives it:
    #     1 - 3    record identifier
    #     5        type of abnormal assignment (AAT)
    #     8 - 11   match points
    #    14 - 17   game points (teams) or points (individuals)
    #    20 - 22   round number
    #    24 - 27   1st pairing number, then 29 - 32, 34 - 37, ...
    line = list(" " * 23)
    line[0:3] = "299"
    line[4] = aat
    line[7:11] = "%4s" % matchpoints
    line[13:17] = "%4s" % gamepoints
    line[19:22] = "%03d" % rnd
    return "".join(line) + " ".join(["%04d" % competitor for competitor in competitors])


def points_only_line(aat, matchpoints, gamepoints):
    # The form of record 299 the specification writes out in its own note. The record
    # stops after the game points: no round field and no pairing numbers, which means
    # every round and every competitor.
    #     ### T   MMMM     GGGG
    #     299 +    2.0      2.5
    line = list(" " * 17)
    line[0:3] = "299"
    line[4] = aat
    line[7:11] = "%4s" % matchpoints
    line[13:17] = "%4s" % gamepoints
    return "".join(line)


def two_rounds(abnormal):
    # Four players, two rounds, and whatever 299 records the test wants to add.
    lines = ["012 Abnormal assignment points", "042 2026-03-01", "XXR 2"]
    lines.append(player_line(1, "One, Player", 2400, "1.5", [(2, "w", "1"), (3, "b", "=")]))
    lines.append(player_line(2, "Two, Player", 2300, "0.5", [(1, "b", "0"), (4, "w", "=")]))
    lines.append(player_line(3, "Three, Player", 2200, "1.5", [(4, "w", "1"), (1, "w", "=")]))
    lines.append(player_line(4, "Four, Player", 2100, "0.5", [(3, "b", "0"), (2, "b", "=")]))
    return lines + abnormal


def four_teams(abnormal, first=1):
    """Four teams of two, two rounds, and whatever 299 records the test wants to add.

    Team 1 is players 1 and 2, team 2 is players 3 and 4, and so on, so the team pairing
    numbers stop at 4 while the player start numbers run to 8: a number like 6 names a
    player and no team, and a number like 99 names neither. `first` is the start number
    of the first player: with first=101 the players are 101 - 108, and the numbers 1 - 4
    then name a team and no player at all.
    """
    p = lambda n: n + first - 1  # noqa: E731
    lines = ["012 Abnormal assignment points, teams", "042 2026-03-01", "XXR 2", "352 WB"]
    lines.append(team_line(1, "Team One", [p(1), p(2)], "2.0", "2.5"))
    lines.append(team_line(2, "Team Two", [p(3), p(4)], "2.0", "2.0"))
    lines.append(team_line(3, "Team Three", [p(5), p(6)], "0.0", "0.5"))
    lines.append(team_line(4, "Team Four", [p(7), p(8)], "4.0", "3.0"))
    lines.append(player_line(p(1), "One, Player", 2400, "1.5", [(p(5), "w", "1"), (p(7), "w", "=")]))
    lines.append(player_line(p(2), "Two, Player", 2300, "1.0", [(p(6), "b", "1"), (p(8), "b", "0")]))
    lines.append(player_line(p(3), "Three, Player", 2200, "0.5", [(p(7), "b", "0"), (p(5), "b", "=")]))
    lines.append(player_line(p(4), "Four, Player", 2100, "1.5", [(p(8), "w", "="), (p(6), "w", "1")]))
    lines.append(player_line(p(5), "Five, Player", 2000, "0.5", [(p(1), "b", "0"), (p(3), "w", "=")]))
    lines.append(player_line(p(6), "Six, Player", 1900, "0.0", [(p(2), "w", "0"), (p(4), "b", "0")]))
    lines.append(player_line(p(7), "Seven, Player", 1800, "1.5", [(p(3), "w", "1"), (p(1), "b", "=")]))
    lines.append(player_line(p(8), "Eight, Player", 1700, "1.5", [(p(4), "b", "="), (p(2), "w", "1")]))
    return lines + abnormal


def team_line(cid, name, players, matchpoints, gamepoints):
    # Record 310, at the columns TRF-2026 gives it.
    line = list(" " * 73)
    line[0:3] = "310"
    line[4:7] = "%3d" % cid
    line[8 : 8 + len(name)] = name
    line[54:60] = "%6s" % matchpoints
    line[61:67] = "%6s" % gamepoints
    line[68:71] = "%3d" % cid
    return "".join(line) + " ".join(["%4d" % player for player in players])


def parse(lines):
    chessfile = trf2json.trf2json()
    chessfile.parse_file("\n".join(lines), True)
    return chessfile


def test_tournament_wide_299_still_works():
    """No round and no pairing numbers: the points apply to the whole tournament.

    This is the record the specification writes out in its note, and it is the one form
    of record 299 the engine implements. It is not an assignment to anybody -- it says
    what a forfeit win and a forfeit loss are worth -- so it goes to the score system,
    where "+" is the match points of a forfeit win and "+G" its game points.

    It is here to guard the supported case against the refusal of the scoped one. A
    refusal written one condition too wide would take this record with it, and this
    tournament would then be unreadable for declaring its own forfeit scoring.
    """
    lines = two_rounds([points_only_line("+", "2.0", "2.5"),
                        points_only_line("-", "0.0", "1.5")])
    chessfile = parse(lines)
    scoresystem = chessfile.get_tournament(1)["scoreSystem"]["match"]

    assert chessfile.get_status() == 0
    assert scoresystem["+"] == decimal.Decimal("2.0")   # forfeit win, match points
    assert scoresystem["+G"] == decimal.Decimal("2.5")  # forfeit win, game points
    assert scoresystem["-"] == decimal.Decimal("0.0")   # forfeit loss, match points
    assert scoresystem["-G"] == decimal.Decimal("1.5")  # forfeit loss, game points


@pytest.mark.parametrize(
    "line, scope",
    [
        (abnormal_line("W", "", "2.0", 1, [1, 3]), "round 1, player(s) 1, 3"),
        (abnormal_line("W", "", "2.0", 1, []), "round 1, every player"),
        (abnormal_line("D", "", "0.0", 0, [1]), "every round, player(s) 1"),
    ],
    ids=["round-and-competitors", "round-only", "competitors-only"],
)
def test_scoped_299_is_explicitly_unsupported(line, scope):
    """A scoped record 299 that would really change the score is refused by name.

    Every case here names a result the competitor actually has, and gives it points the
    score system does not. Players 1 and 3 both won their first round, so an assignment
    of 2.0 to a win in round 1 changes both of their scores from the 1.0 a win is worth;
    the second case names no competitor, so it is every player's round 1; the third names
    no round, so it is every round of player 1, whose round-2 draw would go from 0.5 to
    0.0. Applying them is the one thing the engine cannot do, and scoring the file as
    though they were not there is the one thing it must not do silently.

    The three cases are the three scopes the record's own fields can express: the round
    field set, the pairing-number fields set, or both. Round 000 in the third case is
    "every round" -- the record still names a competitor, so it is an assignment to that
    competitor and not a statement about the tournament.

    The assertions are on what a user can act on. The message has to name the record, so
    the line can be found in the file; the scope the reader read out of it, so a user who
    meant something else can see the fields did not land where they thought; the result
    and the two point values, so they can see exactly what would have been mis-scored;
    and that the scoped form is unsupported rather than wrong, so nobody spends the
    afternoon correcting a record that is already correct.
    """
    with pytest.raises(errors.GacruxInputError) as excinfo:
        parse(two_rounds([line]))

    message = str(excinfo.value)
    assert "299" in message          # the record the message is about
    assert scope in message          # the scope, exactly as the reader read it
    assert "supported" in message    # unsupported, not malformed
    assert "2.0" in message or "0.0" in message   # the points the record assigns


def test_scoped_299_that_cannot_fire_is_accepted():
    """An assignment whose result nobody has is read and accepted, without a word.

    "-" in column 5 is a forfeit loss. Player 1 drew round 2 against a real opponent, so
    the file contains no forfeit loss for player 1 in round 2 and there is nothing for
    this record to assign points to. It could be applied in full and every number the
    engine reports would be the number it reports now.

    Accepting it is the honest answer, not a loosened rule. The reason to refuse a scoped
    record is that the engine would otherwise score the file by different rules than the
    file asks for -- and here the two sets of rules agree, on this file, exactly. Refusing
    it would reject a tournament the engine handles correctly, which is a real cost paid
    for no protection at all. The refusal has to be narrow enough to mean something: it
    fires on the files that would be mis-scored and on no others.
    """
    chessfile = parse(two_rounds([abnormal_line("-", "", "1.0", 2, [1])]))

    assert chessfile.get_status() == 0
    # Read and kept, as changelog.txt says: an implementation of record 299 finds it here.
    assert [(att["att"], att["round"], att["teams"]) for att in chessfile.aatlist] == [("-", 2, [1])]
    # And the file scores as it would without the record: player 1 won and drew.
    tournament = chessfile.get_tournament(1)
    assert next(c for c in tournament["competitors"] if c["cid"] == 1)["gamePoints"] == decimal.Decimal("1.5")


def test_scoped_299_that_changes_nothing_is_accepted():
    """An assignment that fires but restates the score system is accepted too.

    Player 1's round-1 result is a win and a win is worth 1.0, which is exactly what this
    record assigns to it. The assignment matches, so unlike the case above it would fire
    -- and firing it would leave every reported number where it was. There is no rule the
    engine could apply differently, so there is nothing to warn anybody about.

    This is the second half of the same predicate as the test above, and it is worth its
    own case because it fails differently: a reader that only compared the result letter
    and not the points would refuse this file, and a reader that only compared the points
    would refuse the one above.
    """
    chessfile = parse(two_rounds([abnormal_line("W", "", "1.0", 1, [1])]))

    assert chessfile.get_status() == 0
    assert chessfile.aatlist[0]["gamePoints"] == decimal.Decimal("1.0")


def test_scoped_299_names_the_round_and_not_the_game_points():
    """The round is field 20-22 and the game points are 14-17.

    Two different fields in two different places, and a reader that takes the round from
    the game-points columns has nothing to complain about -- it just reports the wrong
    round, and here it would look for a win in round 3 of a two-round tournament, find
    none, and accept a record it should refuse. The game points are 3 and the round is 2,
    so the two cannot be confused with one another, and player 1's round-2 result is the
    draw the record names.
    """
    with pytest.raises(errors.GacruxInputError) as excinfo:
        parse(two_rounds([abnormal_line("D", "", "3", 2, [1])]))

    assert "round 2, player(s) 1" in str(excinfo.value)


def test_scoped_299_rejects_unknown_pairing_number():
    """The pairing numbers of record 299 are checked before anything else about it.

    Nine is not a player of this four-player event, so there is no result to look up and
    no way to tell whether the record would fire. "This number names nobody" is a mistake
    in the file that the user can fix, and it is the diagnostic worth having; it is also
    the only honest one, because a reader that cannot resolve the number cannot claim the
    record is inert either.

    The message is the one every other record's pairing numbers get, from
    check_pairing_number, so record 299 is not a second dialect of the same complaint.
    """
    with pytest.raises(errors.GacruxInputError) as excinfo:
        parse(two_rounds([abnormal_line("W", "", "2.0", 1, [1, 9])]))

    message = str(excinfo.value)
    assert "299" in message          # the record it came from
    assert "player 9" in message     # the number that is wrong
    assert "1 - 4" in message        # the numbers that would have been right


def test_scoped_299_in_a_team_event_may_name_a_player():
    """In a team file a record 299 pairing number may be a player start number.

    TRF-2026 labels the field of record 299 "(Team) Pairing Number" and describes it as
    the "1st team or individual" getting the points -- unlike records 300, 320 and 330,
    whose "Team Pairing Number" is a team's, and record 240, whose "Player/Team ID" is
    a team's in a team event. So the label leaves record 299 open. Its two point fields
    are match points in 8-11 and game points in 14-17, and a game-point assignment reads
    as an assignment to a player. Files in the wild use the player start number, and
    this event has eight players and four teams, so 6 is a player and no team at all.

    Reading it against the teams alone would reject a valid file for a number that is
    perfectly good; reading it against the players alone would do the same to a file that
    means the team. So both are accepted, and only a number that names nobody under either
    reading is refused -- which is the next test.
    """
    chessfile = parse(four_teams([abnormal_line("-", "", "1.0", 2, [6])]))

    assert chessfile.get_status() == 0
    assert chessfile.aatlist[0]["teams"] == [6]


def test_scoped_299_in_a_team_event_rejects_a_number_that_is_neither():
    """A number that is neither a team nor a player is still refused, and says both.

    Accepting either reading is not the same as accepting anything. 99 is not one of the
    four teams and not one of the eight players, so there is no competitor for the
    assignment to belong to under either reading, and the message has to say what it
    checked against -- naming only one of the two vocabularies would send the user
    looking in the wrong place.
    """
    with pytest.raises(errors.GacruxInputError) as excinfo:
        parse(four_teams([abnormal_line("-", "", "1.0", 2, [99])]))

    message = str(excinfo.value)
    assert "299" in message
    assert "99" in message
    assert "4 teams (1 - 4)" in message
    assert "8 players (1 - 8)" in message


def test_a_team_299_with_different_game_points_is_refused():
    """In a team event the assignment names two point values, and both are compared.

    Record 299 gives a team's abnormal result its match points in columns 8-11 and its
    game points in 14-17. Team 1 -- a team and no player, because the players here are
    numbered from 101 -- won its round-1 match on both boards, so it has result W in
    round 1, worth 2.0 match points under the default match score system and 2.0 game
    points from its two boards. This record gives that win 2.0 match points, which is
    what it is worth, and 9.9 game points, which is not.

    The reader compared the match points only, so a record that agreed on them and
    disagreed on the game points was read as inert and the file accepted with status 0
    -- and then scored, on game points, by rules it did not ask for. The message names
    both values.
    """
    with pytest.raises(errors.GacruxInputError) as excinfo:
        parse(four_teams([abnormal_line("W", "2.0", "9.9", 1, [1])], first=101))

    message = str(excinfo.value)
    assert "299" in message
    assert "round 1, team(s) 1" in message
    assert "9.9" in message                  # the game points the record assigns
    assert "2.0" in message                  # and what the boards actually gave

    # Control: the same record with the game points the boards gave is inert.
    assert parse(four_teams([abnormal_line("W", "2.0", "2.0", 1, [1])], first=101)).get_status() == 0


def test_a_scoped_blank_299_that_changes_standings_is_refused():
    """A blank type in column 5 is a standings adjustment, and a nonzero one is refused.

    TRF-2026, record 299, column 5: "(blank) penalty/bonus points (may be negative)" --
    "the points in the standings of teams or individuals (type: [blank]) are modified by
    a positive or negative number (whatever the reason)". It is the one type that is
    not tied to a result: player 1 need not have any particular result in round 1 for
    the -1.0 to come off their total.

    Nothing in the engine adds such a number to anybody's standing, so a file carrying
    one would be ranked without it, with status 0. The reader used to look the blank up
    as a result code (the results table maps " " to Z, the code of an unrecorded
    result), find that player 1 has no Z in round 1, and accept the record as inert:
    player 1 kept 1.5 points and the file read clean.
    """
    chessfile = trf2json.trf2json()

    with pytest.raises(errors.GacruxInputError) as excinfo:
        chessfile.parse_file("\n".join(two_rounds([abnormal_line(" ", "", "-1.0", 1, [1])])), 0)

    message = str(excinfo.value)
    assert "299" in message
    assert "round 1, player(s) 1" in message    # the scope, as the reader read it
    assert "-1.0" in message                    # the points it would have adjusted by
    assert chessfile.get_status() == 401


def test_an_unscoped_blank_299_is_refused_and_leaves_no_score_keys():
    """A blank-type record with no round and no pairing numbers is not a score system.

    The unscoped form of the other types states what a result is worth for the whole
    tournament, and goes to scoresystem.add_unplayed() under its type letter. A blank
    type names no result, so there is nothing for a score system to hold: the reader
    used to create the keys " " and " G" in the match score system and accept the file,
    which adjusted nobody's standing and left two nonsense keys behind. The record
    means "every competitor, every round, -1.0", and that is refused like the scoped
    form, naming the scope it was read as.
    """
    chessfile = trf2json.trf2json()

    with pytest.raises(errors.GacruxInputError) as excinfo:
        chessfile.parse_file("\n".join(two_rounds([points_only_line(" ", "", "-1.0")])), 0)

    message = str(excinfo.value)
    assert "299" in message
    assert "every round, every player" in message
    assert "-1.0" in message
    assert chessfile.get_status() == 401
    assert " " not in chessfile.scores.score["match"]
    assert " G" not in chessfile.scores.score["match"]


def test_a_blank_299_of_zero_points_is_accepted():
    """A blank-type record of 0.0 adjusts nothing, and is read like any inert record.

    Scoped or not, an adjustment of zero leaves every standing where it was, so the
    engine reports exactly what a record-299-aware engine would report. Refusing it
    would lose a file the engine scores right. It is read and kept -- an implementation
    of record 299 finds it in aatlist -- and it puts nothing into the score system.
    """
    for record in [abnormal_line(" ", "", "0.0", 1, [1]), points_only_line(" ", "", "0.0")]:
        chessfile = parse(two_rounds([record]))

        assert chessfile.get_status() == 0
        assert [att["att"] for att in chessfile.aatlist] == [" "]
        assert " " not in chessfile.scores.score["match"]
        assert " G" not in chessfile.scores.score["match"]
        tournament = chessfile.get_tournament(1)
        assert next(c for c in tournament["competitors"] if c["cid"] == 1)["gamePoints"] == decimal.Decimal("1.5")


def test_scoped_299_is_refused_without_verbose_too():
    """The refusal is a decision of the reader, not a side effect of verbose mode.

    A program that is handed a file reads it with verbose off, and pass 2 of
    read_all_lines() then swallows an untyped exception into status 401 and stops. The
    refusal is a GacruxInputError raised after the file is read, so the caller sees the
    same message whether or not it asked to see failures -- and it sees a message about
    record 299 rather than the generic "Error in trf-file, line N".
    """
    chessfile = trf2json.trf2json()

    with pytest.raises(errors.GacruxInputError) as excinfo:
        chessfile.parse_file("\n".join(two_rounds([abnormal_line("W", "", "2.0", 1, [1])])), 0)

    assert "299" in str(excinfo.value)
    assert chessfile.get_status() == 401
