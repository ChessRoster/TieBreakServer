# -*- coding: utf-8 -*-
"""
Regression tests for the match- and game-point totals TRF-2026 record 310 declares.

Record 310 is the team section: the team pairing number in columns 5-7, the name in
9-40, the match points in 55-60, the game points in 62-67, the rank in 69-71, and the
pairing numbers of its players from 74 on. The two point fields are the team's standing,
and the reader recomputes them rather than trusting them -- a file whose standings
contradict its own results is a file whose pairing cannot be right.

A check like this earns its place only if it agrees with valid input, because it does not
reject a team: it rejects the event. The two things it has to get right are which rounds
record 310's totals cover, and what it tells a user who has to act on a rejection.

Which rounds. Not the ones up to tournament["currentRound"]: parse_trf_player() advances
that only for a game actually played against a real opponent, so a round decided entirely
by forfeit -- a whole match awarded under record 330, with nobody at the board -- never
advances it. Those results are in record 310's totals and they have to be in the
calculated ones. The rounds are read off the match list instead: a round in which two
teams were set against each other is a round that has produced a result, and a round
whose only entry is a bye or a pairing-allocated bye for one team is a round that has
been announced and not yet played.

What it says. The message reads "Record 310 disagrees with the results of rounds 1 - 3:
team 1 declares 5.0 match points, the matches give 6.0; team 2 declares 2.0 game points,
the 001 records of its players give 1.0": which rounds the reader counted, which team,
and both figures. A message that named only the teams would leave out the round count
and the figures, and the whole of the difficulty is in exactly those two things. A
validation whose message cannot be acted on is only a way to lose a file.

Which game points. TRF-2026 defines the 001 points column of a team event as the points
scored over-the-board or in forfeit wins, so a pairing-allocated bye is not in it and is
declared in record 320 alone; files in the wild add the bye to the 001 column too. The
check accepts a record 310 that agrees with either sum.
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


VALUE = {"1": "1.0", "+": "1.0", "U": "1.0", "=": "0.5", "0": "0.0", "-": "0.0"}


def two_teams(rounds, matchpoints, gamepoints, extra=(), byeround=False):
    """A two-team, two-board event over `rounds` rounds, with the totals the caller gives.

    Round 1 is team 1 as the white team and team 1 wins it 1.5 - 0.5; round 2 is team 2
    as the white team and team 1 wins it 1.5 - 0.5 again. Round 3, when it is there, is
    the round the tests vary: every board of it is a forfeit and record 330 says so, or,
    with `byeround`, every board of it is a pairing-allocated bye for both teams at once.

    The declared record-310 totals are arguments so that a test can hand the reader a
    correct file or an incorrect one without changing anything else about it.
    """
    games = [
        # player 1, team 1                 player 2, team 1
        [(3, "w", "1"), (3, "b", "=")],    [(4, "b", "="), (4, "w", "1")],
        # player 3, team 2                 player 4, team 2
        [(1, "b", "0"), (1, "w", "=")],    [(2, "w", "="), (2, "b", "0")],
    ]
    if rounds > 2 and byeround:
        # Nobody was paired at all: every player of both teams records "U", the TRF code
        # for a pairing-allocated bye, against no opponent.
        for game in games:
            game.append((0, "-", "U"))
    elif rounds > 2:
        # A forfeited match, board by board: the two players of team 1 are awarded the
        # point ("+"), the two players of team 2 forfeit it ("-"), and nobody has an
        # opponent, because the match was never set up.
        for player, result in enumerate(["+", "+", "-", "-"]):
            games[player].append((0, "-", result))
    points = [sum((decimal.Decimal(VALUE[g[2]]) for g in game), decimal.Decimal("0.0"))
              for game in games]

    lines = ["012 Team score totals", "042 2026-03-01", "XXR %d" % rounds, "352 WB"]
    lines.append(team_line(1, "Team One", [1, 2], matchpoints[0], gamepoints[0]))
    lines.append(team_line(2, "Team Two", [3, 4], matchpoints[1], gamepoints[1]))
    for startno, name in enumerate(["One", "Two", "Three", "Four"]):
        lines.append(player_line(startno + 1, name + ", Player", 2400 - 100 * startno,
                                 "%.1f" % points[startno], games[startno]))
    if rounds > 2 and not byeround:
        # Record 330: "+-" in columns 5-6 is the white team winning the forfeited match,
        # the round is in 8-10 and the two team pairing numbers in 12-14 and 16-18.
        lines.append("330 +-   3   1   2")
    return lines + list(extra)


def three_teams_with_an_announced_bye(matchpoints, gamepoints, byes):
    """A three-team event, two rounds played, whose record 320 also names round 3's bye.

    Three teams means one of them sits out every round, and TRF-2026 record 320 is where
    that is written: the match points of a pairing-allocated bye in columns 5-8, its game
    points in 10-13, and then one team pairing number per round from column 15 on. Here a
    bye is worth one match point and two game points, one for each board.

    `byes` is that per-round list. Rounds 1 and 2 have been played; the third number is
    the bye of a round that has not, which is the case under test -- the arbiter has made
    the pairing and the file says so, and none of it has happened yet.
    """
    lines = ["012 Announced bye", "042 2026-03-01", "XXR 3", "352 WB"]
    lines.append(team_line(1, "Team One", [1, 2], matchpoints[0], gamepoints[0]))
    lines.append(team_line(2, "Team Two", [3, 4], matchpoints[1], gamepoints[1]))
    lines.append(team_line(3, "Team Three", [5, 6], matchpoints[2], gamepoints[2]))
    # Round 1: team 1 beats team 2 by 1.5 - 0.5, team 3 sits out. Round 2: team 3 draws
    # team 1 by 1 - 1, team 2 sits out. "U" is the TRF code for a pairing-allocated bye.
    lines.append(player_line(1, "One, Player", 2400, "1.5", [(3, "w", "1"), (5, "b", "=")]))
    lines.append(player_line(2, "Two, Player", 2300, "1.0", [(4, "b", "="), (6, "w", "=")]))
    lines.append(player_line(3, "Three, Player", 2200, "1.0", [(1, "b", "0"), (0, "-", "U")]))
    lines.append(player_line(4, "Four, Player", 2100, "1.5", [(2, "w", "="), (0, "-", "U")]))
    lines.append(player_line(5, "Five, Player", 2000, "1.5", [(0, "-", "U"), (1, "w", "=")]))
    lines.append(player_line(6, "Six, Player", 1900, "1.5", [(0, "-", "U"), (2, "b", "=")]))
    lines.append("320  1.0  2.0 " + " ".join("%03d" % bye for bye in byes))
    return lines


def parse(lines):
    chessfile = trf2json.trf2json()
    # verbose off: this is how a program that is handed a file reads it.
    chessfile.parse_file("\n".join(lines), 0)
    return chessfile


def test_record_310_accepts_latest_all_forfeit_round():
    """A last round decided entirely by forfeit is a round record 310 counts.

    Round 3 of this file is one match, awarded to team 1 under record 330 with nobody at
    the board: every 001 record shows "+" or "-" against no opponent, so no game of it was
    played against a real opponent and parse_trf_player() leaves currentRound at 2. The
    declared totals count it all the same -- record 310 is the standing after round 3, and
    a forfeit is worth what a win is worth -- so team 1 declares 6.0 match points for its
    three wins and team 2 declares 0.0.

    Reading the rounds off the match list is what makes those two agree: the round has a
    match between two teams in it, which is the thing that says a round has produced a
    result, and it is true of a forfeited match as much as of a played one. Asserting the
    parsed match points as well as the status is what distinguishes "the check was
    satisfied" from "the check was skipped".
    """
    chessfile = parse(two_teams(3, ["6.0", "0.0"], ["5.0", "1.0"]))

    assert chessfile.get_status() == 0
    tournament = chessfile.get_tournament(1)
    assert tournament["currentRound"] == 2          # no round-3 game was played
    forfeited = [match for match in tournament["matchList"] if match["round"] == 3]
    assert [(match["white"], match["black"], match["wResult"], match["bResult"])
            for match in forfeited] == [(1, 2, "W", "Z")]
    assert {competitor["cid"]: competitor["matchPoints"]
            for competitor in tournament["competitors"]} == {1: decimal.Decimal("6.0"),
                                                             2: decimal.Decimal("0.0")}


def test_record_310_ignores_a_bye_for_a_future_round():
    """A pairing-allocated bye for a round that has not been played is not in the totals.

    Record 320 carries one team per round, and an arbiter fills the next round's in as
    soon as the pairing is made. Here rounds 1 and 2 have been played -- team 3 sat out
    the first, team 2 the second -- and the third number is team 1's bye in a round 3 that
    has not happened. Record 310 is the standing after round 2, so the point that bye is
    worth is not in it yet.

    Round 3 of the match list holds nothing but that bye: one entry, one team, no
    opponent. That is what tells the two cases apart -- an all-forfeit round has two teams
    set against each other and an announced bye does not -- and it is why the rule cannot
    be "count everything" any more than it can be "count up to currentRound".
    """
    chessfile = parse(three_teams_with_an_announced_bye(
        ["3.0", "1.0", "2.0"], ["2.5", "2.5", "3.0"], [3, 2, 1]))

    assert chessfile.get_status() == 0
    tournament = chessfile.get_tournament(1)
    roundthree = [match for match in tournament["matchList"] if match["round"] == 3]
    assert [(match["white"], match.get("black", 0), match["wResult"]) for match in roundthree] == [(1, 0, "P")]
    # Team 1's two wins-worth of match points, and not the third one the announced bye
    # would have added.
    assert {competitor["cid"]: competitor["matchPoints"]
            for competitor in tournament["competitors"]} == {1: decimal.Decimal("3.0"),
                                                             2: decimal.Decimal("1.0"),
                                                             3: decimal.Decimal("2.0")}


def test_record_310_mismatch_names_the_team_and_the_round():
    """A record 310 that really is wrong is still refused, and says what is wrong with it.

    The same three-round file, with team 1's declared match points changed from 6.0 to
    5.0 and team 2's declared game points from 1.0 to 2.0. Nothing else moves, so the
    figures the message quotes can only have come from the comparison.

    The message has to carry three things, and each of them answers a question the user
    would otherwise have to answer by hand. Which team: 1 and 2 here, and not the ones
    that agree. Which rounds the reader counted: rounds 1 - 3, which is how a user finds
    out that the reader and the file disagree about how much of the event has happened --
    the single most likely reason for a total to be off. And both figures, declared
    against calculated, because "5.0 declared, 6.0 calculated" is a difference of one
    win and says where to look, while "incorrect" does not.

    Match points and game points are checked against two different things, and the message
    says which: the match points against the results of the matches, the game points
    against the totals the players' own 001 records report.
    """
    with pytest.raises(errors.GacruxInputError) as excinfo:
        parse(two_teams(3, ["5.0", "0.0"], ["5.0", "2.0"]))

    message = str(excinfo.value)
    assert "310" in message                                    # the record it is about
    assert "rounds 1 - 3" in message                           # what the reader counted
    assert "team 1 declares 5.0 match points" in message       # declared
    assert "the matches give 6.0" in message                   # calculated
    assert "team 2 declares 2.0 game points" in message
    assert "give 1.0" in message


def test_record_310_mismatch_is_reported_as_a_status_as_well():
    """The refusal reaches a caller that reads the status and never sees the exception.

    Every other refusal in the reader records status 401 and raises, and this one has to
    do both for the same reason: a program embedding the engine may look at only one of
    them, and a file rejected in silence is the failure this whole check exists to
    prevent.
    """
    chessfile = trf2json.trf2json()

    with pytest.raises(errors.GacruxInputError):
        chessfile.parse_file("\n".join(two_teams(3, ["5.0", "0.0"], ["5.0", "1.0"])), 0)

    assert chessfile.get_status() == 401
    assert any("310" in error for error in chessfile.chessjson["status"]["error"])


def test_record_310_unknown_team_reports_a_typed_error():
    """A match played by a team record 310 never declared is a typed error, not a KeyError.

    The totals are accumulated into a dict keyed by the team pairing numbers record 310
    declares, and the match list is indexed straight into it. Every record that names a
    team is checked as it is read, so this is the last place a number that names nobody
    can still arrive -- and an unguarded index turns it into a bare KeyError from inside
    the reader, which tells the caller nothing and is not one of the three exceptions
    errors.py says the engine raises.

    The match is added to a file that reads cleanly, so the only thing wrong with the
    tournament is the one thing under test. validate_team_scores() is called directly
    because the reader's own records cannot produce this state -- check_pairing_number()
    stops a bad number in records 240, 300, 310, 320 and 330 before it gets here -- and a
    guard against a state that is currently unreachable is exactly the kind that stops
    being tested if it is only ever reached through a file.
    """
    chessfile = parse(two_teams(2, ["4.0", "0.0"], ["3.0", "1.0"]))
    tournament = chessfile.get_tournament(1)
    tournament["matchList"].append(
        {"id": 0, "round": 2, "white": 9, "black": 1, "played": True, "wResult": "W", "bResult": "L"}
    )

    with pytest.raises(errors.GacruxInputError) as excinfo:
        chessfile.validate_team_scores(tournament)

    message = str(excinfo.value)
    assert "team 9" in message       # the number that names nobody
    assert "310" in message          # the record that would have declared it
    assert "round 2" in message      # where it was found
    assert "1 - 2" in message        # the numbers that would have been right


def test_record_310_totals_accept_a_pab_recorded_only_in_320():
    """The 001 points column of a team event leaves the pairing-allocated bye out.

    TRF-2026, record 001, columns 81-84: "In team competitions, it is an informative
    field that shows the number of points the player scored over-the-board or in
    forfeit wins (standard score)." A player whose team had the pairing-allocated bye
    writes "0000 - U" for the round and does not add the bye to that field; the bye's
    game points live in record 320 alone, and the team's total including them in record
    310. This file is written exactly that way: three one-player teams, one round, team
    1 has the PAB, player 1 reports 0.0, record 320 makes the bye worth 1.0 match point
    and 1.0 game point, and record 310 gives team 1 1.0 of each.

    The check summed the players' 001 totals and compared that with record 310, so this
    spec-shaped file was refused: "team 1 declares 1.0 game points, the 001 records of
    its players give 0.0". Files that add the bye to the 001 field as well -- every one
    in the corpus, and the fixtures above -- must keep reading, so the check accepts a
    record 310 that agrees with either sum.
    """
    lines = ["012 PAB recorded in 320 only", "042 2026-03-01", "XXR 1", "352 W"]
    lines.append(team_line(1, "Team One", [1], "1.0", "1.0"))
    lines.append(team_line(2, "Team Two", [2], "0.0", "0.0"))
    lines.append(team_line(3, "Team Three", [3], "2.0", "1.0"))
    lines.append(player_line(1, "One, Player", 2400, "0.0", [(0, "-", "U")]))
    lines.append(player_line(2, "Two, Player", 2300, "0.0", [(3, "b", "0")]))
    lines.append(player_line(3, "Three, Player", 2200, "1.0", [(2, "w", "1")]))
    lines.append("320  1.0  1.0 001")

    chessfile = parse(lines)

    assert chessfile.get_status() == 0
    tournament = chessfile.get_tournament(1)
    assert {competitor["cid"]: (competitor["matchPoints"], competitor["gamePoints"])
            for competitor in tournament["competitors"]} == {
        1: (decimal.Decimal("1.0"), decimal.Decimal("1.0")),
        2: (decimal.Decimal("0.0"), decimal.Decimal("0.0")),
        3: (decimal.Decimal("2.0"), decimal.Decimal("1.0")),
    }


def test_a_correct_record_310_still_reads():
    """The control: the same two files with the totals they should have.

    Both of these are ordinary valid team files, and neither of them may be rejected by
    anything done to make the two cases above work.
    """
    assert parse(two_teams(2, ["4.0", "0.0"], ["3.0", "1.0"])).get_status() == 0
    assert parse(three_teams_with_an_announced_bye(
        ["3.0", "1.0", "2.0"], ["2.5", "2.5", "3.0"], [3, 2, 0])).get_status() == 0


def test_record_310_counts_a_round_every_team_sat_out():
    """A round in which nobody was paired still counts, because the players recorded it.

    This is the shape of a team file whose last rounds have not been contested at all:
    every player of every team writes "U" against no opponent, so each team's round is a
    pairing-allocated bye, worth one match point under the default match score system.
    Record 310's totals include those points -- team 1 declares 5.0 for two wins and a
    bye, team 2 declares 1.0 for the bye alone -- so the check has to include them too.

    Round 3 has no match between two teams, which is exactly the shape of the announced
    bye in the test above, and the two must not be treated alike. What separates them is
    whether the round reached the 001 records at all: here every player wrote a round-3
    entry, and for an announced bye no player has one, because the round has not happened.
    So the question is asked of the game list -- has anybody recorded anything for this
    round -- and not of the round number, and not of currentRound.
    """
    chessfile = parse(two_teams(3, ["5.0", "1.0"], ["5.0", "3.0"], byeround=True))

    assert chessfile.get_status() == 0
    tournament = chessfile.get_tournament(1)
    assert tournament["currentRound"] == 2          # no round-3 game was played
    roundthree = sorted(
        (match["white"], match.get("black", 0), match["wResult"], len(match["games"]))
        for match in tournament["matchList"] if match["round"] == 3
    )
    # Two byes, no match between teams, and two game records behind each bye.
    assert roundthree == [(1, 0, "P", 2), (2, 0, "P", 2)]
    assert {competitor["cid"]: competitor["matchPoints"]
            for competitor in tournament["competitors"]} == {1: decimal.Decimal("5.0"),
                                                             2: decimal.Decimal("1.0")}


def test_an_announced_bye_and_a_sat_out_round_are_told_apart_by_the_game_list():
    """The two bye shapes, side by side, so the discriminator is visible in one place.

    Both files end in a round whose only match-list entries are byes with no opponent,
    and both byes carry the same result letter, "P". Neither the round number, nor
    currentRound, nor the result tells them apart. The game list does: the sat-out round
    has one game record per player and the announced one has none at all.

    The second assertion is here because the obvious discriminator is the wrong one. It
    is tempting to ask how many games games2matches left on the bye itself, and that
    number answers a different question: build_tmatches() empties the game list of every
    bye that a record 240, 320 or 330 declared and keeps it on a bye that only the 001
    records produced. So the announced bye and the sat-out bye do differ there -- but so
    would two byes in the same played round, one of which a record 320 happened to name.
    Pinning that here records why the reader must not read anything into it.
    """
    announced = parse(three_teams_with_an_announced_bye(
        ["3.0", "1.0", "2.0"], ["2.5", "2.5", "3.0"], [3, 2, 1])).get_tournament(1)
    satout = parse(two_teams(3, ["5.0", "1.0"], ["5.0", "3.0"], byeround=True)).get_tournament(1)

    def games_in(tournament, rnd):
        return len([game for game in tournament["gameList"] if game["round"] == rnd])

    assert games_in(announced, 3) == 0    # nobody has an entry: the round has not happened
    assert games_in(satout, 3) == 4       # every player recorded their bye

    # And the count games2matches leaves on the bye, which says which record made the bye
    # rather than whether the round happened. Team 3's round-1 bye is a bye in a round
    # that was certainly played, and it is as empty as the announced one.
    def bye_games(tournament, rnd):
        return [len(match["games"]) for match in tournament["matchList"]
                if match["round"] == rnd and match.get("black", 0) == 0]

    assert bye_games(announced, 1) == [0]     # played round, but record 320 named it
    assert bye_games(announced, 3) == [0]     # announced round
    assert bye_games(satout, 3) == [2, 2]     # no record named these, so they kept theirs
