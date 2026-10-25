# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json

import pytest

from mmd_retarget.canonical import (
    build_canonical,
    detect_contacts,
    load_canonical,
    qmul,
    qrot,
    qslerp,
    sample_keys,
    save_canonical,
)
from mmd_retarget.vmd import BoneFrame, MorphFrame, Vmd


def profile() -> dict:
    return {
        "model": "Src",
        "map": {
            "root": "センター",
            "spine": "上半身",
            "leftUpperArm": "左腕",
            "leftFoot": "左足",
        },
        "rest": {
            "センター": {"head": [0, 0, 0], "parent": None},
            "上半身": {"head": [0, 5, 0], "parent": "センター"},
            "左腕": {"head": [1, 5, 0], "parent": "上半身"},
            "左足": {"head": [0, 1, 0], "parent": "センター"},
        },
        "morphs": ["まばたき"],
    }


def make_vmd() -> Vmd:
    # 故意乱序 + 重复帧：frame 10 出现两次，后者应胜出。
    return Vmd(
        model_name="Src",
        bone_frames=[
            BoneFrame("センター", 10, (0, 0, 0), (0, 0, 0, 1)),
            BoneFrame("センター", 0, (0, 0, 0), (0, 0, 0, 1)),
            BoneFrame("上半身", 5, (0, 0, 0), (0, 0.0871557, 0, 0.9961947)),
            BoneFrame("上半身", 10, (0, 0, 0), (0, 0.1736482, 0, 0.9848078)),
            BoneFrame("左腕", 10, (0, 0, 0), (0.1, 0, 0, 0.9949874)),
            BoneFrame("謎骨", 10, (0, 0, 0), (0, 0, 0.1, 0.9949874)),
            BoneFrame("左足", 10, (0.5, 0, 0), (0, 0, 0, 1)),
            BoneFrame("センター", 10, (0, 1.5, 0), (0.05, 0, 0, 0.9987492)),
        ],
        morph_frames=[MorphFrame("まばたき", 10, 1.0), MorphFrame("まばたき", 0, 0.0)],
    )


def test_split_and_dedup():
    c = build_canonical(make_vmd(), profile(), detect=False)
    assert c["fps"] == 30
    assert c["frames"] == 11
    # 重复帧保留最后一个
    assert c["joints"]["spine"][-1][0] == 10
    assert c["joints"]["spine"][-1][4] == pytest.approx(0.9848078)
    # 有位移的骨保留全部位置键（包括 0）
    assert [k[0] for k in c["root"]["pos"]] == [0.0, 10.0]
    assert c["root"]["pos"][-1][1:] == pytest.approx([0.0, 1.5, 0.0])
    assert c["translations"]["leftFoot"][0][1:] == pytest.approx([0.5, 0.0, 0.0])
    # 没有语义映射的骨进入 extra
    assert "謎骨" in c["extra"]
    assert "謎骨" not in c["joints"]
    assert c["meta"]["joints"] == 3
    assert c["meta"]["extra_bones"] == 1
    assert c["morphs"]["まばたき"] == [[0.0, 0.0], [10.0, 1.0]]


def test_save_and_load(tmp_path):
    c = build_canonical(make_vmd(), profile(), detect=False)
    path = tmp_path / "motion.json"
    save_canonical(c, path)
    assert load_canonical(path) == c
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == 1


def test_quaternion_helpers():
    q = (0.0, 0.0, 0.7071068, 0.7071068)  # 绕 Z 90°
    assert qrot(q, (1.0, 0.0, 0.0)) == pytest.approx((0.0, 1.0, 0.0), abs=1e-6)
    assert qmul(q, q) == pytest.approx((0.0, 0.0, 1.0, 0.0), abs=1e-6)
    assert qslerp((0, 0, 0, 1), q, 0.0) == pytest.approx((0, 0, 0, 1))
    assert qslerp((0, 0, 0, 1), q, 1.0) == pytest.approx(q)


