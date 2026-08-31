# FIDE pairing and tie-break conformance corpus

This directory contains complete, self-contained tournament fixtures for testing
FIDE Dutch individual pairing (C.04.3), FIDE Swiss team pairing (C.04.6), and
C.07 tie-break calculations.

## Files

```
tests/corpus/
  corpus.jsonl.gz            gzip-compressed JSON Lines fixture data
  known_failures.json        active expected failures, grouped by reason
  tiebreak_values.jsonl.gz   per-tie-break value baseline
  _harness.py                corpus loader and in-process checker driver
  test_corpus.py             verdict test entry point
  test_corpus_values.py      tie-break value test entry point
  regen_known_failures.py    expectation regeneration tool
  regen_tiebreak_values.py   value baseline regeneration tool
```

## Corpus contents

The corpus contains 6,000 TRF-2026 tournaments:

| category | valid | invalid | total |
|----------|------:|--------:|------:|
| Individual | 4,281 | 719 | 5,000 |
| Team | 424 | 576 | 1,000 |
| **Total** | **4,705** | **1,295** | **6,000** |

Each decompressed line is one JSON object:

```json
{"name": "ind_00000", "category": "individual", "valid": true,
 "skip": false, "skip_reason": null, "trf": "062 45\n072 45\n001 ..."}
```

| field | type | meaning |
|-------|------|---------|
| `name` | string | unique fixture identifier and pytest test id |
| `category` | string | `"individual"` or `"team"` |
| `valid` | bool | expected checker verdict |
| `skip` | bool | whether the fixture is excluded from the run |
| `skip_reason` | string or null | reason for an exclusion |
| `trf` | string | complete TRF-2026 file text |

No current fixture is skipped. The `skip` fields remain part of the format so a
consumer can stage future additions when necessary.

## What the fixtures cover

| dimension | range |
|-----------|-------|
| individual field size | 20 to 219 players, median 61 |
| team field size | 4 to 16 teams, median 11 |
| boards per team | 2 to 6, spread evenly |
| individual rounds | 5 to 11, median 8 |
| team rounds | 4 to 9, median 7 |
| games | 1.57 million in total, median 225 per fixture |

Feature coverage, by the number of fixtures exercising each:

| feature | individual | team |
|---------|-----------:|-----:|
| Baku acceleration (C.04.7) | 1,586 | 254 |
| prohibited pairings (record 260) | 536 | 0 |
| abnormal assignments (record 299) | 192 | 43 |
| tie-break catalogue (record 212) | 4,612 | 909 |
| forfeits (`+` / `-`) | 3,688 | 615 |
| byes (`U`, `Z`, `H`) | 3,947 | 561 |

Team fixtures additionally cover the Type A and Type B colour models and the
no-preference model of art. 1.7, and match-point and game-point primary scoring,
through the record 192 tournament type codes: every code in the table below
appears, in the counts shown.

| record 192 code | fixtures | | record 192 code | fixtures |
|-----------------|---------:|-|-----------------|---------:|
| `FIDE_TEAM_BAKU` | 254 | | `FIDE_TEAM_TYPEA_MP` | 92 |
| `FIDE_TEAM_MP_GP` | 104 | | `FIDE_TEAM_TYPEB_GP` | 88 |
| `FIDE_TEAM_GP_MP` | 97 | | `FIDE_TEAM_TYPEB_MP` | 87 |
| `FIDE_TEAM_TYPEA_MP_GP` | 95 | | *(no record 192)* | 88 |
| `FIDE_TEAM_TYPEB_MP_GP` | 95 | | | |

### What they do not cover

No fixture carries these records, so the engine's handling of each is held by
unit tests under `tests/` instead:

