# -*- coding: utf-8 -*-
"""In-process adapter over this repository's own engine, driven exactly as
``tests/corpus/_harness.py`` already does: import the engine modules once per
worker and run the real read -> prepare -> pair path through
``pairingchecker.common_main()`` with a synthesised ``sys.argv``, rather than
reimplementing any of it. Implements the ``Engine`` protocol in
``engines/base.py``.

``-p -n <round>`` mode is used instead of ``_harness.py``'s ``-c`` check mode:
that asks the engine for its own prescribed pairing of exactly one round,
which is what the comparison needs. The result is read off
``self.resultjson["pairingResult"]["pairs"]``: a list of ``[white_cid,
black_cid]`` pairs in the engine's own board order, with ``black_cid == 0``
marking the pairing-allocated bye (see pairingchecker.py's module docstring).

``cid`` (competitor id) was spot-checked empirically against a corpus fixture
and confirmed to equal the TRF starting rank for a TRF-loaded tournament:
trf2json.parse_trf_player sets ``competitor["cid"] = startno`` directly (the
value parsed from record 001's own starting-rank column, line[4:8]) and
nothing downstream remaps it -- the one thing that would (the "fakerank"
experimental flag) is never set by this adapter. So no translation is needed
between cid and startno here; if that ever changed, this file is where a
mapping would need to be added.
"""
import contextlib
import io
import os
import sys
import tempfile

INTEROP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(INTEROP_DIR))
for path in (REPO_ROOT, INTEROP_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import pairingchecker  # noqa: E402
import version  # noqa: E402

from engines.base import Outcome  # noqa: E402
from normalize import normalize_pairing  # noqa: E402

_TMPDIR = tempfile.gettempdir()

# Status codes commonmain.do_command maps a GacruxNoLegalPairing to (see
# commonmain.py's do_command docstring): "this round of this tournament has no
# admissible pairing" is a state of the tournament, not a defect of the
# engine, and is reported as 505 rather than raised.
NO_LEGAL_PAIRING_CODE = 505

VARIANTS = {
    # This repository has both a default pairing path and an "-x weighted"
    # mode (pairing.py: self.optimize = "weighted" not in self.experimental).
    # Registering both as variants of the same engine directly addresses
    # whether the two implementations follow the same priorities.
    "default": [],
    "weighted": ["weighted"],
}


def _scratch(suffix):
    # One scratch path per process, so xdist workers can never clobber each
    # other's input or output file -- the same _harness.py _scratch() pattern.
    return os.path.join(_TMPDIR, "tiebreak_interop_tbs_%d.%s" % (os.getpid(), suffix))


class TieBreakServerEngine:
    """Adapter over this repository's own pairing engine. This is the
    reference implementation the sweep is checking, so it has nothing of its
    own to screen out -- every fixture in the corpus is, by construction,
    something it can read (see tests/corpus/README.md); screening for what
    the *comparison* engine cannot handle lives in external_engine.py."""

    def __init__(self, variant="default"):
        if variant not in VARIANTS:
            raise ValueError("unknown tiebreakserver variant: %r" % (variant,))
        self.variant = variant
        self.name = "tiebreakserver"
        self.version = version.version()["version"]

    def screen(self, case):
        return None

    def pair(self, trf, round_no):
        """Returns ``(outcome, raw)`` -- see ``Engine.pair`` in
        ``engines/base.py`` for the shape of ``raw``."""
        input_path = _scratch("trf")
        output_path = _scratch("out")
        with open(input_path, "w", encoding="latin1") as handle:
            handle.write(trf)

        obj = pairingchecker.pairingchecker()
        argv = ["checker", "-i", input_path, "-o", output_path, "-p", "-n", str(round_no)]
        if VARIANTS[self.variant]:
            argv += ["-x"] + VARIANTS[self.variant]

        saved_argv = sys.argv
        sys.argv = argv
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    obj.common_main()
                except SystemExit:
                    pass
                except Exception as exc:  # pragma: no cover - defensive, see _harness.py
                    return Outcome.error(code=510, message="%s: %s" % (type(exc).__name__, exc)), None
        finally:
            sys.argv = saved_argv

        status = obj.resultjson.get("status", {})
        code = status.get("code")

        if code == NO_LEGAL_PAIRING_CODE:
            return Outcome.no_legal_pairing(), None

        if code != 0:
            message = status.get("error")
            return Outcome.error(code=code, message=message), None

        pairing_result = obj.resultjson.get("pairingResult") or {}
        raw_pairs = pairing_result.get("pairs")
        if not raw_pairs:
            return Outcome.error(code=code, message="empty pairing result"), None

        raw = [(int(w), int(b)) for w, b in raw_pairs]
        return normalize_pairing(raw), raw
