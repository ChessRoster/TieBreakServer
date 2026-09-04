# Cross-engine pairing regression sweep

This directory runs this repository's test corpus through an independent FIDE
Dutch pairing engine binary -- supplied entirely at run time, see
`engines/external_engine.py` -- and compares its answer to this repository's own engine, one
`(fixture, round)` pairing decision at a time. This file is the design: what
the sweep is, how to run it locally, and how to triage what it finds.

## Why

`tests/corpus/` catches *regressions*: a change that moves this engine away
from where it used to be. It cannot catch a *standing misreading* of C.04.3
that this engine has held all along, because its own fixtures are this
engine's own opinion, restated. An external engine is a genuinely independent
implementation of the same rules, so a divergence between the two is
information the corpus alone cannot produce -- whichever engine turns out to
be wrong.

Team tournaments (C.04.6) are out of scope: no independent implementation of
C.04.6 is known to exist.

## Layout

- `engines/base.py` -- the `Engine` protocol and the `Outcome` type both
  adapters return (`PAIRED` / `NO_LEGAL_PAIRING` / `ERROR`); see "Outcome
  model" below.
- `engines/tiebreakserver.py` -- in-process adapter over this repository's own
  engine, driven the same way `tests/corpus/_harness.py` drives it.
- `engines/external_engine.py` -- subprocess adapter over the configured
  external engine binary (`TIEBREAK_INTEROP_ENGINE_*` env vars).
- `trftrunc.py` / `test_trftrunc.py` -- the truncation transform that turns a
  whole tournament into one `(fixture, round)` comparison point (see "The
  truncation transform" below), and its unit tests.
- `normalize.py` -- canonical pairing form and the six-way classifier
  (`MATCH` / `COLOUR` / `PAIRING` / `PAIRABILITY` / `INCONCLUSIVE` / `SKIPPED`).
- `fetch-engine-binary.sh` -- downloads and checksum-verifies a binary (or
  `.tar.gz`/`.tgz` archive) from an arbitrary URL into `bin/` (gitignored).
  Idempotent -- see the script's own header comment for exactly what that
  means here.
- `bin/` -- where the fetched binary lives. Not committed.

- `validate_truncation.py` -- the self-validation gate (see "Running the
  validation gate" below): checks that `trftrunc.truncate` itself isn't
  manufacturing divergences, using this engine's own `-c` check mode (a full
  replay of the *untruncated* fixture) as an oracle for what `-p -n <round>`
  should produce on the truncated file. Pure in-process, no external engine
  needed. **Gate on this before trusting any external-engine divergence.**
- `runner.py` -- the corpus sweep: screens fixtures, truncates each
  `(fixture, round)`, pairs it through `tiebreakserver` (`default` and
  `weighted` variants) and the configured external engine, classifies, and
  writes `results.jsonl`. This is the sweep itself -- see "Running the sweep"
  below; `pytest tests/interop` does not run it (see that section).
- `report.py` -- reads `results.jsonl`, produces `REPORT.md` (coverage,
  agreement rate, divergences by class and by group) and writes a minimal
  reproducer per divergence group under `repro/`.
- `divergences.json` -- gitignored scratch space for jotting hand-triage notes
  while working through a `REPORT.md`; nothing in this directory reads it
  back or writes it automatically (see "Triaging a divergence" below for what
  *is* automated).

## Outcome model

Each engine, for each `(fixture, round)`, returns exactly one of:

| outcome | meaning |
|---|---|
| `PAIRED(pairs, pab)` | a pairing was produced |
| `NO_LEGAL_PAIRING` | the engine states no legal pairing exists |
| `ERROR(code, message)` | anything else -- a crash, a timeout, an unsupported input |

`PAIRED` is normalised to a canonical form before comparison (`normalize.normalize_pairing`):
`pairs` is a frozenset of `(white_startno, black_startno)` tuples and `pab` is
the starting rank receiving the pairing-allocated bye, or `None`. Board order
is deliberately *not* part of this form -- see below.

Comparing a pair of outcomes (`normalize.classify`) gives one of six classes:

| class | condition |
|---|---|
| `MATCH` | both `PAIRED` with identical pairs, colours and PAB; or both `NO_LEGAL_PAIRING` |
| `COLOUR` | both `PAIRED`, same unordered pairings and same PAB, but at least one board has the colours reversed |
| `PAIRING` | both `PAIRED`, different unordered pairings or different PAB |
| `PAIRABILITY` | one `PAIRED`, the other `NO_LEGAL_PAIRING` |
| `INCONCLUSIVE` | either engine returned `ERROR` |
| `SKIPPED` | screened out before either engine ran (`Engine.screen`), not a comparison outcome at all |

`COLOUR` is kept apart from `PAIRING` deliberately: they implicate different
rule families (C.04.3 E versus the bracket and matching rules), and folding
them together would bury a small number of serious pairing divergences under
a larger, more easily explained colour population.

`INCONCLUSIVE` is quarantined and counted as neither agreement nor
divergence -- never folded into the agreement-rate denominator. A run whose
`INCONCLUSIVE` count is not near zero is not reporting on pairing at all, and
`report.py` says so rather than quoting a rate over a shrunken denominator.

**Board order is a secondary, non-blocking dimension.** An external engine's
output order is its own presentation choice, not a claim about C.04 board
assignment. `normalize.is_board_order_only_difference` compares the two
engines' *raw*, board-ordered pairing lists (which each adapter's `pair()`
also returns, alongside the canonical `Outcome` -- see `engines/base.py`) and
is recorded in its own table, but it never gates `MATCH` or a divergence
verdict, and it is only meaningful between two rows that already agree on the
pairing (`MATCH`/`COLOUR`) -- a `PAIRING`-class row's boards are not "the same
boards in a different order" at all, so it is left out of that table rather
than counted as either "same" or "different" order.

