# -*- coding: utf-8 -*-
"""The corpus sweep. See this directory's README.md for the design and
"Outcome model" for the classification below.

For every eligible individual fixture and every round ``k = 1..numRounds``,
truncates once (``trftrunc.truncate(trf, k-1)``) and pairs that truncated TRF
through three engine variants -- ``(tiebreakserver, default)``,
``(tiebreakserver, weighted)``, ``(external, default)`` -- then classifies
each tiebreakserver variant against the external engine with
``normalize.classify``. Writes one JSON record per ``(fixture, round,
tiebreakserver_variant)`` to ``results.jsonl`` (or a shard of it). "external"
is deliberately generic: which binary answers for it is supplied entirely at
run time (see ``engines/external_engine.py``), not named here.

Note on ``normalize_pairing`` and raw board order: each adapter's ``pair()``
returns ``(outcome, raw)`` -- ``outcome`` a canonical ``Outcome`` whose
``pairs`` is an order-independent frozenset, by design, so the
PAIRED/COLOUR/PAIRING classification never depends on board order, and
``raw`` the engine's own pre-normalisation, board-ordered pairing list. The
board-order-only secondary signal (``normalize.is_board_order_only_difference``)
needs that raw list, which the canonical form has already discarded; both
adapters hand it back from the one engine invocation each comparison makes,
so nothing here has to invoke an engine a second time or duplicate either
adapter's own ``pair()`` to get at it.
"""
import argparse
import gzip
import hashlib
import json
import os
import platform as platform_module
import sys
import time

PLATFORM = platform_module.system().lower() or "unknown"

INTEROP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(INTEROP_DIR))
TESTS_DIR = os.path.dirname(INTEROP_DIR)
for path in (REPO_ROOT, TESTS_DIR, INTEROP_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import version as version_module  # noqa: E402

import trftrunc  # noqa: E402
from engines.tiebreakserver import TieBreakServerEngine, VARIANTS as TBS_VARIANTS  # noqa: E402
from engines.external_engine import (  # noqa: E402
    BINARY_PATH,
    ENGINE_NAME,
    ENGINE_VERSION,
    ExternalEngine,
)
from normalize import classify, is_board_order_only_difference  # noqa: E402
from validate_truncation import _num_rounds  # noqa: E402

CORPUS_GZ = os.path.join(TESTS_DIR, "corpus", "corpus.jsonl.gz")
RESULTS_PATH = os.path.join(INTEROP_DIR, "results.jsonl")

DEFAULT_SAMPLE = 300


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


def _external_binary_sha256():
    if not os.path.exists(BINARY_PATH):
        return None
    digest = hashlib.sha256()
    with open(BINARY_PATH, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# -- the sweep ------------------------------------------------------------


def run(records, out_handle, progress_every=25):
    external_engine = ExternalEngine()
    tbs_engines = {variant: TieBreakServerEngine(variant) for variant in TBS_VARIANTS}
    tbs_version = version_module.version()["version"]
    external_binary_sha256 = _external_binary_sha256()

    meta = {
        "kind": "meta",
        "tiebreakserver_version": tbs_version,
        "external_engine_name": ENGINE_NAME,
        "external_engine_version": ENGINE_VERSION,
        "external_engine_sha256": external_binary_sha256,
    }
    out_handle.write(json.dumps(meta) + "\n")

    skip_counts = {}
    comparisons = 0
    t0 = time.time()
    total = len(records)

    for i, fixture in enumerate(records, start=1):
        name = fixture["name"]
        trf = fixture["trf"]

        skip_reason = external_engine.screen(trf)
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

            external_outcome, external_raw = external_engine.pair(truncated, k)

            for variant_name, tbs_engine in tbs_engines.items():
                tbs_outcome, tbs_raw = tbs_engine.pair(truncated, k)
                cls = classify(tbs_outcome, external_outcome)
                board_order_only = None
                # Board order is only comparable when both engines PAIRED and
                # agree on the pairing itself (MATCH/COLOUR): a PAIRING-class
                # row produced different boards outright, so asking whether
                # they are "the same boards in a different order" is not a
                # question with a useful answer, and report.py's board-order
                # table would otherwise misfile it as "same order".
                if (
                    cls in ("MATCH", "COLOUR")
                    and tbs_raw is not None
                    and external_raw is not None
                ):
                    board_order_only = is_board_order_only_difference(tbs_raw, external_raw)

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
                    "external": _outcome_to_dict(external_outcome),
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
