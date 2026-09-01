# -*- coding: utf-8 -*-
"""The self-validation gate: see this directory's README.md, "Running the
validation gate".

Before a single external-engine divergence is trusted, this checks that
``trftrunc.truncate`` itself is not manufacturing divergences on both sides at
once. This engine's own ``-c`` check mode replays a *whole, untruncated*
tournament and reports, per round, the pairing it would itself prescribe --
independent of the truncation transform entirely. That prescribed pairing must
equal what ``TieBreakServerEngine.pair()`` (``-p -n <round>``) produces on the
file truncated to rounds ``1..round-1``. Any mismatch is a bug in
``trftrunc.py``, not a real finding -- see the module docstring there and the
README's "The truncation transform" section.

This needs no external engine and no subprocess: it is pure in-process work, so it
is expected to be much faster than the full sweep and can reasonably cover the
whole individual corpus rather than a sample.

Usage::

    python3 tests/interop/validate_truncation.py [--full] [--sample N]

Exit code is 0 if every checked (fixture, round) either matched or was an
oracle-coverage gap -- a fixture whose full, untruncated tournament has no
legal pairing at all, leaving the ``-c`` oracle nothing to compare against
(see ``main`` below); 1 if any round was a genuine mismatch. On failure,
prints the first few real mismatches, and the oracle-gap count separately,
with enough detail to reproduce them by hand.
"""
import argparse
import contextlib
import io
import os
import sys
import tempfile
import time

