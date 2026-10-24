# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json

from mmd_retarget.parts import (
    classify_bone,
    classify_material,
    load_rules,
    outside_is_bad,
    part_pairs,
)


def test_default_classification():
    rules = load_rules()
    assert classify_bone("左腕", rules) == "leftArm"
    assert classify_bone("右ひざ", rules) == "rightLeg"
    assert classify_bone("左足ＩＫ", rules) == "leftLeg"
    assert classify_bone("上半身2", rules) == "torso"
    assert classify_bone("センター", rules) == "torso"
    assert classify_bone("髮_1", rules) is None
    assert classify_material("裙", rules) == "skirt"
    assert classify_material("裙内", rules) is None
    assert classify_material("髮", rules) == "hair"
    assert classify_material("翼", rules) == "wings"
    assert ("leftArm", "torso") in part_pairs(rules)
    assert ("leftLeg", "skirt") in outside_is_bad(rules)


def test_custom_rules_override(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            {
                "material": {"skirt": ["dress"]},
                "limb_groups": {"Wing": ["wing"]},
                "pairs": [["leftWing", "torso"]],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rules = load_rules(path)
    assert classify_material("dress_a", rules) == "skirt"
    assert classify_material("裙", rules) is None  # 列表被整体替换
    assert classify_bone("左wing01", rules) == "leftWing"
    assert part_pairs(rules) == [("leftWing", "torso")]
    # 未覆盖的字段保留默认值
    assert classify_bone("上半身", rules) == "torso"

def test_suffix_bone_names():
    """本项目模型用 .L/.R 后缀，规则要同时支持前缀和后缀。"""
    rules = load_rules()
    assert classify_bone("腕.L", rules) == "leftArm"
    assert classify_bone("ひじ.R", rules) == "rightArm"
    assert classify_bone("足.L", rules) == "leftLeg"
    assert classify_bone("ひざ.R", rules) == "rightLeg"
    assert classify_bone("上半身1", rules) == "torso"
