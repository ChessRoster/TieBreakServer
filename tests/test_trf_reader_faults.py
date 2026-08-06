# -*- coding: utf-8 -*-
"""
Regression tests for what the reader does with a record it could not parse.

read_all_lines reads the records in two passes. A parser that raises something the
reader did not anticipate was recorded as status 401 -- naming the line and quoting it,
which is everything the caller needs -- and then the reader returned. Bare.

parse_file assigns that return to self.all_lines and immediately reads it:

    self.all_lines = self.read_all_lines(tournament, alines, verbose)
    self.scores.update_gamescore(..., "162" in self.all_lines or "222" in self.all_lines)

so the caller does not see the 401 and does not see the record. It sees

    TypeError: argument of type 'NoneType' is not a container or iterable

raised at a line about score systems, which is not where anything went wrong. The one
piece of information the reader had -- which record, and what was in it -- is discarded
in the act of reporting it.

The field that provoked this in practice is the FIDE id of record 001. It is read with
int(), and programs that keep their own registration state in the same field write text
there for a competitor who has not been assigned one yet.
"""
import pytest

import errors
import trf2json


def player_line(startno, name, fideid):
    # Record 001 at the columns TRF-2026 gives it. fideid is written as text so a test
    # can put something in the field that is not a number.
    line = list(" " * 91)
    line[0:3] = "001"
    line[4:8] = "%4d" % startno
    line[9] = "m"
    line[14 : 14 + len(name)] = name
    line[48:52] = "%4d" % 2000
    line[53:56] = "NOR"
    line[57:68] = "%11s" % fideid
    line[80:84] = "%4s" % "0.0"
    line[85:89] = "%4d" % startno
    return "".join(line)


def tournament(fideids):
    lines = ["012 Reader faults", "042 2026-03-01", "XXR 3"]
    names = ["One, Player", "Two, Player", "Three, Player", "Four, Player"]
    lines += [player_line(i, names[i - 1], fideid) for i, fideid in enumerate(fideids, start=1)]
    return lines


def parse(lines, verbose=0):
    chessfile = trf2json.trf2json()
    # verbose off: this is how a program that is handed a file reads it, and it is the
    # setting under which the reader used to swallow what it knew and crash later.
    chessfile.parse_file("\n".join(lines), verbose)
    return chessfile


def test_an_unparsable_record_raises_instead_of_returning_none():
    # 'NEW' where the FIDE id goes. int() cannot read it, and nothing in this file's
    # parsers expected that, so it arrives at the reader's last-resort handler.
    with pytest.raises(errors.GacruxInputError) as excinfo:
        parse(tournament([12345678, "NEW", 12475278, 12280430]))

    message = str(excinfo.value)
    assert "line 5" in message, "the message must name the record that failed"
    assert "Two, Player" in message, "and quote it, so the arbiter can find it"


def test_the_original_fault_is_still_reachable():
    # The exception the parser raised is the cause, so a caller debugging its own input
    # can still see what was actually wrong with the field.
    with pytest.raises(errors.GacruxInputError) as excinfo:
        parse(tournament([12345678, "NEW", 12475278, 12280430]))

    cause = excinfo.value.__cause__
    assert isinstance(cause, ValueError)
    assert "NEW" in str(cause)


def test_the_status_code_is_still_recorded():
    # The 401 is how a caller that reads status rather than catching exceptions learns
    # of this, and it must survive the change.
    chessfile = trf2json.trf2json()
    with pytest.raises(errors.GacruxInputError):
        chessfile.parse_file("\n".join(tournament([12345678, "NEW", 12475278, 12280430])), 0)

    assert chessfile.get_status() == 401


def test_verbose_still_lets_the_original_exception_through_untouched():
    # With verbose on, the reader has always re-raised what the parser raised. A caller
    # debugging a file wants that exception, not one wrapped around it.
    with pytest.raises(ValueError) as excinfo:
        parse(tournament([12345678, "NEW", 12475278, 12280430]), verbose=1)

    assert "NEW" in str(excinfo.value)


def test_a_tournament_whose_records_all_parse_still_reads():
    # The handler must not be reachable from valid input.
    chessfile = parse(tournament([12345678, 12475278, 12280430, 12024550]))
    assert chessfile.get_status() == 0
    assert len(chessfile.get_tournament(1)["competitors"]) == 4
