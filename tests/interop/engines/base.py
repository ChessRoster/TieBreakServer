# -*- coding: utf-8 -*-
"""The engine interface and the outcome model, per PLAN-REGRESSION.md sections
4 and 6.1.

Every engine adapter -- ``tiebreakserver.py`` (in-process, this repository's
own engine) and ``bbppairings.py`` (subprocess, the independent oracle) --
implements the same three-member ``Engine`` protocol below and returns the
same ``Outcome`` shape, so nothing upstream of an adapter (the truncation
transform, normalisation, classification, the runner, the report) is specific
to either engine. Adding a second comparison engine (JaVaFo, say) is a new
module implementing this protocol plus a registry entry, not a rewrite.
"""
from dataclasses import dataclass
from typing import FrozenSet, Optional, Protocol, Tuple


# -- Outcome ------------------------------------------------------------------
#
# Each engine, for each (fixture, round), returns exactly one of:
#
#   PAIRED(pairs, pab)   a pairing was produced
#   NO_LEGAL_PAIRING     the engine states no legal pairing exists (bbp exit 1)
#   ERROR(code, message) anything else -- a crash, a timeout, an unsupported
#                        input the adapter did not screen out in advance
#
# PAIRED is always carried in canonical form: `pairs` is a frozenset of
# (white_startno, black_startno) tuples and `pab` is the starting rank
# receiving the pairing-allocated bye, or None. Board order is deliberately
# not part of this form -- see normalize.py and PLAN-REGRESSION.md section 4's
# "board order is a secondary, non-blocking dimension".

PAIRED = "PAIRED"
NO_LEGAL_PAIRING = "NO_LEGAL_PAIRING"
ERROR = "ERROR"

TAGS = frozenset({PAIRED, NO_LEGAL_PAIRING, ERROR})


@dataclass(frozen=True)
class Outcome:
    """One engine's answer for one (fixture, round).

    Exactly one of the following combinations of fields is meaningful,
    selected by ``tag``:

    - ``PAIRED``: ``pairs`` and ``pab`` are set, ``code``/``message`` are None.
    - ``NO_LEGAL_PAIRING``: every payload field is None.
    - ``ERROR``: ``code`` and/or ``message`` describe what went wrong; ``pairs``
      and ``pab`` are None.

    Construct via the classmethods below rather than the constructor directly
    -- they enforce that shape.
    """

    tag: str
    pairs: Optional[FrozenSet[Tuple[int, int]]] = None
    pab: Optional[int] = None
    code: Optional[object] = None
    message: Optional[str] = None

    def __post_init__(self):
        if self.tag not in TAGS:
            raise ValueError("unknown Outcome tag: %r" % (self.tag,))
        if self.tag != PAIRED and (self.pairs is not None or self.pab is not None):
            raise ValueError("pairs/pab are only meaningful on a PAIRED outcome")

    @classmethod
    def paired(cls, pairs, pab=None):
        return cls(tag=PAIRED, pairs=frozenset(pairs), pab=pab)

    @classmethod
    def no_legal_pairing(cls):
        return cls(tag=NO_LEGAL_PAIRING)

    @classmethod
    def error(cls, code=None, message=None):
        return cls(tag=ERROR, code=code, message=message)

    @property
    def is_paired(self):
        return self.tag == PAIRED

    @property
    def is_no_legal_pairing(self):
        return self.tag == NO_LEGAL_PAIRING

    @property
    def is_error(self):
        return self.tag == ERROR


# -- Engine protocol ------------------------------------------------------------


class Engine(Protocol):
    """The interface every engine adapter (and every -x variant of one)
    implements. See PLAN-REGRESSION.md section 6.1."""

    name: str
    version: str

    def screen(self, case) -> Optional[str]:
        """Return None if this engine can handle ``case``, else the reason it
        cannot (a short human-readable string, e.g. "team tournament" or
        "record 299 (abnormal assignment points)"). Screening is declarative:
        it inspects the fixture, never runs the engine and interprets a
        failure -- see PLAN-REGRESSION.md section 6.4. ``case`` is whatever
        the runner passes (at minimum, the fixture's raw TRF text and its
        record-prefix set); an adapter that never needs to screen anything out
        may simply always return None."""
        ...

    def pair(self, trf: str, round_no: int) -> Outcome:
        """Pair round ``round_no`` of a TRF already truncated to the results of
        rounds ``1..round_no - 1`` (see trftrunc.truncate). Must not raise for
        an ordinary pairing failure -- that is NO_LEGAL_PAIRING, a first-class
        outcome, not an exception. Anything unexpected (a crash, a timeout, a
        malformed response) is caught by the adapter and returned as ERROR
        rather than propagated."""
        ...
