# -*- coding: utf-8 -*-
"""Regression tests for chess-JSON construction and its status diagnostics.

The result-reversal table, chessjson.reverse, is held by
tests/test_score_single_sided_result.py::test_reverse_is_defined_for_every_result_letter,
beside the single-sided results it exists to complete.
"""
import chessjson


def test_unsupported_python_version_is_reported_in_status(monkeypatch):
    monkeypatch.setattr(chessjson.sys, "version_info", (3, 10))

    result = chessjson.chessjson().chessjson

    assert result["status"]["code"] == 500
    assert result["status"]["error"] == ["Python version must be at least ver. 3.11"]
