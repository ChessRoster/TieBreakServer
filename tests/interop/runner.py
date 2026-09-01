# -*- coding: utf-8 -*-
"""The corpus sweep: PLAN-REGRESSION.md sections 6 and 9.

For every eligible individual fixture and every round ``k = 1..numRounds``,
truncates once (``trftrunc.truncate(trf, k-1)``) and pairs that truncated TRF
through three engine variants -- ``(tiebreakserver, default)``,
``(tiebreakserver, weighted)``, ``(bbppairings, default)`` -- then classifies
each tiebreakserver variant against bbppairings with ``normalize.classify``.
Writes one JSON record per ``(fixture, round, tiebreakserver_variant)`` to
``results.jsonl`` (or a shard of it).

Note on ``normalize_pairing`` and raw board order: ``Engine.pair()`` returns a
canonical ``Outcome`` whose ``pairs`` is an order-independent frozenset -- by
design, so the PAIRED/COLOUR/PAIRING classification never depends on board
order (PLAN-REGRESSION.md section 4). The board-order-only secondary signal
needs the *raw*, board-ordered pairing list each engine actually produced,
which the canonical form has already discarded. Rather than call each engine
twice per (fixture, round) -- once through ``.pair()`` for the Outcome, once
more duplicating that work for the raw list, doubling the dominant cost of the
whole sweep (bbpPairings subprocess spawns) -- the two ``_tbs_pair`` /
``_bbp_pair`` helpers below run each engine exactly once and return both the
canonical Outcome and the pre-normalisation raw list together. They are
necessarily near-duplicates of ``engines/tiebreakserver.py`` and
``engines/bbppairings.py``'s own ``pair()`` methods, built only out of names
those modules already export (nothing in those files is modified) -- to keep
one engine invocation per comparison rather than two.
"""
import argparse
import contextlib
import gzip
import hashlib
import io
import json
import os
import platform as platform_module
import subprocess
import sys
import time

PLATFORM = platform_module.system().lower() or "unknown"

