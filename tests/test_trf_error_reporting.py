# -*- coding: utf-8 -*-
"""
Regression tests for the way trf2json reports a line it cannot parse.

read_all_lines() reads the file twice: pass 1 files every line under its three-character
record identifier, pass 2 hands each line to the parser for that identifier. A parser
that fails is the ordinary case this design is built for -- a TRF is typed by hand, and
a mistyped field is what the reader exists to report -- so pass 2 catches the failure,
records status 401 "Error in trf-file, line N, <the line>", and carries on.

That contract only holds if the caller is left with something to work with.
read_all_lines() returns the pass-1 structure, and parse_file() goes straight on to read
it:

    self.all_lines = self.read_all_lines(tournament, alines, verbose)
    self.scores.update_gamescore(..., "162" in self.all_lines or "222" in self.all_lines)

A `return` with no value in the error path hands parse_file() None, and `"162" in None`
raises TypeError: argument of type 'NoneType' is not iterable. The status code the
reader had just written is then never seen by anybody, and the caller is handed a
TypeError from a line of code that has nothing to do with the record that was wrong.

These tests hold the reader to reporting the record instead of dying on it.
"""
import pytest

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


def team_line(cid, name, players, matchpoints="0.0", gamepoints="0.0"):
    # Record 310, written at the columns TRF-2026 gives it:
    #     1 - 3    record identifier 310
    #     5 - 7    team pairing number
    #     9 - 40   team name
    #    55 - 60   match points
    #    62 - 67   game points
    #    69 - 71   rank
    #    74 - 77   1st player id, then 79 - 82, ...
    line = list(" " * 73)
    line[0:3] = "310"
    line[4:7] = "%3d" % cid
    line[8 : 8 + len(name)] = name
    line[54:60] = "%6s" % matchpoints
    line[61:67] = "%6s" % gamepoints
    line[68:71] = "%3d" % cid
    return "".join(line) + " ".join(["%4d" % player for player in players])


def teams(records):
    """Two teams of two players, two rounds played, plus whatever records the test adds.

    The declared record-310 totals are the totals of the two played rounds, so the file
    is valid on its own and the only thing under test is the record the caller appends.
    """
    lines = ["012 Error reporting, teams", "042 2026-03-01", "XXR 2", "352 WB"]
    lines.append(team_line(1, "Team One", [1, 2], "4.0", "3.0"))
    lines.append(team_line(2, "Team Two", [3, 4], "0.0", "1.0"))
    lines.append(player_line(1, "One, Player", 2400, "1.5", [(3, "w", "1"), (4, "w", "=")]))
    lines.append(player_line(2, "Two, Player", 2300, "1.5", [(4, "b", "="), (3, "b", "1")]))
    lines.append(player_line(3, "Three, Player", 2200, "0.5", [(1, "b", "0"), (2, "w", "=")]))
    lines.append(player_line(4, "Four, Player", 2100, "0.5", [(2, "w", "="), (1, "b", "0")]))
    return lines + records


def parse(lines):
    chessfile = trf2json.trf2json()
    # verbose off: this is how a program that is handed a file reads it, and it is the
    # setting under which the reader is meant to turn a bad record into a status code
    # rather than into an exception.
    chessfile.parse_file("\n".join(lines), 0)
    return chessfile


def test_unknown_forfeit_code_reports_the_line_number():
    """Record 330 field "Result" carries a two-character forfeit code.

    TRF-2026 record 330 is "<forfeited result> <round> <team> <team>", and the reader
    accepts the codes the specification and its predecessors write for the three
    outcomes of a forfeited match: "10"/"WL"/"WZ"/"+-", "00"/"LL"/"ZZ"/"--" and
    "01"/"LW"/"ZW"/"-+". "WW" is none of them -- there is no forfeited match both teams
    win -- and it reaches parse_forfeited() as a KeyError out of the translation table.

    A KeyError is exactly the untyped failure pass 2 is written to convert: the parser
    did not work out what was wrong, so the reader names the line and lets the caller
    look at it. The assertions are the whole of that contract -- the status code, the
    line number (the 330 record is the 11th line of the file), the text of the offending
    record -- and the run completing at all is what proves the return value survived,
    because a bare `return` here leaves parse_file() to raise TypeError on None before
    any of this can be asserted.
    """
    lines = teams(["330 WW   2   1   2"])
    assert lines[10] == "330 WW   2   1   2"          # the line the message must name

    chessfile = parse(lines)

    assert chessfile.get_status() == 401
    errors = chessfile.chessjson["status"]["error"]
    assert "Error in trf-file, line 11, 330 WW   2   1   2" in errors


def test_unknown_forfeit_code_raises_the_underlying_error_when_verbose():
    """The same record, read with verbose on, still re-raises.

    Pass 2 re-raises instead of recording a status when the caller asked to see the
    failure, and that path is unchanged: it is only the swallowing path that has to hand
    a structure back. Pinning both halves keeps a fix to one of them from quietly
    disabling the other.
    """
    with pytest.raises(KeyError):
        chessfile = trf2json.trf2json()
        chessfile.parse_file("\n".join(teams(["330 WW   2   1   2"])), True)


def test_a_file_with_no_bad_record_still_reads():
    """The guard must not cost the ordinary case: the same fixture without the bad
    record reads clean, so a failure of the two tests above is a failure of the error
    path and not of the fixture."""
    assert parse(teams([])).get_status() == 0
