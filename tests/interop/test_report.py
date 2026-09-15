# -*- coding: utf-8 -*-
"""Unit tests for report.py's aggregation, notably the board-order table."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import report  # noqa: E402


def _comparison(cls, board_order_only_difference, variant="default"):
    return {
        "kind": "comparison",
        "tiebreakserver_variant": variant,
        "class": cls,
        "board_order_only_difference": board_order_only_difference,
    }


def test_pairing_class_row_is_not_counted_as_same_board_order():
    """A PAIRING-class row is a real pairing divergence, not an ordering one.

    ``is_board_order_only_difference`` answers False both when two raw
    pairing lists are identical (truly the same board order) and when they
    carry entirely different pairs (a PAIRING-class row, where "board order"
    is not even a meaningful comparison -- the boards themselves differ).
    ``summarize`` used to bucket every False alongside the identical case as
    "same board order", so the Board-order table's "same" column silently
    absorbed genuine pairing divergences instead of leaving them out of a
    table that is documented as never gating on anything but order.

    This constructs one PAIRING-class row exactly as the (unfixed) runner
    would have written it -- ``board_order_only_difference: False`` -- and
    checks it is not counted as "same".
    """
    comparisons = [_comparison("PAIRING", False)]

    by_variant, board_order = report.summarize(comparisons)

    assert board_order["default"]["same"] == 0
    assert board_order["default"]["order_only"] == 0
    assert board_order["default"]["na"] == 1


def test_match_and_colour_rows_still_use_the_board_order_signal():
    """The gate does not swallow the legitimate MATCH/COLOUR signal."""
    comparisons = [
        _comparison("MATCH", False),
        _comparison("MATCH", True),
        _comparison("COLOUR", True),
    ]

    by_variant, board_order = report.summarize(comparisons)

    assert board_order["default"]["same"] == 1
    assert board_order["default"]["order_only"] == 2
    assert board_order["default"]["na"] == 0


def test_pairability_and_inconclusive_rows_are_not_applicable():
    comparisons = [
        _comparison("PAIRABILITY", None),
        _comparison("INCONCLUSIVE", None),
    ]

    by_variant, board_order = report.summarize(comparisons)

    assert board_order["default"]["na"] == 2