INTEROP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(INTEROP_DIR))
TESTS_DIR = os.path.dirname(INTEROP_DIR)
for path in (REPO_ROOT, TESTS_DIR, INTEROP_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import pairingchecker  # noqa: E402
import version as version_module  # noqa: E402

import trftrunc  # noqa: E402
from engines.base import Outcome  # noqa: E402
from engines.tiebreakserver import (  # noqa: E402
    NO_LEGAL_PAIRING_CODE,
    VARIANTS as TBS_VARIANTS,
    _scratch as _tbs_scratch,
)
from engines.bbppairings import (  # noqa: E402
    BINARY_PATH,
    ENGINE_NAME,
    ENGINE_VERSION,
    PINNED_BBP_SHA256,
    TIMEOUT_SECONDS,
    BbpPairingsEngine,
    _blank_250_match_points,
    _is_pinned_bbp_binary,
    _parse_pairing_file,
    _scratch as _bbp_scratch,
)
from normalize import classify, is_board_order_only_difference, normalize_pairing  # noqa: E402
from validate_truncation import _num_rounds  # noqa: E402

CORPUS_GZ = os.path.join(TESTS_DIR, "corpus", "corpus.jsonl.gz")
RESULTS_PATH = os.path.join(INTEROP_DIR, "results.jsonl")

DEFAULT_SAMPLE = 300


# -- engine invocation, each done once per (fixture, round, variant) ---------


def _tbs_pair(trf, round_no, variant):
    """Mirrors engines/tiebreakserver.py's TieBreakServerEngine.pair(), but
    also returns the raw board-ordered pairs list before normalize_pairing()
    discards order. See this module's docstring for why this is a near-copy
    rather than a call to the adapter."""
    input_path = _tbs_scratch("trf")
    output_path = _tbs_scratch("out")
    with open(input_path, "w", encoding="latin1") as handle:
        handle.write(trf)

    obj = pairingchecker.pairingchecker()
    argv = ["checker", "-i", input_path, "-o", output_path, "-p", "-n", str(round_no)]
    if TBS_VARIANTS[variant]:
        argv += ["-x"] + TBS_VARIANTS[variant]

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
        return Outcome.error(code=code, message=status.get("error")), None

    pairing_result = obj.resultjson.get("pairingResult") or {}
    raw_pairs = pairing_result.get("pairs")
    if not raw_pairs:
        return Outcome.error(code=code, message="empty pairing result"), None

    raw = [(int(w), int(b)) for w, b in raw_pairs]
    return normalize_pairing(raw), raw


def _bbp_pair(trf, round_no):
    """Mirrors engines/bbppairings.py's BbpPairingsEngine.pair(); see this
    module's docstring."""
    if _is_pinned_bbp_binary(BINARY_PATH):
        trf, _ = _blank_250_match_points(trf)
    input_path = _bbp_scratch("trf")
    output_path = _bbp_scratch("out")
    with open(input_path, "w", encoding="latin1") as handle:
        handle.write(trf)
    if os.path.exists(output_path):
        os.remove(output_path)

    try:
        result = subprocess.run(
            [BINARY_PATH, "--dutch", input_path, "-p", output_path],
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return Outcome.error(code="timeout", message="bbpPairings exceeded %ds" % TIMEOUT_SECONDS), None
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


# -- corpus loading -----------------------------------------------------------


def load_individual_fixtures():
    records = []
    with gzip.open(CORPUS_GZ, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("category") == "individual":
                records.append(record)
    return records


def want_full():
    return os.environ.get("TIEBREAK_INTEROP_FULL", "") not in ("", "0", "false", "no", "off")


def select_fixtures(records, full, sample_size, shard, shards):
    if shards > 1:
        records = [r for i, r in enumerate(records) if i % shards == shard]
    if not full:
        stride = max(1, len(records) // sample_size)
        records = records[::stride]
    return records


# -- serialization --------------------------------------------------------


def _outcome_to_dict(outcome):
    return {
        "tag": outcome.tag,
        "pairs": sorted([list(pair) for pair in outcome.pairs]) if outcome.pairs is not None else None,
        "pab": outcome.pab,
        "code": outcome.code,
        "message": outcome.message,
    }


def _bbp_binary_sha256():
    if not os.path.exists(BINARY_PATH):
        return None
    digest = hashlib.sha256()
    with open(BINARY_PATH, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# -- the sweep ------------------------------------------------------------


def run(records, out_handle, progress_every=25):
    bbp_screen_engine = BbpPairingsEngine()
    tbs_version = version_module.version()["version"]
    bbp_binary_sha256 = _bbp_binary_sha256()
    is_pinned = _is_pinned_bbp_binary(BINARY_PATH)
    if not is_pinned:
        print(
            "NOTE: %s binary (sha256 %s) is not the pinned bbpPairings v6.0.0 build "
            "(%s) -- running as an unrecognised second engine: only the "
            "team-tournament screen applies, and the section-2.2 static rules "
            "(record 299, record 192 allow-list, record 250 blanking) are skipped "
            "in favour of observing this binary's own runtime behaviour."
            % (ENGINE_NAME, bbp_binary_sha256, PINNED_BBP_SHA256),
            file=sys.stderr,
        )

    meta = {
        "kind": "meta",
        "tiebreakserver_version": tbs_version,
        "bbppairings_name": ENGINE_NAME,
        "bbppairings_version": ENGINE_VERSION,
        "bbppairings_sha256": bbp_binary_sha256,
        "bbppairings_sha256_pinned": PINNED_BBP_SHA256,
        "bbppairings_is_pinned_build": is_pinned,
    }
    out_handle.write(json.dumps(meta) + "\n")

    skip_counts = {}
    comparisons = 0
    t0 = time.time()
    total = len(records)

    for i, fixture in enumerate(records, start=1):
        name = fixture["name"]
        trf = fixture["trf"]

        skip_reason = bbp_screen_engine.screen(trf)
        if skip_reason:
            skip_counts[skip_reason] = skip_counts.get(skip_reason, 0) + 1
            out_handle.write(json.dumps({"kind": "skip", "fixture": name, "reason": skip_reason}) + "\n")
            continue

        num_rounds = _num_rounds(trf)
        num_players = sum(1 for line in trf.split("\n") if line[:3] == "001")
        if not num_rounds:
            skip_counts["no record 142 (round count)"] = skip_counts.get("no record 142 (round count)", 0) + 1
            out_handle.write(
                json.dumps({"kind": "skip", "fixture": name, "reason": "no record 142 (round count)"}) + "\n"
            )
            continue

        for k in range(1, num_rounds + 1):
            truncated = trftrunc.truncate(trf, k - 1)

            tbs_default_outcome, tbs_default_raw = _tbs_pair(truncated, k, "default")
            tbs_weighted_outcome, tbs_weighted_raw = _tbs_pair(truncated, k, "weighted")
            bbp_outcome, bbp_raw = _bbp_pair(truncated, k)

            for variant_name, tbs_outcome, tbs_raw in (
                ("default", tbs_default_outcome, tbs_default_raw),
                ("weighted", tbs_weighted_outcome, tbs_weighted_raw),
            ):
                cls = classify(tbs_outcome, bbp_outcome)
                board_order_only = None
                if tbs_outcome.is_paired and bbp_outcome.is_paired and tbs_raw is not None and bbp_raw is not None:
                    board_order_only = is_board_order_only_difference(tbs_raw, bbp_raw)

                record = {
                    "kind": "comparison",
                    "fixture": name,
                    "round": k,
                    "num_rounds": num_rounds,
                    "num_players": num_players,
                    # Distinguishes rows when a single merged results.jsonl
                    # combines shards from more than one OS (the
                    # interop-sweep GitHub Action's optional Windows run) --
                    # merge() keeps only the first shard's "meta" record, so
                    # this is per-row rather than relying on meta alone.
                    "platform": PLATFORM,
                    "tiebreakserver_variant": variant_name,
                    "tiebreakserver": _outcome_to_dict(tbs_outcome),
                    "bbppairings": _outcome_to_dict(bbp_outcome),
                    "class": cls,
                    "board_order_only_difference": board_order_only,
                }
                out_handle.write(json.dumps(record) + "\n")
                comparisons += 1

        if i % progress_every == 0 or i == total:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0.0
            eta = (total - i) / rate if rate > 0 else float("nan")
            print(
                "runner: %d/%d fixtures, %d comparisons, %.1fs elapsed, %.2f fixtures/s, ETA %.0fs"
                % (i, total, comparisons, elapsed, rate, eta),
                file=sys.stderr,
            )

    elapsed = time.time() - t0
    print("", file=sys.stderr)
    print(
        "runner: done. %d fixtures processed, %d skipped, %d comparisons written in %.1fs"
        % (total - sum(skip_counts.values()), sum(skip_counts.values()), comparisons, elapsed),
        file=sys.stderr,
    )
    for reason, count in sorted(skip_counts.items(), key=lambda kv: -kv[1]):
        print("  skipped %d: %s" % (count, reason), file=sys.stderr)

    return {"comparisons": comparisons, "skip_counts": skip_counts, "elapsed": elapsed}


def merge(paths, out_path):
    seen_meta = False
    with open(out_path, "w", encoding="utf-8") as out_handle:
        for path in paths:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    if '"kind": "meta"' in line or '"kind":"meta"' in line:
                        if seen_meta:
                            continue
                        seen_meta = True
                    out_handle.write(line if line.endswith("\n") else line + "\n")
    print("merged %d shard file(s) into %s" % (len(paths), out_path), file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="run every eligible individual fixture (else a deterministic sample; env TIEBREAK_INTEROP_FULL=1 has the same effect)")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE, help="sample size when not --full (default %d)" % DEFAULT_SAMPLE)
    parser.add_argument("--shard", type=int, default=0, help="this shard's 0-based index")
    parser.add_argument("--shards", type=int, default=1, help="total number of shards")
    parser.add_argument("--out", default=None, help="output path (default results.jsonl, or results.shard{N}.jsonl when --shards > 1)")
    parser.add_argument("--merge", nargs="+", default=None, metavar="SHARD_FILE", help="concatenate shard result files into --out (default results.jsonl) and exit")
    args = parser.parse_args(argv)

    if args.merge:
        merge(args.merge, args.out or RESULTS_PATH)
        return 0

    full = args.full or want_full()
    out_path = args.out
    if out_path is None:
        out_path = RESULTS_PATH if args.shards <= 1 else os.path.join(INTEROP_DIR, "results.shard%d.jsonl" % args.shard)

    records = load_individual_fixtures()
    selected = select_fixtures(records, full, args.sample, args.shard, args.shards)

    print(
        "runner: %d individual fixtures selected (%s%s) -> %s"
        % (
            len(selected),
            "full" if full else "sample=%d" % args.sample,
            ", shard %d/%d" % (args.shard, args.shards) if args.shards > 1 else "",
            out_path,
        ),
        file=sys.stderr,
    )

    with open(out_path, "w", encoding="utf-8") as out_handle:
        run(selected, out_handle)

    return 0


if __name__ == "__main__":
    sys.exit(main())
