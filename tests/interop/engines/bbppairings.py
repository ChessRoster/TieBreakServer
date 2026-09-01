# -*- coding: utf-8 -*-
"""Subprocess adapter over an external pairing-engine binary that speaks the
same command-line protocol as bbpPairings -- the independent oracle the
interop sweep points at this repository's engine. See PLAN-REGRESSION.md
sections 2, 6.2 and 6.4.

Command form: ``BINARY --dutch INPUT -p OUTPUT``. Exit 0 -> parse OUTPUT as
the JaVaFo-style pairing file (a count line, then one ``WHITE BLACK`` line
per board, ``0`` marking the pairing-allocated bye's opponent). Exit 1 ->
NO_LEGAL_PAIRING (a first-class outcome, not a failure -- see
PLAN-REGRESSION.md section 4). Anything else, or a timeout, -> ERROR. This is
the "JaVaFo-style" pairing CLI/output convention PLAN-REGRESSION.md section
2.3 describes -- bbpPairings v6.0.0 is the pinned default, but any binary
speaking the same protocol (a real prospect for JaVaFo-family engines) can be
substituted by pointing the three env vars below at it, e.g. from the
interop-sweep GitHub Action's workflow_dispatch URL input, without touching
this module.

Which binary, and what to call it, is configurable via environment variables
so the same code path runs both the locally pinned build and an arbitrary one
fetched at CI dispatch time:

    TIEBREAK_INTEROP_ENGINE_BINARY   path to the binary (default: the pinned
                                      bbpPairings.exe under tests/interop/bin/)
    TIEBREAK_INTEROP_ENGINE_NAME     report label (default: "bbppairings")
    TIEBREAK_INTEROP_ENGINE_VERSION  report label (default: "6.0.0")

The section-2.2 static screening rules (the accepted record-192 values, the
record-299 rejection, the record-250 compatibility blanking) are specific,
verified facts about the *pinned* bbpPairings v6.0.0 build -- they do not
necessarily hold for an arbitrary substituted binary. This module therefore
only applies them when the binary at TIEBREAK_INTEROP_ENGINE_BINARY hashes to
the known pinned build; for any other binary, screen() checks only the
engine-independent team-tournament exclusion (this repo's own scope limit,
per PLAN-REGRESSION.md's "FIDE team pairing is out of scope", true regardless
of which second engine is being compared against) and lets every other
rejection surface at runtime as an ERROR carrying the binary's own message,
per PLAN-REGRESSION.md section 6.4's "screening is declarative, never a
crash" -- for an unknown binary, attempt-and-observe is the more honest
default than guessing its feature set.
"""
import functools
import hashlib
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
    os.path.join(INTEROP_DIR, "bin", "bbpPairings.exe"),
)
ENGINE_NAME = os.environ.get("TIEBREAK_INTEROP_ENGINE_NAME", "bbppairings")
ENGINE_VERSION = os.environ.get("TIEBREAK_INTEROP_ENGINE_VERSION", "6.0.0")

# PLAN-REGRESSION.md section 2.1's pinned bbpPairings v6.0.0 binary hash. Used
# only to decide whether the section-2.2 static screening rules below apply --
# see the module docstring.
PINNED_BBP_SHA256 = "81904eae52e5345e96344e4fd2ffd4f317497edf568dadff69b50e5844ad7c51"

# Records this version of bbpPairings rejects outright, and the accepted set
# for record 192, from src/fileformats/trf.cpp at tag v6.0.0 -- see
# PLAN-REGRESSION.md section 2.2. FIDE_DUTCH_2026 / FIDE_DUTCH_2026_BAKU were
# added to the format *after* this release and are deliberately not in this
# set: a corpus that switches to writing them would be a coverage collapse
# this screen() should surface, not silently absorb. Applied only when the
# configured binary is the pinned build -- see the module docstring.
ACCEPTED_192 = frozenset({
    "FIDE_DUTCH",
    "FIDE_DUTCH_2025",
    "FIDE_DUTCH_BAKU",
    "FIDE_DUTCH_2025_BAKU",
    "FIDE_BURSTEIN",
    "FIDE_BURSTEIN_BAKU",
})

TIMEOUT_SECONDS = 10


