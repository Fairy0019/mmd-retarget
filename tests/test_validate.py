# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest

from mmd_retarget.validate import (
    classify,
    diff_reports,
    make_record,
    read_csv,
    summarize,
    write_csv,
)


def test_severity_thresholds():
    assert classify(1.9) is None
    assert classify(2.0) == "low"
    assert classify(9.9) == "low"
    assert classify(10.0) == "medium"
    assert classify(29.9) == "medium"
    assert classify(30.0) == "high"


def test_record_and_suggestion():
    r = make_record(10, "leftArm", "torso", 42.0, pairs=7)
    assert r["severity"] == "high"
    assert r["suggestion"] == "retarget:arm_ik"
    assert r["pairs"] == 7


def test_below_threshold_rejected():
    with pytest.raises(ValueError):
        make_record(1, "leftArm", "torso", 1.0)


def test_csv_roundtrip(tmp_path):
    records = [
        make_record(1, "leftArm", "torso", 12.0),
        make_record(2, "leftLeg", "skirt", 3.5),
    ]
    path = tmp_path / "r.csv"
    write_csv(records, path)
    assert read_csv(path) == records


def test_diff_reports():
    old = [
        make_record(1, "leftArm", "torso", 20.0),
        make_record(2, "leftArm", "torso", 5.0),
        make_record(3, "leftLeg", "skirt", 8.0),
    ]
    new = [
        make_record(1, "leftArm", "torso", 25.0),  # worse
        make_record(2, "leftArm", "torso", 2.5),   # better
        make_record(4, "leftLeg", "skirt", 3.0),   # new
    ]
    d = diff_reports(old, new)
    assert [x["frame"] for x in d["worse"]] == [1]
    assert [x["frame"] for x in d["better"]] == [2]
    assert [x["frame"] for x in d["new"]] == [4]
    assert [x["frame"] for x in d["fixed"]] == [3]


def test_summarize():
    records = [
        make_record(1, "leftArm", "torso", 40.0),
        make_record(2, "leftArm", "torso", 12.0),
        make_record(2, "leftLeg", "skirt", 4.0),
    ]
    s = summarize(records)
    assert s["records"] == 3
    assert s["frames"] == 2
    assert s["by_severity"] == {"high": 1, "medium": 1, "low": 1}
    assert s["max_depth_mm"] == 40.0


def test_regression_ok():
    from mmd_retarget.validate import regression_ok

    d = {"new": [1, 2], "fixed": [], "worse": [1], "better": []}
    assert regression_ok(d) is True
    assert regression_ok(d, max_new=2, max_worse=1) is True
    assert regression_ok(d, max_new=1) is False
    assert regression_ok(d, max_worse=0) is False

def test_pick_visibility_points_topk_distinct():
    from mmd_retarget.validate import pick_visibility_points

    pts = [(5.0, (0, 0, 0)), (4.0, (0, 0, 0)), (3.0, (1, 0, 0)), (2.0, (2, 0, 0))]
    picked = pick_visibility_points(pts, 2)
    assert picked == [(0, 0, 0), (1, 0, 0)]


def test_visibility_from_ratios():
    from mmd_retarget.validate import visibility_from_ratios

    assert visibility_from_ratios({}) == ("unknown", None)
    assert visibility_from_ratios({"a": 1.0}) == ("yes", 1.0)
    assert visibility_from_ratios({"a": 0.4})[0] == "partial"
    assert visibility_from_ratios({"a": 0.0})[0] == "no"
    assert visibility_from_ratios({"a": 0.2, "b": 0.9}) == ("yes", 0.9)


def test_contact_sheet_html(tmp_path):
    from mmd_retarget.validate import write_contact_sheet

    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    (thumbs / "clip_00001.png").write_bytes(b"not-a-real-png")
    records = [make_record(1, "leftArm", "torso", 12.0, visible="yes", visible_ratio=0.5)]
    out = tmp_path / "sheet.html"
    n = write_contact_sheet(records, thumbs, out)
    html = out.read_text(encoding="utf-8")
    assert n == 1
    assert "clip_00001.png" in html
    assert "leftArm" in html and "12.0 mm" in html
