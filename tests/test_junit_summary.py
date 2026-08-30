# -*- coding: utf-8 -*-
"""Tests for the matrix JUnit summary's logical-case accounting."""
import importlib.util
import re
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".github" / "scripts" / "junit_summary.py"
SPEC = importlib.util.spec_from_file_location("junit_summary", SCRIPT)
junit_summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(junit_summary)


def _write_results(path, cases):
    body = []
    for classname, name, outcome, detail in cases:
        child = ""
        if outcome == "xfailed":
            child = '<skipped type="pytest.xfail" message="%s" />' % detail
        elif outcome == "skipped":
            child = '<skipped type="pytest.skip" message="%s" />' % detail
        elif outcome in ("failure", "error"):
            child = '<%s message="%s" />' % (outcome, detail)
        body.append(
            '<testcase classname="%s" name="%s">%s</testcase>'
            % (classname, name, child)
        )
    path.write_text("<testsuite>%s</testsuite>" % "".join(body), encoding="utf-8")


def test_identical_versions_and_repeated_shards_count_logical_cases_once(tmp_path):
    cases = [
        ("tests.corpus.test_corpus", "test_corpus_record[ind_00001]", "passed", ""),
        ("tests.test_example", "test_unit", "passed", ""),
        ("tests.corpus.test_corpus", "test_corpus_record[team_00001]", "xfailed", "known bug"),
    ]
    repeated_unit = [("tests.test_example", "test_unit", "passed", "")]
    for python in ("3.11", "3.14"):
        _write_results(tmp_path / ("results-%s-1.xml" % python), cases)
        _write_results(tmp_path / ("results-%s-2.xml" % python), repeated_unit)

    report = junit_summary.collect(tmp_path)
    rendered = junit_summary.render(report)

    assert report["by_group"]["Individual pairing (corpus)"]["passed"] == 1
    assert report["by_group"]["Team pairing (corpus)"]["xfailed"] == 1
    assert report["by_group"]["Unit & regression tests"]["passed"] == 1
    assert report["by_python"]["3.11"]["passed"] == 2
    assert report["by_python"]["3.14"]["passed"] == 2
    assert report["xfail_reasons"] == {"known bug": 1}
    assert "3 cases across 2 Python version(s)" in rendered
    assert "**1×** known bug" in rendered


def test_python_disagreement_counts_one_logical_failure(tmp_path):
    passed = [("tests.test_example", "test_unit", "passed", "")]
    failed = [("tests.test_example", "test_unit", "failure", "only on 3.14")]
    _write_results(tmp_path / "results-3.11-1.xml", passed)
    _write_results(tmp_path / "results-3.14-1.xml", failed)

    report = junit_summary.collect(tmp_path)
    rendered = junit_summary.render(report)

    assert report["by_group"]["Unit & regression tests"]["failed"] == 1
    assert report["by_python"]["3.11"]["passed"] == 1
    assert report["by_python"]["3.14"]["failed"] == 1
    assert "**❌ 1 failed / errored** — 1 cases" in rendered


def test_same_outcome_different_message_across_shards_is_not_an_integrity_error(tmp_path):
    """A failure message differing by shard is not a shard disagreement.

    Every unit test in the matrix runs in all eight corpus shards, under the
    same Python version, so the same case id reaches ``collect`` once per
    shard. ``collect`` used to compare the whole result -- message included --
    across those arrivals, and flagged any difference as a "conflicting
    duplicate result" integrity problem. A failure message can legitimately
    differ between shards that agree the test failed: a captured object's
    repr address, a line number from a shard-specific temp path, a timing
    figure. None of that is a disagreement about the *outcome*.
    """
    first = [("tests.test_example", "test_unit", "failure", "boom at line 12")]
    second = [("tests.test_example", "test_unit", "failure", "boom at line 47")]
    _write_results(tmp_path / "results-3.11-1.xml", first)
    _write_results(tmp_path / "results-3.11-2.xml", second)

    report = junit_summary.collect(tmp_path)

    assert report["parse_errors"] == []
    assert report["by_group"]["Unit & regression tests"]["failed"] == 1


def test_different_outcome_across_shards_is_still_an_integrity_error(tmp_path):
    """Shards that disagree about the outcome itself are still flagged.

    Ignoring the message must not swallow a real disagreement: one shard
    reporting a pass and another a failure for the same case id under the
    same Python version means the shards do not agree what happened, which is
    exactly the kind of problem this integrity check exists to surface.
    """
    passing = [("tests.test_example", "test_unit", "passed", "")]
    failing = [("tests.test_example", "test_unit", "failure", "boom")]
    _write_results(tmp_path / "results-3.11-1.xml", passing)
    _write_results(tmp_path / "results-3.11-2.xml", failing)

    report = junit_summary.collect(tmp_path)

    assert len(report["parse_errors"]) == 1
    assert "conflicting duplicate result" in report["parse_errors"][0][1]


def _capture(argv, capsys):
    """Run the script's ``main`` the way the workflow does and return
    ``(exit code, markdown)``."""
    code = junit_summary.main(["junit_summary.py"] + argv)
    return code, capsys.readouterr().out


