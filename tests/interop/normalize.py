# -*- coding: utf-8 -*-
"""Canonical Outcome form and the six-way classifier. See PLAN-REGRESSION.md
section 4 for the table this module implements.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engines.base import Outcome  # noqa: E402

MATCH = "MATCH"
COLOUR = "COLOUR"
PAIRING = "PAIRING"
PAIRABILITY = "PAIRABILITY"
INCONCLUSIVE = "INCONCLUSIVE"
SKIPPED = "SKIPPED"


def normalize_pairing(raw_pairs):
    """Canonicalise a raw pairing -- a list of (white, black) starting-rank
    tuples in board order, with 0 marking whichever side receives the
    pairing-allocated bye -- into the PAIRED Outcome form: ``pairs`` a
    frozenset of (white_startno, black_startno), and ``pab`` the starting
    rank receiving the bye, or None. Board order is not part of the canonical
    form; see ``is_board_order_only_difference`` below for that comparison.
    """
    pairs = set()
    pab = None
    for white, black in raw_pairs:
        if white == 0 and black == 0:
            continue
        if black == 0:
            pab = white
            continue
        if white == 0:
            pab = black
            continue
        pairs.add((white, black))
    return Outcome.paired(pairs, pab)


def _unordered_pairs(pairs):
    """A pairing with colours stripped: a frozenset of frozenset({a, b})."""
    return frozenset(frozenset(pair) for pair in pairs)


def classify(outcome_a, outcome_b):
    """Classify a pair of (already-normalised) Outcomes into one of the six
    classes of PLAN-REGRESSION.md section 4. Never returns SKIPPED -- that
    verdict is decided before either engine runs (see engines/base.py's
    ``screen``), not by comparing two outcomes."""
    if outcome_a.is_error or outcome_b.is_error:
        return INCONCLUSIVE

    if outcome_a.is_no_legal_pairing and outcome_b.is_no_legal_pairing:
        return MATCH

    if outcome_a.is_no_legal_pairing != outcome_b.is_no_legal_pairing:
        return PAIRABILITY

    # Both PAIRED from here on.
    if outcome_a.pairs == outcome_b.pairs and outcome_a.pab == outcome_b.pab:
        return MATCH

    if (
        outcome_a.pab == outcome_b.pab
        and _unordered_pairs(outcome_a.pairs) == _unordered_pairs(outcome_b.pairs)
    ):
        return COLOUR

    return PAIRING


def is_board_order_only_difference(raw_pairs_a, raw_pairs_b):
    """True if two raw (board-ordered) pairing lists carry exactly the same
    boards -- same pairs, same colours, same PAB -- just listed in a
    different order. This is the secondary, non-blocking board-order
    comparison of PLAN-REGRESSION.md section 4: bbpPairings' output order is
    a presentation ordering (its own ``sortResults``), not a claim about
    C.04 board assignment, so it is recorded but never gates a divergence.
    """
    a = [tuple(pair) for pair in raw_pairs_a]
    b = [tuple(pair) for pair in raw_pairs_b]
    return a != b and sorted(a) == sorted(b)