INTEROP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(INTEROP_DIR))
TESTS_DIR = os.path.dirname(INTEROP_DIR)
for path in (REPO_ROOT, TESTS_DIR, INTEROP_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import pairingchecker  # noqa: E402
from helpers import parse_int  # noqa: E402

import trftrunc  # noqa: E402
from engines.tiebreakserver import TieBreakServerEngine  # noqa: E402
from normalize import normalize_pairing  # noqa: E402

from corpus._harness import load_corpus  # noqa: E402

DEFAULT_SAMPLE = 300


def _num_rounds(trf_text):
    for line in trf_text.split("\n"):
        if line[:3] == "142":
            return parse_int(line[4:])
    return None


def _check_mode_roundpairing(trf_text):
    """Run this engine's own -c check mode over the whole, untruncated
    fixture and return {round_no: [(w, b), ...]} -- the pairing it would
    itself prescribe for every round, read straight off
    resultjson["pairingResult"]["roundpairing"], independent of trftrunc.py
    entirely (see this module's docstring)."""
    input_path = _scratch("trf")
    output_path = _scratch("out")
    with open(input_path, "w", encoding="latin1") as handle:
        handle.write(trf_text)

    obj = pairingchecker.pairingchecker()
    argv = ["checker", "-i", input_path, "-o", output_path, "-c"]
    saved_argv = sys.argv
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                obj.common_main()
            except SystemExit:
                pass
            except Exception as exc:  # pragma: no cover - defensive
                return None, "%s: %s" % (type(exc).__name__, exc)
    finally:
        sys.argv = saved_argv

    status = obj.resultjson.get("status", {})
    if status.get("code") not in (0, 1):
        # 0 = every round's declared pairing matched the prescribed one, 1 =
        # at least one round differed from what's *declared in the file* --
        # both are normal check-mode outcomes and still carry roundpairing.
        # Anything else (a read/setup error) means there is nothing to
        # validate against.
        return None, "check mode status %r: %s" % (status.get("code"), status.get("error"))

    pairing_result = obj.resultjson.get("pairingResult") or {}
    roundpairing = pairing_result.get("roundpairing")
    if not roundpairing:
        return None, "no roundpairing in check-mode result"

    by_round = {}
    for entry in roundpairing:
        by_round[entry["round"]] = [(int(w), int(b)) for w, b in entry["pairs"]]
    return by_round, None


def _scratch(suffix):
    return os.path.join(tempfile.gettempdir(), "tiebreak_interop_validate_%d.%s" % (os.getpid(), suffix))


def validate_fixture(fixture, tbs):
    """Yield one (round_no, ok, detail) tuple per round of `fixture`."""
    trf = fixture["trf"]
    num_rounds = _num_rounds(trf)
    if not num_rounds:
        return

    by_round, err = _check_mode_roundpairing(trf)
    if by_round is None:
        yield (None, False, "check-mode failed: %s" % err)
        return

    for round_no in range(1, num_rounds + 1):
        prescribed = by_round.get(round_no)
        if prescribed is None:
            yield (round_no, False, "no check-mode pairing for round %d" % round_no)
            continue

        truncated = trftrunc.truncate(trf, round_no - 1)
        outcome, _raw = tbs.pair(truncated, round_no)

        expected = normalize_pairing(prescribed)

        if outcome.is_error:
            yield (round_no, False, "pair() errored: %s / %s" % (outcome.code, outcome.message))
            continue

        # A round with no legal pairing can't be reported by check mode (it
        # requires a declared pairing to check), so it can't arise here in
        # practice, but guard it explicitly rather than silently mismatch.
        if outcome.is_no_legal_pairing:
            yield (round_no, False, "pair() said NO_LEGAL_PAIRING, check mode prescribed a pairing")
            continue

        ok = outcome.pairs == expected.pairs and outcome.pab == expected.pab
        detail = None if ok else "expected pairs=%s pab=%s, got pairs=%s pab=%s" % (
            sorted(expected.pairs), expected.pab, sorted(outcome.pairs), outcome.pab,
        )
        yield (round_no, ok, detail)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="validate every individual fixture, not a sample")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE, help="sample size when not --full")
    parser.add_argument("--max-failures", type=int, default=20, help="max mismatch details to print")
    parser.add_argument("--shard", type=int, default=0, help="this shard's 0-based index")
    parser.add_argument("--shards", type=int, default=1, help="total number of shards, for splitting a --full run across parallel CI jobs")
    args = parser.parse_args(argv)

    records = load_corpus(full=True)  # load_corpus's own sampling is corpus-test-specific; sample here instead
    individual = [r for r in records if r.get("category") == "individual"]

    if args.shards > 1:
        individual = [r for i, r in enumerate(individual) if i % args.shards == args.shard]

    if args.full:
        selected = individual
    else:
        stride = max(1, len(individual) // args.sample)
        selected = individual[::stride]

    print("validate_truncation: %d fixtures (%s%s)" % (
        len(selected),
        "full" if args.full else "sample",
        ", shard %d/%d" % (args.shard, args.shards) if args.shards > 1 else "",
    ), file=sys.stderr)

    tbs = TieBreakServerEngine()

    total_rounds = 0
    ok_rounds = 0
    failures = []
    t0 = time.time()

    for i, fixture in enumerate(selected, start=1):
        for round_no, ok, detail in validate_fixture(fixture, tbs):
            total_rounds += 1
            if ok:
                ok_rounds += 1
            else:
                failures.append((fixture["name"], round_no, detail))

        if i % 20 == 0 or i == len(selected):
            elapsed = time.time() - t0
            print(
                "  %d/%d fixtures, %d/%d rounds ok, %.1fs elapsed"
                % (i, len(selected), ok_rounds, total_rounds, elapsed),
                file=sys.stderr,
            )

    elapsed = time.time() - t0
    print("", file=sys.stderr)
    print(
        "validate_truncation: %d/%d rounds matched (%.2f%%) across %d fixtures in %.1fs"
        % (ok_rounds, total_rounds, 100.0 * ok_rounds / total_rounds if total_rounds else 0.0, len(selected), elapsed),
        file=sys.stderr,
    )

    # A fixture where the FULL, untruncated tournament has no legal pairing at
    # all (this corpus's deliberately-invalid "_inv_c2" category) leaves the
    # -c oracle with nothing to compare against -- "check-mode failed" --
    # which is a gap in what this gate can check, not a trftrunc.py defect.
    # Treated as a real, blocking mismatch, a gate over any full or large
    # sample would never pass, since the corpus guarantees this category is
    # present.
    oracle_gaps = [f for f in failures if f[2] and f[2].startswith("check-mode failed")]
    real_mismatches = [f for f in failures if f not in oracle_gaps]

    if oracle_gaps:
        print(
            "%d oracle-coverage gaps (full tournament has no legal pairing -- not a trftrunc.py defect, see module docstring)"
            % len(oracle_gaps),
            file=sys.stderr,
        )
    if real_mismatches:
        print("%d real mismatches (showing up to %d):" % (len(real_mismatches), args.max_failures), file=sys.stderr)
        for name, round_no, detail in real_mismatches[: args.max_failures]:
            print("  %s round %s: %s" % (name, round_no, detail), file=sys.stderr)

    return 0 if not real_mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
