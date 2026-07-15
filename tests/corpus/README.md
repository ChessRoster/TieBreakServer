# TRF corpus

A regression corpus of TRF tournament files. Each record carries the verdict the
engine is expected to reach; the test runs the real command-line checker over the
tournament and asserts the engine agrees.

## Files

```
tests/corpus/
  corpus.jsonl.gz            the corpus: gzip-compressed JSON lines, one tournament per line
  known_failures.json        records the current engine gets wrong (xfail), grouped by reason
  _harness.py                loads the corpus and drives the checker in-process
  test_corpus.py             the pytest entry point
  regen_known_failures.py    regenerates known_failures.json against the current engine
```

## Corpus format

`corpus.jsonl.gz` is a gzip of a [JSON Lines](https://jsonlines.org/) file. Each
line is one tournament:

```json
{"name": "ind_00000", "category": "individual", "valid": true,
 "skip": false, "skip_reason": null, "trf": "062 45\n072 45\n001    1 ..."}
```

| field         | type            | meaning |
|---------------|-----------------|---------|
| `name`        | string          | unique id, also the pytest test id |
| `category`    | string          | `"individual"` or `"team"` |
| `valid`       | bool            | **the expected verdict** — whether the engine should accept the tournament |
| `skip`        | bool            | if true the record is not run at all |
| `skip_reason` | string \| null  | why it is skipped (shown in the pytest skip report) |
| `trf`         | string          | the tournament as a TRF-2026 file, newlines embedded |

`valid` is the golden output: there are no separate golden files. A record is
"valid" when the tournament is well-formed and correctly paired, so the engine
should accept it; it is invalid when it is malformed or mispaired, so the engine
should reject it.

## What the test asserts

For every non-skipped record the harness drives the tournament through the same
`common_main` pipeline the `pairingchecker.py` and `tiebreakchecker.py` command
line tools use — the full read → prepare → check → apply path, run in-process so
the interpreter and networkx load once per worker rather than once per record —
and checks two things:

1. **The tie-break path does not fault** (status 510) on the tournament.
2. **The engine's accept/reject verdict matches `valid`.** The engine accepts a
   tournament exactly when its pairing check passes: the pairing it recomputes
   for every round equals the one the file declares.

The corpus is large, so `pytest-xdist` (`-n auto`) spreads records across cores.
Each record still rebuilds its own pairing graph — the irreducible cost of
checking a distinct tournament — so wall-clock scales with core count.

## Sample vs. full

By default the test runs a fast deterministic **sample** of the corpus (about
500 records), which is enough for quick local feedback. Set
`TIEBREAK_CORPUS_FULL=1` to run the **whole** corpus:

```bash
pytest tests/corpus/ -n auto                     # sample
TIEBREAK_CORPUS_FULL=1 pytest tests/corpus/ -n auto   # full
```

CI runs the whole corpus on every run, on both interpreters, split across
parallel runners: set `TIEBREAK_CORPUS_SHARDS` to the number of shards and
`TIEBREAK_CORPUS_SHARD` to a runner's 0-based index, and each runner checks a
round-robin slice of the corpus. The sample is a local convenience.

## Markers (data-driven)

Both marker kinds come from data, never from code, so a follow-up change retags a
record by editing a file, not `test_corpus.py`:

* **skip** — any record with `"skip": true` is skipped with its `skip_reason`.
  Today that is the whole `team` category: the FIDE Swiss Team system (C.04.6) is
  validated separately and is not wired into this branch.
* **xfail** — any record named in `known_failures.json` is expected to fail,
  because of a known, not-yet-fixed engine bug. The file groups record names by
  reason:

  ```json
  {
    "accelerated pairing (TRF-2026 record 250) is not yet ... ": ["ind_00042", "ind_00087"],
    "another distinct bug, described here": ["ind_01234"]
  }
  ```

  The markers are `strict`: when a bug is fixed its records start passing, which
  turns them into XPASS and fails the suite — the signal to remove them from
  `known_failures.json`.

## Maintaining the corpus

* **Adding tournaments:** append JSON-lines records to the corpus and recompress
  (`gzip`). Give each a unique `name`, set `valid`, and set `skip`/`skip_reason`
  for anything not yet meant to run. No test code changes are needed.
* **After an engine change:** run `python tests/corpus/regen_known_failures.py`,
  which reruns the corpus and rewrites `known_failures.json`, preserving the
  reason for records that still fail, dropping records that now pass, and listing
  any newly failing records as `unclassified` for you to describe. Review the
  diff before committing.
