# Cross-engine pairing regression sweep

This directory runs this repository's test corpus through an independent FIDE
Dutch pairing engine -- [bbpPairings](https://github.com/BieremaBoyzProgramming/bbpPairings)
v6.0.0 -- and compares its answer to this repository's own engine, one
`(fixture, round)` pairing decision at a time. See `../../PLAN-REGRESSION.md`
for the full design; this file is the short version: what the sweep is, how
to run it locally, and how to triage what it finds.

## Why

`tests/corpus/` catches *regressions*: a change that moves this engine away
from where it used to be. It cannot catch a *standing misreading* of C.04.3
that this engine has held all along, because its own fixtures are this
engine's own opinion, restated. bbpPairings is a genuinely independent
implementation of the same rules, so a divergence between the two is
information the corpus alone cannot produce -- whichever engine turns out to
be wrong.

Team tournaments (C.04.6) are out of scope: bbpPairings rejects them outright
and no independent implementation of C.04.6 is known to exist.

## Layout

- `engines/base.py` -- the `Engine` protocol and the `Outcome` type both
  adapters return (`PAIRED` / `NO_LEGAL_PAIRING` / `ERROR`).
- `engines/tiebreakserver.py` -- in-process adapter over this repository's own
  engine, driven the same way `tests/corpus/_harness.py` drives it.
- `engines/bbppairings.py` -- subprocess adapter over the pinned bbpPairings
  binary.
- `trftrunc.py` / `test_trftrunc.py` -- the truncation transform that turns a
  whole tournament into one `(fixture, round)` comparison point, and its unit
  tests.
- `normalize.py` -- canonical pairing form and the six-way classifier
  (`MATCH` / `COLOUR` / `PAIRING` / `PAIRABILITY` / `INCONCLUSIVE` / `SKIPPED`).
- `fetch-bbppairings.sh` -- downloads and checksum-verifies the pinned
  bbpPairings release into `bin/` (gitignored). Idempotent.
- `bin/` -- where the fetched binary lives. Not committed.

- `validate_truncation.py` -- the self-validation gate (PLAN-REGRESSION.md
  section 7 step 4): checks that `trftrunc.truncate` itself isn't
  manufacturing divergences, using this engine's own `-c` check mode (a full
  replay of the *untruncated* fixture) as an oracle for what `-p -n <round>`
  should produce on the truncated file. Pure in-process, no bbpPairings
  needed. **Gate on this before trusting any bbpPairings divergence** -- see
  "Known gap" below; as of this writing it does not pass cleanly.
- `runner.py` -- the corpus sweep: screens fixtures, truncates each
  `(fixture, round)`, pairs it through `tiebreakserver` (`default` and
  `weighted` variants) and `bbppairings`, classifies, and writes
  `results.jsonl`.
- `report.py` -- reads `results.jsonl`, produces `REPORT.md` (coverage,
  agreement rate, divergences by class and by group) and writes a minimal
  reproducer per divergence group under `repro/`.

Not yet built here: `divergences.json` (hand-triaged verdicts, to be filled in
once the known gap below is resolved and a real sweep is trustworthy) and the
CI workflow.

### Known gap: requested byes declared in the round being paired

`validate_truncation.py` does **not** currently pass cleanly -- roughly
14-17% of rounds mismatch in every sample tried. Every mismatch traced so far
has the same shape: a player has a pre-declared exemption for round *k*
itself -- record 001's round-*k* block reads opponent `0000` with a non-blank
result code (`Z`/`H`/`F`/`U`, a requested/forced bye known before the round is
paired, not one the pairing algorithm assigns) -- and `trftrunc.truncate(trf,
k-1)` drops that information, because it lives in round *k*'s own block and
the transform keeps only rounds `<= keep_rounds = k-1` (PLAN-REGRESSION.md
section 5, point 1). Both engines then pair round *k* not knowing that player
is unavailable, which can (a) produce a wrong pairing that still **matches
between the two engines** (since both are equally misled by the same missing
input, silently inflating the agreement rate) or (b) produce a spurious
divergence that has nothing to do with either engine's C.04.3 reading.

This was found while building the gate, not fixed -- `trftrunc.py` is out of
scope for this change (see the module docstring and PLAN-REGRESSION.md
section 5's own spec, which is explicit that only rounds `<= keep_rounds` are
kept). Confirmed on every mismatch in two independent ~300-fixture samples.
Any full sweep run before this is addressed should be read with that caveat
prominently attached.

## Running it locally

The binary is Linux-only (no macOS build), so local iteration on any host
goes through Docker:

