# -*- coding: utf-8 -*-
"""Tests for the two corpus baseline regenerators.

Both scripts rewrite a checked-in file in place, which makes them a class of
their own: a bug in either one does not fail a test, it changes the thing every
other test is measured against.  A baseline regenerated from an eighth of the
corpus, or truncated to the first fifty records, looks exactly like a baseline
regenerated properly -- smaller, and nothing says how big it should have been.

Nothing here runs either script's ``main``.  The corpus is faked, the engine is
faked, and every write goes to a temporary path; the checked-in baselines are
only ever read, and one test asserts explicitly that they are not touched.
"""
import gzip
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

CORPUS_DIR = Path(__file__).parents[1] / "tests" / "corpus"
if not CORPUS_DIR.is_dir():                       # running from inside tests/
    CORPUS_DIR = Path(__file__).parent / "corpus"


def _load(name, filename):
    """Import one of the regen scripts by path, under its own module name."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, CORPUS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


regen_known_failures = _load("regen_known_failures", "regen_known_failures.py")
regen_values = _load("regen_tiebreak_values", "regen_tiebreak_values.py")
_harness = _load("_harness", "_harness.py")


def _fake_corpus(tmp_path, count):
    """A gzipped corpus of *count* trivial records, in the real file's format."""
    path = tmp_path / "corpus.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for index in range(count):
            handle.write(json.dumps({
                "name": "ind_%05d" % index,
                "category": "individual",
                "valid": True,
                "skip": False,
                "trf": "012 fake\n",
            }) + "\n")
    return path


# --------------------------------------------------------------------------
# regen_known_failures.py
# --------------------------------------------------------------------------

def test_known_failure_regeneration_ignores_the_ci_shard_variables(tmp_path,
                                                                   monkeypatch):
    """The regenerator reads the whole corpus even inside a sharded environment.

    ``_harness.load_corpus`` honours ``TIEBREAK_CORPUS_SHARDS`` and
    ``TIEBREAK_CORPUS_SHARD``, which is right for the test suite -- that is how
    CI splits the corpus across eight runners.  The regenerator called the same
    loader, so running it in any shell where those variables were still set
    rewrote the entire checked-in ``known_failures.json`` from one eighth of the
    records.  Every known failure outside that eighth silently disappeared from
    the file, and the test suite then reported the records as unexpected passes
    or, worse, stopped marking real failures at all.  Nothing about the result
    looked wrong; the file is a list of names with no declared length.

    This pins the separation directly: with the variables set to a 1-of-8 split,
    the loader used by the test suite returns an eighth, and the regenerator's
    own loader returns all of it.
    """
    monkeypatch.setattr(_harness, "CORPUS_GZ", _fake_corpus(tmp_path, 16))
    monkeypatch.setenv("TIEBREAK_CORPUS_SHARDS", "8")
    monkeypatch.setenv("TIEBREAK_CORPUS_SHARD", "3")

    # What the test suite sees under those variables: one shard.
    assert len(_harness.load_corpus(full=True)) == 2

    records = regen_known_failures.load_records()

    assert len(records) == 16
    assert [record["name"] for record in records] == \
        ["ind_%05d" % index for index in range(16)]


def test_known_failure_regeneration_skips_records_marked_skip(tmp_path, monkeypatch):
    """Records the corpus marks ``skip`` stay out of the regenerated baseline.

    The loader is new; this keeps the filter that was in ``main`` from being lost
    with the move, since a skipped record is not run by the test either and must
    not be listed as a known failure.
    """
    path = tmp_path / "corpus.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for index, skip in enumerate([False, True, False]):
            handle.write(json.dumps({
                "name": "ind_%05d" % index, "category": "individual",
                "valid": True, "skip": skip, "trf": "012 fake\n"}) + "\n")
    monkeypatch.setattr(_harness, "CORPUS_GZ", path)
    monkeypatch.delenv("TIEBREAK_CORPUS_SHARDS", raising=False)
    monkeypatch.delenv("TIEBREAK_CORPUS_SHARD", raising=False)

    assert [record["name"] for record in regen_known_failures.load_records()] == \
        ["ind_00000", "ind_00002"]


# --------------------------------------------------------------------------
# regen_tiebreak_values.py -- the command line
# --------------------------------------------------------------------------

def test_a_positional_argument_no_longer_truncates_the_baseline(capsys):
    """``regen_tiebreak_values.py 50`` is refused rather than obeyed.

    The script took an undocumented positional ``limit``: ``sys.argv[1]`` was
    read as a record count, and any value there truncated the run *and still
    wrote the real baseline*, leaving a 6000-record file holding fifty rows. The
    remaining records then had no baseline entry at all. There is nothing in the
    usage line about it and nothing in the output that says the file is short.

    Now the only positional-looking argument is rejected by the parser, so the
    old invocation fails loudly instead of quietly shrinking the baseline.
    """
    with pytest.raises(SystemExit) as excinfo:
        regen_values.parse_args(["50"])
    assert excinfo.value.code != 0
    assert "unrecognized arguments" in capsys.readouterr().err