## The truncation transform

`trftrunc.truncate(trf_text, keep_rounds) -> trf_text` is the only piece of
real engineering in this directory: a bug here can manufacture a divergence
on *both* sides of a comparison at once, which is exactly why it carries its
own unit tests (`test_trftrunc.py`) and its own self-validation gate
(`validate_truncation.py`, below) rather than being trusted by construction.

What it does, given a whole tournament and a round count to keep:

1. Cuts each `001` line to the results of rounds `1..keep_rounds`, dropping
   the round blocks for anything after.
2. **Recomputes the points column.** An external engine may verify that each
   player's declared score reconciles with their results under the file's
   point system and refuse to proceed otherwise, so a stale points field
   would be a hard stop rather than a subtle skew. The recomputation goes
   through this repository's own TRF reader rather than reimplementing FIDE
   scoring, so it stays correct if the score rules are ever revised.
3. **Recomputes the rank column** from the recomputed points (ties broken by
   starting rank). This is *not* an identity transform even when
   `keep_rounds` is the tournament's full round count and the points
   therefore recompute to exactly what they already were -- ranking a tie by
   starting rank is one defensible rule, but not necessarily the rule a given
   file's own rank column was produced with.
4. **Leaves record `142` (the scheduled round count) untouched.** Baku
   acceleration and several C.04 provisions key off how many rounds the
   tournament is *scheduled* for, not how many have been played; rewriting
   `142` down to `keep_rounds` would quietly change the pairing both engines
   should produce.
5. Leaves `152`, `192`, `162`, `250` and `260` untouched.
6. Filters any per-round records (`240`, `300`, `320`, `330`) to rounds `<= keep_rounds`.

`keep_rounds == 0` drops every round's results (an all-byes-unpaired file).

## Running it locally

Whether local iteration needs Docker depends on the specific comparison-engine
binary in play: some publish only a Linux build, in which case Docker is the
simplest way to run one on any host; a binary with a native build for your OS
needs no container at all. Docker, when needed:

```
docker run --rm -v "$PWD:/w" -w /w python:3.12-slim \
  sh -c 'pip install -q -r requirements.txt -r requirements-dev.txt &&
         tests/interop/fetch-engine-binary.sh --url <URL> --sha256 <SHA256> --out tests/interop/bin/engine.exe &&
         python tests/interop/runner.py --sample 200'
```

Directly, without a container:

```
source /path/to/venv/bin/activate   # deps from requirements*.txt already installed
tests/interop/fetch-engine-binary.sh --url <URL> --sha256 <SHA256> --out tests/interop/bin/engine.exe
python tests/interop/runner.py --sample 200
```

`fetch-engine-binary.sh` is the same script CI runs, so local and CI cannot
drift on which binary is being compared against.

`pytest tests/interop` is **not** the sweep -- it collects and runs this
directory's own fast unit tests (`test_trftrunc.py`, `test_report.py`), which
need no binary and no corpus pass at all. It is a good pre-flight check that
the transform and the report's aggregation are still correct before spending
the time on an actual sweep, not a substitute for one. The sweep itself is
`runner.py`, invoked directly as shown above and in "Running the sweep" below.

### Running the validation gate

```
python3 tests/interop/validate_truncation.py --sample 300   # default sample
python3 tests/interop/validate_truncation.py --full          # every individual fixture
```

