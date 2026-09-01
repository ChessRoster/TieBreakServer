# -*- coding: utf-8 -*-
"""Reads results.jsonl (or a set of shard files already merged by runner.py's
--merge), classifies and groups what came out, and writes a Markdown summary
to REPORT.md. See PLAN-REGRESSION.md section 9.

Usage::

    python3 tests/interop/report.py [--results PATH] [--out PATH] [--repro-dir DIR]

For a representative sample of each divergence group (round number x
tournament-size bucket x class, per tiebreakserver variant) -- the smallest
fixture in the group, up to ~20 groups -- writes a minimal reproducer under
``repro/<group>/``: the truncated TRF and both raw outcomes. Reconstructing
the truncated TRF needs the original fixture text, which results.jsonl does
not carry (only the fixture name), so this looks the fixture back up in
tests/corpus/corpus.jsonl.gz by name and re-truncates it -- deterministic,
since trftrunc.truncate is pure.
"""
import argparse
import gzip
import json
import os
import subprocess
import sys

INTEROP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(INTEROP_DIR))
TESTS_DIR = os.path.dirname(INTEROP_DIR)
for path in (REPO_ROOT, TESTS_DIR, INTEROP_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import trftrunc  # noqa: E402
from engines.bbppairings import BINARY_PATH, TIMEOUT_SECONDS, _blank_250_match_points, _is_pinned_bbp_binary  # noqa: E402

CORPUS_GZ = os.path.join(TESTS_DIR, "corpus", "corpus.jsonl.gz")
DEFAULT_RESULTS = os.path.join(INTEROP_DIR, "results.jsonl")
DEFAULT_OUT = os.path.join(INTEROP_DIR, "REPORT.md")
DEFAULT_REPRO_DIR = os.path.join(INTEROP_DIR, "repro")

VARIANTS = ("default", "weighted")
DIVERGENT_CLASSES = ("COLOUR", "PAIRING", "PAIRABILITY")

SIZE_BUCKETS = [
    (0, 31, "<=31"),
    (32, 63, "32-63"),
    (64, 127, "64-127"),
    (128, float("inf"), "128+"),
]


def size_bucket(num_players):
    if num_players is None:
        return "unknown"
    for lo, hi, label in SIZE_BUCKETS:
        if lo <= num_players <= hi:
            return label
    return "unknown"


# -- loading ----------------------------------------------------------------


def load_results(path):
    meta = None
    skips = []
    comparisons = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            kind = record.get("kind")
            if kind == "meta":
                meta = record
            elif kind == "skip":
                skips.append(record)
            elif kind == "comparison":
                comparisons.append(record)
    return meta, skips, comparisons


_corpus_by_name_cache = None


def _corpus_fixture(name):
    global _corpus_by_name_cache
    if _corpus_by_name_cache is None:
        _corpus_by_name_cache = {}
        with gzip.open(CORPUS_GZ, "rt", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                _corpus_by_name_cache[record["name"]] = record
    return _corpus_by_name_cache.get(name)


# -- aggregation --------------------------------------------------------


def summarize(comparisons):
    by_variant = {v: {"MATCH": 0, "COLOUR": 0, "PAIRING": 0, "PAIRABILITY": 0, "INCONCLUSIVE": 0} for v in VARIANTS}
    board_order = {v: {"same": 0, "order_only": 0, "na": 0} for v in VARIANTS}

    for row in comparisons:
        variant = row["tiebreakserver_variant"]
        cls = row["class"]
        by_variant.setdefault(variant, {"MATCH": 0, "COLOUR": 0, "PAIRING": 0, "PAIRABILITY": 0, "INCONCLUSIVE": 0})
        by_variant[variant][cls] = by_variant[variant].get(cls, 0) + 1

        bo = row.get("board_order_only_difference")
        board_order.setdefault(variant, {"same": 0, "order_only": 0, "na": 0})
        if bo is None:
            board_order[variant]["na"] += 1
        elif bo:
            board_order[variant]["order_only"] += 1
        else:
            board_order[variant]["same"] += 1

    return by_variant, board_order


def summarize_by_platform(comparisons):
    """{platform: {variant: {class: count}}} -- only worth rendering when a
    merged results.jsonl combines shards from more than one OS (the
    interop-sweep GitHub Action's optional Windows run alongside its always-on
    Linux run); a single-OS sweep's platform breakdown is just its overall
    numbers again."""
    by_platform = {}
    for row in comparisons:
        platform = row.get("platform") or "unknown"
        variant = row["tiebreakserver_variant"]
        cls = row["class"]
        counts = by_platform.setdefault(platform, {}).setdefault(
            variant, {"MATCH": 0, "COLOUR": 0, "PAIRING": 0, "PAIRABILITY": 0, "INCONCLUSIVE": 0}
        )
        counts[cls] = counts.get(cls, 0) + 1
    return by_platform


def group_divergences(comparisons):
    """{(variant, class, round, size_bucket): [row, ...]}"""
    groups = {}
    for row in comparisons:
        if row["class"] not in DIVERGENT_CLASSES:
            continue
        key = (row["tiebreakserver_variant"], row["class"], row["round"], size_bucket(row.get("num_players")))
        groups.setdefault(key, []).append(row)
    return groups


# -- reproducer extraction ---------------------------------------------------


def _bbp_checklist(truncated_trf, round_no, out_dir):
    """Best-effort: run bbpPairings -l for this round and save the checklist.
    Never raises -- this is a nice-to-have per PLAN-REGRESSION.md section 9."""
    if not os.path.exists(BINARY_PATH):
        return None
    trf = truncated_trf
    if _is_pinned_bbp_binary(BINARY_PATH):
        trf, _ = _blank_250_match_points(trf)
    input_path = os.path.join(out_dir, "input.trf")
    output_path = os.path.join(out_dir, "bbp_pairing.out")
    checklist_path = os.path.join(out_dir, "bbp_checklist.txt")
    with open(input_path, "w", encoding="latin1") as handle:
        handle.write(trf)
    try:
        subprocess.run(
            [BINARY_PATH, "--dutch", input_path, "-p", output_path, "-l", checklist_path],
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    return checklist_path if os.path.exists(checklist_path) else None


def write_repro(group_key, rows, repro_dir):
    variant, cls, round_no, bucket = group_key
    group_name = "%s_%s_round%02d_%s" % (variant, cls.lower(), round_no, bucket.replace("<=", "le").replace("+", "plus"))
    # Representative: the row with the fewest players (smallest fixture).
    rep = min(rows, key=lambda r: r.get("num_players") or 10 ** 9)

    fixture = _corpus_fixture(rep["fixture"])
    if fixture is None:
        return None

    out_dir = os.path.join(repro_dir, group_name)
    os.makedirs(out_dir, exist_ok=True)

    truncated = trftrunc.truncate(fixture["trf"], rep["round"] - 1)
    with open(os.path.join(out_dir, "truncated.trf"), "w", encoding="latin1") as handle:
        handle.write(truncated)

    with open(os.path.join(out_dir, "outcomes.json"), "w", encoding="utf-8") as handle:
        json.dump(
            {
                "fixture": rep["fixture"],
                "round": rep["round"],
                "num_players": rep.get("num_players"),
                "tiebreakserver_variant": rep["tiebreakserver_variant"],
                "class": rep["class"],
                "board_order_only_difference": rep.get("board_order_only_difference"),
                "tiebreakserver": rep["tiebreakserver"],
                "bbppairings": rep["bbppairings"],
                "group_size": len(rows),
            },
            handle,
            indent=2,
        )

    _bbp_checklist(truncated, rep["round"], out_dir)

    return group_name, rep, len(rows)


# -- markdown -----------------------------------------------------------


def render(meta, skips, comparisons, by_variant, board_order, groups, repro_written, by_platform=None):
    lines = []
    lines.append("# Cross-engine pairing regression report")
    lines.append("")
    lines.append("Generated by `tests/interop/report.py`. See `PLAN-REGRESSION.md` for the design.")
    lines.append("")

    if meta:
        lines.append("## Provenance")
        lines.append("")
        lines.append("| | |")
        lines.append("|---|---|")
        lines.append("| tiebreakserver version | `%s` |" % meta.get("tiebreakserver_version"))
        lines.append("| second engine | `%s %s` |" % (meta.get("bbppairings_name", "bbppairings"), meta.get("bbppairings_version")))
        lines.append("| second engine binary sha256 | `%s` |" % meta.get("bbppairings_sha256"))
        lines.append("| pinned bbpPairings v6.0.0 sha256 | `%s` |" % meta.get("bbppairings_sha256_pinned"))
        lines.append(
            "| pinned build? | %s |"
            % ("yes" if meta.get("bbppairings_is_pinned_build", True) else "no -- section 2.2 static screening rules were skipped, see divergences/INCONCLUSIVE for this engine's own rejections")
        )
        lines.append("")

    total_comparisons = len(comparisons)
    skip_reasons = {}
    for row in skips:
        skip_reasons[row["reason"]] = skip_reasons.get(row["reason"], 0) + 1
    skipped_fixtures = len(skips)

    lines.append("## Coverage")
    lines.append("")
    lines.append("- %d comparison rows (one per (fixture, round, tiebreakserver variant))" % total_comparisons)
    lines.append("- %d fixtures screened out" % skipped_fixtures)
    if skip_reasons:
        lines.append("")
        lines.append("| reason | fixtures |")
        lines.append("|---|---:|")
        for reason, count in sorted(skip_reasons.items(), key=lambda kv: -kv[1]):
            lines.append("| %s | %d |" % (reason, count))
    lines.append("")

    lines.append("## Agreement, by tiebreakserver variant")
    lines.append("")
    lines.append("Agreement rate is `MATCH / (total - INCONCLUSIVE)`. INCONCLUSIVE is stated")
    lines.append("separately and never folded into the denominator.")
    lines.append("")
    lines.append("| variant | MATCH | COLOUR | PAIRING | PAIRABILITY | INCONCLUSIVE | total | agreement rate |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for variant in VARIANTS:
        counts = by_variant.get(variant, {})
        match = counts.get("MATCH", 0)
        colour = counts.get("COLOUR", 0)
        pairing = counts.get("PAIRING", 0)
        pairability = counts.get("PAIRABILITY", 0)
        inconclusive = counts.get("INCONCLUSIVE", 0)
        total = match + colour + pairing + pairability + inconclusive
        denom = total - inconclusive
        rate = (100.0 * match / denom) if denom else float("nan")
        lines.append(
            "| %s | %d | %d | %d | %d | %d | %d | %.2f%% |"
            % (variant, match, colour, pairing, pairability, inconclusive, total, rate)
        )
    lines.append("")

    if by_platform and len(by_platform) > 1:
        lines.append("## Agreement, by platform")
        lines.append("")
        lines.append("This run's shards came from more than one OS (a Windows dispatch alongside")
        lines.append("the always-on Linux one) -- broken out separately since the two ran the")
        lines.append("comparison engine as two different binaries, and the table above already")
        lines.append("folds them together.")
        lines.append("")
        lines.append("| platform | variant | MATCH | COLOUR | PAIRING | PAIRABILITY | INCONCLUSIVE | total | agreement rate |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
        for platform in sorted(by_platform):
            for variant in VARIANTS:
                counts = by_platform[platform].get(variant, {})
                match = counts.get("MATCH", 0)
                colour = counts.get("COLOUR", 0)
                pairing = counts.get("PAIRING", 0)
                pairability = counts.get("PAIRABILITY", 0)
                inconclusive = counts.get("INCONCLUSIVE", 0)
                total = match + colour + pairing + pairability + inconclusive
                denom = total - inconclusive
                rate = (100.0 * match / denom) if denom else float("nan")
                lines.append(
                    "| %s | %s | %d | %d | %d | %d | %d | %d | %.2f%% |"
                    % (platform, variant, match, colour, pairing, pairability, inconclusive, total, rate)
                )
        lines.append("")

    lines.append("## Board order (secondary, non-blocking)")
    lines.append("")
    lines.append("Whether the two engines listed the same boards in the same sequence, among")
    lines.append("rows where both engines PAIRED. Never gates MATCH/divergence -- see")
    lines.append("PLAN-REGRESSION.md section 4.")
    lines.append("")
    lines.append("| variant | same order | order-only difference | n/a (not both PAIRED) |")
    lines.append("|---|---:|---:|---:|")
    for variant in VARIANTS:
        bo = board_order.get(variant, {})
        lines.append("| %s | %d | %d | %d |" % (variant, bo.get("same", 0), bo.get("order_only", 0), bo.get("na", 0)))
    lines.append("")

    lines.append("## Divergences by group")
    lines.append("")
    lines.append("Grouped by (tiebreakserver variant, class, round, tournament-size bucket).")
    lines.append("A reproducer was written for the %d largest groups (smallest fixture in each)." % len(repro_written))
    lines.append("")
    lines.append("| variant | class | round | size bucket | count | repro |")
    lines.append("|---|---|---:|---|---:|---|")
    for key, rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        variant, cls, round_no, bucket = key
        repro = repro_written.get(key)
        repro_cell = "`repro/%s/`" % repro[0] if repro else ""
        lines.append("| %s | %s | %d | %s | %d | %s |" % (variant, cls, round_no, bucket, len(rows), repro_cell))
    if not groups:
        lines.append("| _none_ | | | | | |")
    lines.append("")

    lines.append("## Triage")
    lines.append("")
    lines.append("Not yet triaged here. Per PLAN-REGRESSION.md section 9, each reproducer above")
    lines.append("should be classified by hand into exactly one of `tiebreakserver is wrong`,")
    lines.append("`bbppairings is wrong`, or `underdetermined`, and recorded in `divergences.json`.")
    lines.append("")

    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=DEFAULT_RESULTS)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--repro-dir", default=DEFAULT_REPRO_DIR)
    parser.add_argument("--max-repro-groups", type=int, default=20)
    args = parser.parse_args(argv)

    meta, skips, comparisons = load_results(args.results)
    by_variant, board_order = summarize(comparisons)
    by_platform = summarize_by_platform(comparisons)
    groups = group_divergences(comparisons)

    repro_written = {}
    top_groups = sorted(groups.items(), key=lambda kv: -len(kv[1]))[: args.max_repro_groups]
    for key, rows in top_groups:
        result = write_repro(key, rows, args.repro_dir)
        if result:
            repro_written[key] = result

    markdown = render(meta, skips, comparisons, by_variant, board_order, groups, repro_written, by_platform)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(markdown)

    print("report.py: wrote %s (%d groups, %d reproducers)" % (args.out, len(groups), len(repro_written)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