def test_missing_junit_shard_never_says_all_passed(tmp_path, capsys):
    """A run whose shard artifacts are incomplete is never reported as a pass.

    The workflow's matrix is two Python versions across eight corpus shards, so
    sixteen JUnit files must arrive.  A ``conftest`` or import error that kills a
    shard leaves its job red but produces no artifact at all, and the aggregate
    over what *did* arrive is then entirely green.  Before ``--expect-files`` the
    summary counted files, printed the count and never compared it to anything,
    so fifteen green shards rendered "✅ All checks passed ... 15 shard result
    file(s)" and exited 0 -- a passing gate over a red run.

    This pins the comparison itself: with one of sixteen files absent, the
    headline must not claim a pass, the report must say what is missing, and the
    exit status must be non-zero so the summary job goes red with it.
    """
    passing = [("tests.test_example", "test_unit", "passed", "")]
    written = 0
    for python in ("3.11", "3.14"):
        for shard in range(1, 9):
            if (python, shard) == ("3.14", 8):
                continue                      # the shard whose job died on import
            _write_results(tmp_path / ("results-%s-%d.xml" % (python, shard)), passing)
            written += 1
    assert written == 15

    code, rendered = _capture(["--expect-files", "16", str(tmp_path)], capsys)

    assert code != 0
    assert "All checks passed" not in rendered
    assert "Incomplete" in rendered
    assert "1 of 16" in rendered


def test_malformed_only_junit_reports_parser_error(tmp_path, capsys):
    """Nothing but unparseable XML is reported as a parser error, not as silence.

    ``render`` used to return as soon as no case had been parsed, which put the
    early return *before* the block that lists unparseable files: two corrupt
    shard files produced the single line "No JUnit results were found to
    summarise" -- naming neither file nor reason -- and ``main`` returned 0
    regardless.  The whole diagnostic was dropped on the floor precisely when it
    was the only thing left to report.

    This pins that both corrupt files are named, that the parser's own message
    survives into the report, and that the exit status is non-zero.
    """
    (tmp_path / "results-3.11-1.xml").write_text("<testsuite>", encoding="utf-8")
    (tmp_path / "results-3.14-1.xml").write_text("not xml at all", encoding="utf-8")

    code, rendered = _capture(["--expect-files", "2", str(tmp_path)], capsys)

    assert code != 0
    assert "results-3.11-1.xml" in rendered
    assert "results-3.14-1.xml" in rendered
    # The parser's own diagnostic, not just the file name.
    assert "line 1" in rendered
    assert "All checks passed" not in rendered


def test_corpus_value_cases_are_classified_as_corpus():
    """Both corpus tests are filed under the corpus, not under the unit tests.

    ``tests/corpus/test_corpus_values.py`` parametrises ``test_corpus_record_values``
    over the same records as ``test_corpus_record``, so the two names differ only
    by a suffix.  The classifier anchored on ``test_corpus_record\\[``, which the
    longer name does not match, and roughly six thousand corpus cases were
    reported as hand-written unit tests -- swamping the group whose size is the
    only signal that the unit suite itself ran.
    """
    assert junit_summary._group_of("test_corpus_record[ind_00123]") == \
        junit_summary._INDIVIDUAL
    assert junit_summary._group_of("test_corpus_record[team_00045]") == \
        junit_summary._TEAM
    assert junit_summary._group_of("test_corpus_record_values[ind_00123]") == \
        junit_summary._INDIVIDUAL
    assert junit_summary._group_of("test_corpus_record_values[team_00045]") == \
        junit_summary._TEAM
    # A genuine unit test is still a unit test.
    assert junit_summary._group_of("test_the_baseline_covers_the_whole_corpus") == \
        junit_summary._UNIT


def test_summary_escapes_untrusted_skip_reason(tmp_path, capsys):
    """Artifact text cannot close a tag or forge a verdict in the comment.

    On a ``pull_request`` the ``junit-*`` artifacts are produced by the *fork's*
    copy of the workflow, so a fork controls every string in them -- skip reasons
    included.  The rendered Markdown is posted to the pull request by a job
    holding ``pull-requests: write``, so anything copied through verbatim is
    written into the repository's own bot comment.

    A skip reason of ``- **1x** </details><img src=x>**ALL GREEN** [click](...)``
    used to reach the comment unaltered: it closed the surrounding ``<details>``
    element, injected an image tag and printed a bold green verdict of its own
    above the real one.  This pins that the tag markers, the emphasis and the
    link syntax are all neutralised, and that the text still arrives readable.
    """
    hostile = "- **1x** &lt;/details&gt;&lt;img src=x&gt;**ALL GREEN** [click](http://evil)"
    _write_results(tmp_path / "results-3.11-1.xml",
                   [("tests.corpus.test_corpus", "test_corpus_record[ind_00001]",
                     "skipped", hostile)])

    code, rendered = _capture(["--expect-files", "1", str(tmp_path)], capsys)

    assert code == 0
    assert "</details><img src=x>" not in rendered
    assert "&lt;/details&gt;&lt;img src=x&gt;" in rendered   # inert, and still readable
    assert "**ALL GREEN**" not in rendered
    assert "[click](http://evil)" not in rendered
    # The reader can still tell what the reason said.
    assert "ALL GREEN" in rendered
    assert "http://evil" in rendered