| record | what it decides | a unit test covers it |
|--------|-----------------|:---:|
| 162 | the game score system | yes |
| 240 | half-point and full-point byes | yes |
| 320 | pairing-allocated byes, which [C2] reads | yes |
| 330 | forfeited team matches | yes |
| 300 | out-of-order pairings, which set board order | yes |
| 352 | the board colour sequence of a team event | yes |
| 362 | the team match-point score system | yes |
| 202 | the tie-breaks used to break a tie in the standings | yes |
| XXZ | competitors who will not meet | yes |

Record 260 appears in individual fixtures only. Eight result codes are absent as
well - `W`, `D` and `L` (an unrated played result), `X` and `?` (which score as
"A"), `F`, `A`, and a blank - so the "A" points class is not scored end to end by
any fixture.

## Verdict semantics

`valid` is an identity verdict, not a general quality score. A fixture is valid
when every declared pairing agrees board-for-board and colour-for-colour with
the pairing prescribed by the engine, and every declared rank agrees with the
ranking calculated from its declared tie-breaks. An invalid fixture deviates
from at least one of those prescribed results.

TRF records the declared ranking but does not carry golden numeric tie-break
values. The corpus therefore detects a tie-break calculation error when it
changes that ranking; it cannot detect an incorrect intermediate value that
leaves the final order unchanged. The reader separately checks that declared
score totals reconcile with the recorded results and score system.

Many invalid fixtures take a valid tournament and apply one isolated change. The
fixture name records the mechanism:

| mechanism | category | change |
|-----------|----------|--------|
| `c1` | individual | repeat pairing |
| `c2` | individual | second pairing-allocated bye for an ineligible player |
| `c3` | individual | pairing of two players with the same absolute colour preference |
| `team_colour` | team | reversed board colours in one match |
| `team_opponent` | team | cross-swapped opponents in two matches |
| `team_rank` | team | swapped final ranks for two teams |

The corrupted files remain parseable and internally consistent; the intended
failure is the mismatch with the prescribed pairing or ranking.

276 further team fixtures are invalid without carrying a mechanism suffix. Of
these, 265 declare a pairing that differs from the one C.04.6 prescribes: 211 in
which different teams are paired together, 19 that declare a round with no legal
pairing at all, and 35 that differ in colour.

Eleven fixtures declare a final rank that differs after the EDE/EDEBT rewrite in
upstream 1.9.57. They are held to the same identity rule as every other fixture:
a declared pairing or rank that is not the prescribed one is invalid, and the
test asserts the engine rejects it.

## Running the tests

The harness writes each embedded `trf` value to a temporary file and drives the
same `common_main` pipeline as `pairingchecker.py` and `tiebreakchecker.py`. It
checks that the tie-break path does not fault and that the combined pairing and
standings identity verdict agrees with `valid`.

By default pytest selects a deterministic sample of about 500 records:

```bash
pytest tests/corpus/ -n auto
```

Set `TIEBREAK_CORPUS_FULL=1` to run all records:

```bash
TIEBREAK_CORPUS_FULL=1 pytest tests/corpus/ -n auto
```

CI runs the complete corpus in round-robin shards. `TIEBREAK_CORPUS_SHARDS`
sets the number of shards and `TIEBREAK_CORPUS_SHARD` selects the zero-based
shard index. Once every runner finishes, CI posts or updates one pull-request
comment with the combined results; the same report remains available on the
workflow run's summary page.

`known_failures.json` holds records whose disagreement with the engine has not
been accounted for, under strict `xfail` markers, so a fixed one becomes an
XPASS and fails the suite until its expectation is removed. **It is currently
empty**: every record runs, and each is expected to produce the verdict its
`valid` flag records - which for 1,295 of them means being rejected. After an
engine change, regenerate the file with:

```bash
python3 tests/corpus/regen_known_failures.py
```

Review and classify every new disagreement rather than treating regeneration as
an automatic re-baseline: the tool writes new names under a single
"unclassified" reason, and they are not fit to commit until each one has been
traced to a cause. A disagreement means either the engine is wrong or the
fixture's expectation is, and which of those it is has to be established rather
than assumed.