def test_sample_keys_holds_ends():
    keys = [[10.0, 0.0], [20.0, 2.0]]
    assert sample_keys(keys, 0, quat=False) == (0.0,)
    assert sample_keys(keys, 25, quat=False) == (2.0,)
    assert sample_keys(keys, 15, quat=False) == pytest.approx((1.0,))


def contact_profile() -> dict:
    return {
        "model": "FootTest",
        "map": {"root": "センター", "leftFoot": "左足"},
        "rest": {
            "センター": {"head": [0, 0, 0], "parent": None},
            "左足": {"head": [0, 1, 0], "parent": "センター"},
        },
    }


def contact_vmd() -> Vmd:
    # 0–10 贴地，11–20 抬起 2 单位，21–30 回到地面。
    frames = []
    for f, y in [(0, 0.0), (10, 0.0), (11, 2.0), (20, 2.0), (21, 0.0), (30, 0.0)]:
        frames.append(BoneFrame("センター", f, (0.0, y, 0.0), (0, 0, 0, 1)))
    return Vmd(bone_frames=frames)


def test_contact_detection_height_only():
    c = build_canonical(contact_vmd(), contact_profile())
    contacts = c["contacts"]
    assert contacts, "should detect ground phases"
    assert all(x["effector"] == "leftFoot" for x in contacts)
    covered = {f for x in contacts for f in range(x["start"], x["end"] + 1)}
    assert 0 in covered and 30 in covered
    assert 15 not in covered
    assert contacts[0]["mean_slide"] >= 0.0


def test_contact_config_is_recorded():
    c = build_canonical(contact_vmd(), contact_profile(), contact_config={"min_frames": 2})
    assert c["meta"]["contact_config"]["min_frames"] == 2


def test_no_profile_feet_returns_no_contacts():
    p = contact_profile()
    p["map"].pop("leftFoot")
    assert detect_contacts(p, {}, {}, {"pos": [], "rot": []}, 10) == []


def test_contacts_prefer_foot_ik_target():
    """腿由 IK 驱动时，必须用 足IK 的位移，而不是腿骨 FK。"""
    p = {
        "model": "IKTest",
        "map": {"root": "センター", "leftFoot": "左足", "leftFootIK": "左足ＩＫ"},
        "rest": {
            "センター": {"head": [0, 0, 0], "parent": None},
            "左足": {"head": [0, 1, 0], "parent": "センター"},
            "左足ＩＫ": {"head": [0, 1, 0], "parent": "センター"},
        },
    }
    translations = {
        "leftFootIK": [
            [0, 0, 0, 0],
            [10, 0, 0, 0],
            [11, 0, 2, 0],
            [20, 0, 2, 0],
            [21, 0, 0, 0],
            [30, 0, 0, 0],
        ]
    }
    contacts = detect_contacts(p, {}, translations, {"pos": [], "rot": []}, 31)
    assert contacts
    assert all(c["source"] == "foot_ik" for c in contacts)
    covered = {f for c in contacts for f in range(c["start"], c["end"] + 1)}
    assert 0 in covered and 30 in covered and 15 not in covered

def test_root_merges_groove_translation():
    from mmd_retarget.canonical import build_canonical
    from mmd_retarget.vmd import BoneFrame, Vmd

    vmd = Vmd(
        model_name="M",
        bone_frames=[
            BoneFrame("センター", 0, (0.0, 0.0, 0.0), (0, 0, 0, 1)),
            BoneFrame("センター", 10, (0.0, 0.0, 0.5), (0, 0, 0, 1)),
            BoneFrame("グルーブ", 0, (0.0, 1.0, 0.0), (0, 0, 0, 1)),
            BoneFrame("グルーブ", 10, (0.0, 1.0, 0.0), (0, 0, 0, 1)),
        ],
    )
    profile = {"map": {"root": "センター"}, "rest": {}}
    out = build_canonical(vmd, profile, detect=False)
    assert out["root"]["merged_bones"] == ["グルーブ"]
    assert out["root"]["pos"][0][1:] == [0.0, 1.0, 0.0]
    assert out["root"]["pos"][10][1:] == [0.0, 1.0, 0.5]