@functools.lru_cache(maxsize=None)
def _is_pinned_bbp_binary(binary_path):
    """Whether ``binary_path`` hashes to the pinned bbpPairings v6.0.0 build
    -- gates the section-2.2 static screening rules (see module docstring).
    Cached: the sweep calls this once per (fixture, round), and the binary
    does not change mid-run."""
    try:
        with open(binary_path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return False
    return digest == PINNED_BBP_SHA256

_PAIR_LINE = re.compile(r"^\s*(\d+)\s+(\d+)\s*$")


def _blank_250_match_points(trf_text):
    """Work around a corpus-generation bug: this repository's TRF writer
    (trf2json.py's output_trf_accelerated, fixed in this same change set)
    used to write a nonzero value into record 250's match-points column
    [4:8], which bbpPairings' reader rejects unconditionally ("match points
    must be empty") regardless of whether a match-point scoring system is
    declared -- see PLAN-REGRESSION.md section 2.2 and the trf2json.py fix.

    The fix in trf2json.py only changes what *future* TRF generation writes;
    it cannot retroactively rewrite the ~1,586 Baku-accelerated fixtures
    already serialized into tests/corpus/corpus.jsonl.gz. Blanking the field
    here, right before handing the TRF to bbpPairings, is safe because that
    column carries no pairing-relevant information for a tournament with no
    declared match-point system (which is every fixture in this corpus, see
    PLAN-REGRESSION.md section 2.4 -- none carry record 162): it only
    participates in bbpPairings' own score-reconciliation check, never in
    pairing logic itself. This is a comparison-input compatibility fix, not a
    change to what either engine computes."""
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
    return os.path.join(_TMPDIR, "tiebreak_interop_bbp_%d.%s" % (os.getpid(), suffix))


def _line_prefixes_and_192(trf_text):
    prefixes = set()
    value192 = None
    for line in trf_text.replace("\r\n", "\n").split("\n"):
        if len(line) < 3:
            continue
        prefix = line[:3]
        prefixes.add(prefix)
        if prefix == "192":
            value192 = line[4:].strip().upper()
    return prefixes, value192


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


class BbpPairingsEngine:
    """Adapter over an external JaVaFo-protocol pairing binary -- the pinned
    bbpPairings v6.0.0 build by default, or any other binary pointed at by
    the TIEBREAK_INTEROP_ENGINE_* env vars (see module docstring). Only the
    ``default`` variant exists -- bbpPairings always pairs by weighted
    matching, so there is no ``-x weighted`` equivalent on this side of the
    comparison (see PLAN-REGRESSION.md section 6.3, which registers
    ``weighted`` as a variant of tiebreakserver instead)."""

    def __init__(self, binary_path=None, name=None, version=None):
        self.binary_path = binary_path or BINARY_PATH
        self.name = name or ENGINE_NAME
        self.version = version or ENGINE_VERSION

    def screen(self, case):
        trf = case if isinstance(case, str) else case.get("trf")
        if not os.path.exists(self.binary_path):
            return "%s binary not present at %s" % (self.name, self.binary_path)

        prefixes, value192 = _line_prefixes_and_192(trf)

        # Team tournaments: record 013 or 310. Engine-independent: FIDE team
        # pairing (C.04.6) is out of scope for this sweep no matter which
        # second engine is being compared against (PLAN-REGRESSION.md's
        # opening scope note) -- this check always applies, unlike the
        # pinned-build-specific ones below. In the present corpus every team
        # fixture also carries a 192 value outside ACCEPTED_192 (see the
        # check below, which independently catches all of them when running
        # the pinned binary), but a future team fixture with no 192 line at
        # all is not hypothetical -- 88 of this corpus's own 1,000 team
        # fixtures carry record 310 with no 192 line -- so this check stays,
        # on its own terms.
        if "013" in prefixes or "310" in prefixes:
            return "team tournament (record 013/310): out of scope for this sweep"

        if not _is_pinned_bbp_binary(self.binary_path):
            # An unrecognised binary: no static assumptions about its
            # feature set. Anything it can't handle surfaces as an ERROR at
            # pair()-time, with its own message, rather than a guessed skip.
            return None

        if "299" in prefixes:
            return "record 299 (abnormal assignment points): not supported by bbpPairings v6.0.0"

        if value192 is not None and value192 not in ACCEPTED_192:
            # Empirically this is also what a team fixture's own 192 value
            # (e.g. FIDE_TEAM_TYPEB_GP) trips, with bbpPairings itself
            # reporting "unsupported tournament type" rather than the "team
            # tournaments are not supported" message associated with records
            # 013/310 -- so this branch is deliberately not team-specific.
            return "unsupported tournament type (record 192 %s)" % value192

        return None

    def pair(self, trf, round_no):
        if _is_pinned_bbp_binary(self.binary_path):
            # See _blank_250_match_points' docstring: a compatibility fix for
            # this repo's own corpus data, specific to the pinned build's
            # exact rejection behaviour, not something to assume of an
            # arbitrary substituted binary.
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
            return Outcome.error(code="timeout", message="bbpPairings exceeded %ds" % TIMEOUT_SECONDS)
        except OSError as exc:
            return Outcome.error(code="spawn-failed", message=str(exc))

        if result.returncode == 0:
            try:
                raw_pairs = _parse_pairing_file(output_path)
            except (OSError, ValueError) as exc:
                return Outcome.error(code=0, message="could not parse pairing file: %s" % exc)
            return normalize_pairing(raw_pairs)

        if result.returncode == 1:
            return Outcome.no_legal_pairing()

        message = result.stderr.decode("latin1", "replace").strip() or result.stdout.decode("latin1", "replace").strip()
        return Outcome.error(code=result.returncode, message=message)