def test_limit_requires_an_output_path_of_its_own(capsys):
    """A truncated run must be told where to write, and it is never the baseline.

    ``--limit`` exists for a quick partial run while working on the generator.
    Its danger is not the truncation but the destination: a short run that writes
    to the checked-in baseline destroys it, and the damage is only visible later,
    as thousands of records with no baseline entry. The flag therefore refuses to
    run without ``--output``.
    """
    with pytest.raises(SystemExit) as excinfo:
        regen_values.parse_args(["--limit", "50"])
    assert excinfo.value.code != 0
    assert "--output" in capsys.readouterr().err

    args = regen_values.parse_args(["--limit", "50", "--output", "/tmp/partial.gz"])
    assert args.limit == 50
    assert str(args.output) == "/tmp/partial.gz"

    # A full run still defaults to the real baseline: that is the ordinary use.
    assert regen_values.parse_args([]).output == regen_values.BASELINE
    assert regen_values.parse_args([]).limit == 0


def test_writing_a_baseline_writes_only_where_it_is_told(tmp_path):
    """``write_baseline`` writes the path it is given and no other.

    The pairing of ``--limit`` with ``--output`` is only worth anything if the
    output path is actually honoured, so this drives the writer at a temporary
    path and checks the checked-in baseline is byte-for-byte untouched by it.
    """
    before = hashlib.md5(regen_values.BASELINE.read_bytes()).hexdigest()
    destination = tmp_path / "partial.jsonl.gz"

    regen_values.write_baseline(destination, [("ind_00000", {"2024": "aaaaaa"}, {})])

    with gzip.open(destination, "rt", encoding="utf-8") as handle:
        header, row = [json.loads(line) for line in handle if line.strip()]
    assert header["common"] == regen_values.COMMON
    assert row == {"name": "ind_00000", "values": {"2024": "aaaaaa"}}
    assert hashlib.md5(regen_values.BASELINE.read_bytes()).hexdigest() == before


# --------------------------------------------------------------------------
# regen_tiebreak_values.py -- column alignment
# --------------------------------------------------------------------------

NAMES = ["PTS", "BH", "SB", "ESB"]


def _fake_engine(monkeypatch, raising):
    """Replace the engine with one that answers per tie-break and raises for the
    names in *raising*, so the alignment of the row can be examined on its own."""
    def _run(lines, names):
        if len(names) > 1:
            raise RuntimeError("one pass over every tie-break is not available")
        if names[0] in raising:
            raise ValueError("this tie-break raises")
        return {1: ["%s-1" % names[0]], 2: ["%s-2" % names[0]]}
    monkeypatch.setattr(regen_values, "_run", _run)


def test_a_raising_first_tiebreak_costs_only_its_own_column(monkeypatch):
    """A tie-break that raises leaves every other column where it was.

    ``values()`` builds each competitor's row by appending one cell per
    tie-break, and it took the competitors to append for from ``columns`` and the
    successful result together.  When the *first* tie-break raised, both were
    empty, so no cell was appended and every later tie-break's value landed one
    position early: the whole row shifted, and PTS's digest was compared against
    BH's value for the rest of the file.  The module's own docstring promises
    that "a tie-break that raises is recorded as ``ERROR`` in its own column and
    does not disturb the others", which is what this pins -- for a raising first
    tie-break, which is the case that broke it.
    """
    _fake_engine(monkeypatch, raising={"PTS"})

    columns, broken = regen_values.values("012 fake", "2026-03-01", NAMES)

    assert broken == ["PTS=ValueError"]
    assert sorted(columns) == [1, 2]
    for cid in columns:
        assert len(columns[cid]) == len(NAMES), \
            "%d cells for %d tie-breaks: the row is out of step" \
            % (len(columns[cid]), len(NAMES))
    assert columns[1] == ["ERROR", "BH-1", "SB-1", "ESB-1"]
    assert columns[2] == ["ERROR", "BH-2", "SB-2", "ESB-2"]


def test_a_raising_tiebreak_does_not_move_the_other_digests(monkeypatch):
    """The digests of the surviving tie-breaks are the ones a clean run gives.

    The consequence of the shift, stated the way the value test sees it: with the
    row out of step, every column after the raising one reported a digest
    belonging to its neighbour, so a single broken tie-break failed the whole
    record and named the wrong tie-breaks as having moved.
    """
    _fake_engine(monkeypatch, raising=set())
    clean, _ = regen_values.column_digests("012 fake", "2026-03-01", NAMES)
    clean_columns = regen_values.split(clean, NAMES)

    _fake_engine(monkeypatch, raising={"PTS"})
    partial, broken = regen_values.column_digests("012 fake", "2026-03-01", NAMES)
    partial_columns = regen_values.split(partial, NAMES)

    assert broken == ["PTS=ValueError"]
    assert partial_columns["PTS"] != clean_columns["PTS"]
    for name in ("BH", "SB", "ESB"):
        assert partial_columns[name] == clean_columns[name], \
            "%s moved because PTS raised" % name


def test_a_tiebreak_that_loses_a_competitor_does_not_shift_the_row(monkeypatch):
    """A result missing a competitor fills that one cell, not the whole row.

    The same appending built a competitor's list only from the point it first
    appeared, so a tie-break that returned a short competitor set left that
    competitor's row shorter than the rest and every one of its cells attributed
    to the wrong tie-break from there on.
    """
    def _run(lines, names):
        if len(names) > 1:
            raise RuntimeError("one pass over every tie-break is not available")
        if names[0] == "PTS":
            return {1: ["PTS-1"]}                 # competitor 2 missing
        return {1: ["%s-1" % names[0]], 2: ["%s-2" % names[0]]}
    monkeypatch.setattr(regen_values, "_run", _run)

    columns, broken = regen_values.values("012 fake", "2026-03-01", NAMES)

    assert broken == []
    assert columns[1] == ["PTS-1", "BH-1", "SB-1", "ESB-1"]
    assert columns[2] == ["ERROR", "BH-2", "SB-2", "ESB-2"]
