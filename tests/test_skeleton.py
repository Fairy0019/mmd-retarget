# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json

import pytest

from mmd_retarget.pmx import Pmx, PmxBone
from mmd_retarget.skeleton import (
    SEMANTIC_SPECS,
    build_profile,
    load_profile,
    mapped_for_bones,
    write_profile,
)


def bone(
    index: int,
    name: str,
    head: tuple[float, float, float],
    parent: int = -1,
    *,
    tail: tuple[float, float, float] | None = None,
    flags: int = 0x001E,
    ik_links: tuple = (),
) -> PmxBone:
    tail = tail or (head[0], head[1] + 1.0, head[2])
    return PmxBone(
        index=index,
        name=name,
        name_en=name,
        head=head,
        tail=tail,
        parent=parent,
        layer=0,
        flags=flags,
        ik_links=ik_links,
    )


def make_pmx() -> Pmx:
    bones = [
        bone(0, "センター", (0.0, 10.0, 0.0), tail=(0.0, 11.0, 0.0)),
        bone(1, "上半身", (0.0, 12.0, 0.0), 0, tail=(0.0, 13.0, 0.0)),
        bone(2, "上半身1", (0.0, 13.0, 0.0), 1, tail=(0.0, 14.0, 0.0)),
        bone(3, "上半身2", (0.0, 14.0, 0.0), 2, tail=(0.0, 15.5, 0.0)),
        bone(4, "首", (0.0, 15.5, 0.0), 3, tail=(0.0, 16.0, 0.0)),
        bone(5, "頭", (0.0, 16.0, 0.0), 4, tail=(0.0, 17.5, 0.0)),
        bone(6, "左肩", (0.1, 15.0, 0.0), 3, tail=(1.0, 14.8, 0.0)),
        bone(7, "左腕", (1.0, 14.8, 0.0), 6, tail=(3.0, 13.5, 0.0)),
        bone(8, "左ひじ", (3.0, 13.5, 0.0), 7, tail=(5.0, 12.5, 0.0)),
        bone(9, "左手首", (5.0, 12.5, 0.0), 8, tail=(5.5, 12.2, 0.0)),
        bone(10, "左足", (1.0, 10.0, 0.0), 0, tail=(1.0, 5.0, 0.0)),
        bone(11, "左ひざ", (1.0, 5.0, 0.0), 10, tail=(1.0, 1.0, 0.0)),
        bone(12, "左足首", (1.0, 1.0, 0.0), 11, tail=(1.0, 0.2, 0.0)),
        bone(13, "左足D", (1.0, 10.0, 0.0), 0, tail=(1.0, 10.0, 0.0)),
        bone(
            14,
            "左足ＩＫ",
            (1.0, 1.0, 0.0),
            0,
            flags=0x003F,
            tail=(1.0, 1.0, 0.0),
            ik_links=((11, True, (-3.14, 0.0, 0.0), (-0.01, 0.0, 0.0)),),
        ),
        bone(15, "両目", (0.0, 16.5, 0.0), 5, tail=(0.0, 16.5, 1.0)),
        bone(16, "右腕", (-1.0, 14.8, 0.0), 6, tail=(-3.0, 13.5, 0.0)),
        bone(17, "腕.L", (1.0, 14.8, 0.0), 6, tail=(3.0, 13.5, 0.0)),
    ]
    pmx = Pmx(name="TestModel", name_en="Test", path="test.pmx", version=2.0)
    pmx.bones = bones
    # 上半身没有直接权重（真实模型常见），上半身1/2 有。
    pmx.bone_vertex_count = {1: 5, 2: 100, 3: 500, 5: 300, 7: 50, 8: 80, 10: 0, 13: 200}
    pmx.bone_vertex_bbox = {
        2: ((-0.8, 13.0, -0.5), (0.8, 14.0, 0.5)),
        3: ((-1.0, 14.0, -0.6), (1.0, 15.4, 0.6)),
        5: ((-0.9, 16.0, -0.8), (0.9, 17.4, 0.8)),
        7: ((-0.3, 14.5, -0.3), (0.3, 15.0, 0.3)),
        8: ((-0.2, 13.2, -0.2), (0.2, 13.8, 0.2)),
        13: ((-0.7, 5.0, -0.7), (0.7, 10.0, 0.7)),
    }
    return pmx


def test_mapping_prefers_standard_names():
    p = build_profile(make_pmx())
    assert p["map"]["root"] == "センター"
    assert p["map"]["spine2"] == "上半身2"
    assert p["map"]["leftUpperArm"] == "左腕"
    assert p["map"]["leftFootIK"] == "左足ＩＫ"
    assert p["map"]["bothEyes"] == "両目"


def test_missing_semantics_are_reported():
    p = build_profile(make_pmx())
    assert "rightUpperLeg" in p["map_missing"]
    assert p["stats"]["mapped"] == len(p["map"])
    assert 0.0 < p["stats"]["map_coverage"] <= 1.0


def test_rest_and_parent_names():
    p = build_profile(make_pmx())
    assert p["rest"]["左ひざ"]["parent"] == "左足"
    assert p["rest"]["センター"]["parent"] is None
    assert p["rest"]["左腕"]["head"] == [1.0, 14.8, 0.0]
    assert p["rest"]["左腕"]["roll"] == 0.0


def test_ik_limits():
    p = build_profile(make_pmx())
    assert p["limits"]["左ひざ"]["min"] == pytest.approx([-3.14, 0.0, 0.0])
    assert p["limits"]["左ひざ"]["max"] == pytest.approx([-0.01, 0.0, 0.0])
    assert p["limits"]["左ひざ"]["source"] == "ik_link"


def test_colliders_use_d_bone_fallback_for_legs():
    p = build_profile(make_pmx())
    legs = {c["semantic"]: c for c in p["colliders"]}
    assert "leftUpperLeg" in legs
    # 左足 本身没有权重，半径来自 左足D
    assert legs["leftUpperLeg"]["radius"] > 0
    assert legs["leftUpperLeg"]["a"] == pytest.approx([1.0, 10.0, 0.0])


def test_colliders_skip_bones_without_enough_vertices():
    p = build_profile(make_pmx())
    assert all(c["semantic"] != "leftHand" for c in p["colliders"])


def test_write_and_load_profile(tmp_path):
    path = tmp_path / "profile.json"
    written = write_profile(make_pmx(), path)
    loaded = load_profile(path)
    assert loaded == written
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == 1


def test_mapped_for_bones():
    p = build_profile(make_pmx())
    stats = mapped_for_bones(
        p, ["センター", "上半身", "左腕", "左ひじ", "謎ボーン", "左足D"]
    )
    assert stats["total"] == 6
    assert stats["mapped"] == 5  # 左足D 通过 leftUpperLegD 映射
    assert "謎ボーン" in stats["unmapped"]


def test_semantic_specs_are_unique_per_side():
    # 左右不能映射到同一个骨名
    p = build_profile(make_pmx())
    values = list(p["map"].values())
    assert len(values) == len(set(values))
    assert set(SEMANTIC_SPECS) >= {"leftUpperArm", "rightUpperArm", "leftFoot", "rightFoot"}