def test_case_id_neutralises_embedded_newlines(tmp_path, capsys):
    """A hostile test id cannot break out of its Markdown code span.

    ``_case_id`` fed the raw ``classname``/``name`` straight through, and
    ``_code`` only replaced a literal backtick. A JUnit ``name`` carrying
    ``&#10;`` character references decodes, via ordinary XML attribute-value
    normalisation, to real newline characters in the string this script sees
    -- a *raw* newline in the source attribute is not enough to reproduce
    this, because the XML parser itself folds that to a single space before
    ``_case_id`` ever runs (which is why this builds the XML by hand instead
    of going through ``_write_results``). A blank line inside a Markdown code
    span ends the paragraph the span sits in, so the backticks stop fencing
    anything at that point: a forged ``## All checks passed`` prints as a
    real heading, and whatever follows -- here an ``<img>`` tag -- prints as
    raw, un-fenced Markdown/HTML rather than literal code-span text.

    Before the fix: the report contained the literal, blank-line-delimited
    substring ``"\\n\\n## All checks passed\\n\\n"`` and the ``<img>`` tag
    started its own line, outside any backtick span. After collapsing
    whitespace in both ``_case_id`` and ``_code``, the whole hostile id
    renders on one line inside one intact code span, so neither survives.
    """
    hostile_name = ("test_x[&#10;&#10;## All checks passed&#10;&#10;"
                    "&lt;img src=x onerror=alert(1)&gt;]")
    xml = ('<testsuite><testcase classname="tests.test_x" name="%s">'
           '<failure message="boom" /></testcase></testsuite>' % hostile_name)
    (tmp_path / "results-3.11-1.xml").write_text(xml, encoding="utf-8")

    code, rendered = _capture(["--expect-files", "1", str(tmp_path)], capsys)

    assert "\n\n## All checks passed\n\n" not in rendered
    assert re.search(r"^<img src=x onerror=alert\(1\)>", rendered, re.M) is None
    # The hostile id still shows up, but inertly: one line, inside one
    # unbroken code span.
    assert ("`tests.test_x::test_x[ ## All checks passed "
            "<img src=x onerror=alert(1)>]`") in rendered


WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"

_PYTHONS_RE = re.compile(r"^\s*python-version:\s*\[(?P<items>[^\]]*)\]\s*$", re.M)
_SHARD_RE = re.compile(r"^\s*- \{number:\s*\d+,\s*index:\s*\d+\}\s*$", re.M)
_EXPECTED_RE = re.compile(r'^\s*EXPECTED_JUNIT_FILES:\s*"(?P<count>\d+)"\s*$', re.M)


def _expected_junit_files(workflow):
    found = _EXPECTED_RE.findall((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    assert len(found) == 1, \
        "%s should declare EXPECTED_JUNIT_FILES exactly once, found %d" \
        % (workflow, len(found))
    return int(found[0])


def test_expected_shard_count_matches_the_workflow_matrix():
    """The shard-count expectation is the size of the matrix, in both workflows.

    ``--expect-files`` is only as good as the number handed to it: set too low it
    lets a missing shard through, set too high it reddens every run.  The number
    lives in the workflow rather than in the script so the matrix and the
    expectation sit in one file, but nothing in YAML ties them together -- adding
    a ninth shard or a third Python version would leave the expectation at 16 and
    quietly restore the hole this whole check exists to close.

    So the coupling is asserted here instead: the declared expectation must equal
    the number of Python versions times the number of shards in ``tests.yml``, and
    the fork-comment workflow -- which runs from the default branch and cannot
    read ``tests.yml``'s matrix at run time -- must carry the same number.
    """
    tests_yml = (WORKFLOWS / "tests.yml").read_text(encoding="utf-8")

    pythons = _PYTHONS_RE.search(tests_yml)
    assert pythons, "could not find the python-version matrix axis in tests.yml"
    python_count = len([item for item in pythons.group("items").split(",")
                        if item.strip()])
    shard_count = len(_SHARD_RE.findall(tests_yml))
    assert python_count >= 1 and shard_count >= 1, \
        "matrix axes parsed as %d python(s) x %d shard(s)" % (python_count, shard_count)

    assert _expected_junit_files("tests.yml") == python_count * shard_count
    assert _expected_junit_files("test-summary-comment.yml") == \
        _expected_junit_files("tests.yml")


def test_both_workflows_pass_the_expectation_to_the_summary_script():
    """Neither workflow may run the summary without telling it what to expect.

    Without ``--expect-files`` the script has nothing to compare the arriving
    artifacts against and says so in its output, but a silently weakened gate is
    what this whole item is about, so the flag is pinned here as part of the
    invocation rather than left to review.
    """
    for workflow in ("tests.yml", "test-summary-comment.yml"):
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        assert "junit_summary.py" in text, "%s no longer runs the summary" % workflow
        assert '--expect-files "$EXPECTED_JUNIT_FILES"' in text, \
            "%s runs junit_summary.py without --expect-files" % workflow