Pure in-process, no external engine needed. Exit code is 0 if every checked
round either matched or was an oracle-coverage gap -- a fixture whose full,
untruncated tournament has no legal pairing at all leaves the `-c` oracle
nothing to compare against, which is a gap in what this gate can check, not a
`trftrunc.py` defect (see `validate_truncation.py`'s own comments). It is 1
only when a round is a genuine mismatch. Prints up to `--max-failures` real
mismatches, and the oracle-gap count separately, with enough detail to
reproduce either by hand.

### Running the sweep

Sample (fast local iteration, ~300 fixtures by default):

```
python3 tests/interop/runner.py --sample 200 --out tests/interop/results.jsonl
```

Full sweep, sharded across parallel local processes (or `TIEBREAK_INTEROP_FULL=1`
instead of `--full`):

```
for i in 0 1 2 3; do
  python3 tests/interop/runner.py --full --shard $i --shards 4 \
    --out tests/interop/results.shard$i.jsonl &
done
wait
python3 tests/interop/runner.py --merge tests/interop/results.shard*.jsonl \
  --out tests/interop/results.jsonl
```

`--shard`/`--shards` filters fixtures by `index % shards == shard`; each shard
writes its own file, then `--merge` concatenates them (deduplicating the one
`meta` header line). Pick a shard count from the machine's core count and the
per-fixture cost `runner.py` reports as it runs (`fixtures/s` in its progress
line) -- there is no fixed number that fits every machine or every comparison
engine's own speed.

### Running the report

```
python3 tests/interop/report.py --results tests/interop/results.jsonl \
  --out tests/interop/REPORT.md
```

Writes `REPORT.md` (coverage, agreement rate by tiebreakserver variant, board
order as a secondary table, divergences grouped by variant/class/round/size)
and, for up to the 20 largest divergence groups, a minimal reproducer -- the
truncated TRF, both raw outcomes as JSON, and (best-effort) the external
engine's `-l` checklist for that round -- under `tests/interop/repro/<group>/`.

To poke at a single fixture by hand (useful when triaging), pull one out of
the corpus (see `tests/corpus/_harness.py` for the load pattern -- gzip'd
JSON lines, one `trf` field per record), truncate it, and pair it through
each adapter directly:

```python
import sys
sys.path.insert(0, "tests/interop")
import trftrunc
from engines.tiebreakserver import TieBreakServerEngine
from engines.external_engine import ExternalEngine
import normalize

trf = ...  # a fixture's raw TRF text
truncated = trftrunc.truncate(trf, keep_rounds=k)   # results of rounds 1..k
tbs, tbs_raw = TieBreakServerEngine().pair(truncated, round_no=k + 1)
ext, ext_raw = ExternalEngine().pair(truncated, round_no=k + 1)
print(normalize.classify(tbs, ext), tbs, ext)
```

## Triaging a divergence

1. **Reproduce it in isolation first.** The truncated TRF *is* the minimal
   reproducer -- write it to a file and confirm both engines still disagree on
   it standalone before looking any further.
2. **Check board order isn't the whole story.** `normalize.is_board_order_only_difference`
   flags a same-pairs-different-sequence case; that dimension is recorded but
   never gates a `MATCH`/divergence verdict (the external engine's output order is its
   own presentation ordering, not a C.04 claim). See "Outcome model" above.
3. **Ask the external engine why**, not just what: rerun it with `-l checklist.txt` for
   the same round -- it writes each player's score, colour preference, float
   history, and (Dutch) the C2 bye-eligibility flag and C14/C16 float
   directions. That is usually faster than reading either engine's source.
4. **Confirm it isn't a truncation artefact.** A bug in `trftrunc.truncate`
   can manufacture a divergence on *both* sides at once. Before trusting any
   external-engine divergence, this engine's own `-c` check mode (a full replay of
   the untruncated tournament) should agree with what `-p` produces on the
   truncated file for that same round -- see "The truncation transform" and
   "Running the validation gate" above. That validation is the runner's job,
   not something to redo by hand per case, but it is the first thing to
   suspect if a whole shape of divergence looks implausible.
5. **Classify the verdict** into exactly one of the three buckets
   `tests/corpus/README.md`'s `known_failures.json` discipline already uses
   for this project:
   - **this engine is wrong** -- fix it; the reproducer becomes a test under
     `tests/`.
   - **the external engine is wrong** -- record it with the C.04 citation that settles
     it; consider reporting upstream.
   - **underdetermined** -- C.04.3 admits both pairings here and the two
     engines chose differently. This bucket is expected to be non-empty, and
     it is the interesting one: a case where the rules do not determine a
     unique answer is worth writing down regardless of which engine you'd
     prefer, because it's a fact about the rules, not about either
     implementation.

None of this classification is automated or persisted by anything in this
directory -- `divergences.json` (see "Layout" above) is a convenient, private
scratch file for it, not a tracked record. A team that wants the verdicts to
survive across sweeps needs to commit them somewhere of its own choosing (a
tracked file, an issue tracker, a comment beside the promoted test); whatever
that place is, the rule stays the same as `known_failures.json`'s: regeneration
is not re-baselining. A divergence that was triaged once and found
`underdetermined` or `the external engine is wrong` does not get silently
reclassified because a corpus refresh changed its shape.