```
docker run --rm -v "$PWD:/w" -w /w python:3.12-slim \
  sh -c 'pip install -q -r requirements.txt -r requirements-dev.txt &&
         tests/interop/fetch-bbppairings.sh &&
         pytest tests/interop -n auto'
```

On Linux directly, the same steps without Docker:

```
source /path/to/venv/bin/activate   # deps from requirements*.txt already installed
tests/interop/fetch-bbppairings.sh
pytest tests/interop -n auto
```

`fetch-bbppairings.sh` is the same script CI runs, so local and CI cannot
drift on which binary is being compared against.

### Running the validation gate

```
python3 tests/interop/validate_truncation.py --sample 300   # default sample
python3 tests/interop/validate_truncation.py --full          # every individual fixture
```

Pure in-process, no bbpPairings needed. Exit code is 0 only if every checked
round matched; prints up to `--max-failures` mismatches with enough detail to
reproduce by hand. As of this writing it does not exit 0 -- see "Known gap"
above.

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
`meta` header line). See this file's timing note below (or the task that
produced it) for how many shards this machine's core count supports.

### Running the report

```
python3 tests/interop/report.py --results tests/interop/results.jsonl \
  --out tests/interop/REPORT.md
```

Writes `REPORT.md` (coverage, agreement rate by tiebreakserver variant, board
order as a secondary table, divergences grouped by variant/class/round/size)
and, for up to the 20 largest divergence groups, a minimal reproducer -- the
truncated TRF, both raw outcomes as JSON, and (best-effort) bbpPairings' `-l`
checklist for that round -- under `tests/interop/repro/<group>/`.

To poke at a single fixture by hand (useful when triaging), pull one out of
the corpus (see `tests/corpus/_harness.py` for the load pattern -- gzip'd
JSON lines, one `trf` field per record), truncate it, and pair it through
each adapter directly:

```python
import sys
sys.path.insert(0, "tests/interop")
import trftrunc
from engines.tiebreakserver import TieBreakServerEngine
from engines.bbppairings import BbpPairingsEngine
import normalize

trf = ...  # a fixture's raw TRF text
truncated = trftrunc.truncate(trf, keep_rounds=k)   # results of rounds 1..k
tbs = TieBreakServerEngine().pair(truncated, round_no=k + 1)
bbp = BbpPairingsEngine().pair(truncated, round_no=k + 1)
print(normalize.classify(tbs, bbp), tbs, bbp)
```

## Triaging a divergence

1. **Reproduce it in isolation first.** The truncated TRF *is* the minimal
   reproducer -- write it to a file and confirm both engines still disagree on
   it standalone before looking any further.
2. **Check board order isn't the whole story.** `normalize.is_board_order_only_difference`
   flags a same-pairs-different-sequence case; that dimension is recorded but
   never gates a `MATCH`/divergence verdict (bbpPairings' output order is its
   own presentation ordering, not a C.04 claim).
3. **Ask bbpPairings why**, not just what: rerun it with `-l checklist.txt` for
   the same round -- it writes each player's score, colour preference, float
   history, and (Dutch) the C2 bye-eligibility flag and C14/C16 float
   directions. That is usually faster than reading either engine's source.
4. **Confirm it isn't a truncation artefact.** A bug in `trftrunc.truncate`
   can manufacture a divergence on *both* sides at once. Before trusting any
   bbpPairings divergence, this engine's own `-c` check mode (a full replay of
   the untruncated tournament) should agree with what `-p` produces on the
   truncated file for that same round -- see PLAN-REGRESSION.md section 7
   step 4. That validation is the runner's job, not something to redo by hand
   per case, but it is the first thing to suspect if a whole shape of
   divergence looks implausible.
5. **Classify the verdict** into exactly one of the three buckets
   `tests/corpus/README.md`'s `known_failures.json` discipline already uses
   for this project, recorded (once `divergences.json` exists) grouped by
   reason:
   - **this engine is wrong** -- fix it; the reproducer becomes a test under
     `tests/`.
   - **bbpPairings is wrong** -- record it with the C.04 citation that settles
     it; consider reporting upstream.
   - **underdetermined** -- C.04.3 admits both pairings here and the two
     engines chose differently. This bucket is expected to be non-empty, and
     it is the interesting one: a case where the rules do not determine a
     unique answer is worth writing down regardless of which engine you'd
     prefer, because it's a fact about the rules, not about either
     implementation.

Regeneration is not re-baselining: a divergence that was triaged once and
found `underdetermined` or `bbppairings is wrong` does not get silently
reclassified because a corpus refresh changed its shape.
