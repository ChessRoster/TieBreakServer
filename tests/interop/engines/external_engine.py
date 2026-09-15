# -*- coding: utf-8 -*-
"""Subprocess adapter over an external pairing-engine binary that speaks the
JaVaFo-style pairing CLI/output convention -- the independent oracle the
interop sweep points this repository's engine at. See this directory's
README.md for the overall design and "Outcome model" for the classification
below.

Nothing here names a specific binary: which one to run, and what to call it
in a report, is supplied entirely at run time (see the env vars below), local
or from the interop-sweep GitHub Action's own workflow_dispatch URL input.

Command form: ``BINARY --dutch INPUT -p OUTPUT``. Exit 0 -> parse OUTPUT as
the JaVaFo-style pairing file (a count line, then one ``WHITE BLACK`` line
per board, ``0`` marking the pairing-allocated bye's opponent). Exit 1 ->
NO_LEGAL_PAIRING (a first-class outcome, not a failure). Anything else, or a
timeout, -> ERROR.

    TIEBREAK_INTEROP_ENGINE_BINARY   path to the binary
                                      (default: tests/interop/bin/engine.exe)
    TIEBREAK_INTEROP_ENGINE_NAME     report label (default: "external")
    TIEBREAK_INTEROP_ENGINE_VERSION  report label (default: "unspecified")

Screening ("screening is declarative, never a crash": ``Engine.screen`` in
``engines/base.py``) checks only what is true regardless of which binary is
configured: FIDE team pairing (C.04.6) is out of scope for this sweep no
matter which second engine is being compared against (this repo's own scope
note, not a fact about any particular binary). Everything else that a
particular binary cannot handle -- an unsupported tournament type, a record
it rejects, anything -- surfaces honestly at pair()-time as an ERROR carrying
that binary's own message, rather than being guessed at in advance."""
import os
import re
import subprocess
import sys
import tempfile

INTEROP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if INTEROP_DIR not in sys.path:
    sys.path.insert(0, INTEROP_DIR)

from normalize import normalize_pairing  # noqa: E402
from engines.base import Outcome  # noqa: E402

_TMPDIR = tempfile.gettempdir()

BINARY_PATH = os.environ.get(
    "TIEBREAK_INTEROP_ENGINE_BINARY",
    os.path.join(INTEROP_DIR, "bin", "engine.exe"),
)
ENGINE_NAME = os.environ.get("TIEBREAK_INTEROP_ENGINE_NAME", "external")
ENGINE_VERSION = os.environ.get("TIEBREAK_INTEROP_ENGINE_VERSION", "unspecified")

TIMEOUT_SECONDS = 10

_PAIR_LINE = re.compile(r"^\s*(\d+)\s+(\d+)\s*$")


def _blank_250_match_points(trf_text):
    """Record 250's match-points column [4:8] is never meaningful for an
    individual tournament (team tournaments are screened out below, so this
    only ever runs on individual ones) -- match points are a team-only
    concept. Some readers are strict about a nonblank-but-irrelevant value
    there, so it is always blanked before comparison, regardless of which
    binary is configured. This changes nothing about what either engine
    computes: it only affects a column with no individual-tournament
    meaning, on the copy of the TRF handed to the external binary."""
    out = []
    changed = False
    for line in trf_text.split("\n"):
        if line[:3] == "250" and len(line) >= 8 and line[4:8].strip():
            line = line[:4] + "    " + line[8:]
            changed = True
        out.append(line)
    return ("\n".join(out), changed)


def _scratch(suffix):
    # One scratch path per process, so xdist workers cannot clobber each
    # other's input or output file -- the tests/corpus/_harness.py pattern.
    return os.path.join(_TMPDIR, "tiebreak_interop_ext_%d.%s" % (os.getpid(), suffix))


def _line_prefixes(trf_text):
    prefixes = set()
    for line in trf_text.replace("\r\n", "\n").split("\n"):
        if len(line) >= 3:
            prefixes.add(line[:3])
    return prefixes


def _parse_pairing_file(path):
    with open(path, "r", encoding="latin1") as handle:
        lines = [line.strip() for line in handle if line.strip() != ""]
    if not lines:
        return []
    # First line is the board count; trust the WHITE/BLACK lines that follow
    # rather than the count itself.
    raw_pairs = []
    for line in lines[1:]:
        match = _PAIR_LINE.match(line)
        if not match:
            raise ValueError("unparseable pairing line: %r" % (line,))
        raw_pairs.append((int(match.group(1)), int(match.group(2))))
    return raw_pairs


class ExternalEngine:
    """Adapter over an external JaVaFo-protocol pairing binary, supplied
    entirely by configuration (see module docstring) -- nothing here assumes
    a specific one. Only the ``default`` variant exists here: a matching-mode
    switch like this repository's own ``-x weighted`` is a property of a
    *particular* external engine, not of this adapter, so a future one that
    has its own would register its own variant the same way
    tiebreakserver.py's ``VARIANTS`` does, implementing the same ``Engine``
    protocol from ``engines/base.py``."""

    def __init__(self, binary_path=None, name=None, version=None):
        self.binary_path = binary_path or BINARY_PATH
        self.name = name or ENGINE_NAME
        self.version = version or ENGINE_VERSION

    def screen(self, case):
        trf = case if isinstance(case, str) else case.get("trf")
        if not os.path.exists(self.binary_path):
            return "%s binary not present at %s" % (self.name, self.binary_path)

        # Team tournaments: record 013 or 310. Engine-independent: FIDE team
        # pairing (C.04.6) is out of scope for this sweep no matter which
        # second engine is being compared against (this repo's own scope
        # note). Everything else a particular binary can't handle surfaces
        # at pair()-time as an ERROR in that binary's own words, rather than
        # being guessed at here.
        prefixes = _line_prefixes(trf)
        if "013" in prefixes or "310" in prefixes:
            return "team tournament (record 013/310): out of scope for this sweep"

        return None

    def pair(self, trf, round_no):
        """Returns ``(outcome, raw)`` -- see ``Engine.pair`` in
        ``engines/base.py`` for the shape of ``raw``."""
        trf, _ = _blank_250_match_points(trf)
        input_path = _scratch("trf")
        output_path = _scratch("out")
        with open(input_path, "w", encoding="latin1") as handle:
            handle.write(trf)
        if os.path.exists(output_path):
            os.remove(output_path)

        try:
            result = subprocess.run(
                [self.binary_path, "--dutch", input_path, "-p", output_path],
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return Outcome.error(code="timeout", message="%s exceeded %ds" % (self.name, TIMEOUT_SECONDS)), None
        except OSError as exc:
            return Outcome.error(code="spawn-failed", message=str(exc)), None

        if result.returncode == 0:
            try:
                raw_pairs = _parse_pairing_file(output_path)
            except (OSError, ValueError) as exc:
                return Outcome.error(code=0, message="could not parse pairing file: %s" % exc), None
            return normalize_pairing(raw_pairs), raw_pairs

        if result.returncode == 1:
            return Outcome.no_legal_pairing(), None

        message = result.stderr.decode("latin1", "replace").strip() or result.stdout.decode("latin1", "replace").strip()
        return Outcome.error(code=result.returncode, message=message), None
