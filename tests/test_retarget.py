# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest

from mmd_retarget.retarget import (
    contact_slide_stats,
    height_scale,
    retarget_motion,
)


def make_profiles(factor: float = 1.0):
    def prof(height: float, factor: float) -> dict:
        return {
            "model": "M",
            "map": {
                "root": "センター",
                "leftUpperLeg": "左足",
                "leftLowerLeg": "左ひざ",
                "leftFoot": "左足首",
                "leftFootIK": "左足ＩＫ",
            },
            "rest": {
                "センター": {"head": [0.0, 10.0 * factor, 0.0], "parent": None},
                "左足": {"head": [0.5 * factor, 5.0 * factor, 0.0], "parent": "センター"},
                "左ひざ": {"head": [1.0 * factor, 2.5 * factor, 0.0], "parent": "左足"},
                "左足首": {"head": [0.5 * factor, 0.0, 0.0], "parent": "左ひざ"},
                "左足ＩＫ": {"head": [0.5 * factor, 0.0, 0.0], "parent": "センター"},
            },
        }

    return prof(10, 1.0), prof(10 * factor, factor)


def make_canonical(contact_pos=(0.6, 0.0, 0.0), ik_keys=None) -> dict:
    if ik_keys is None:
        ik_keys = [[0, 0.0, 0.0, 0.0], [10, 0.2, 0.0, 0.0]]
    return {
        "schema": 1,
        "fps": 30,
        "frames": 11,
        "root": {"pos": [[0, 0.0, 0.0, 1.0]], "rot": []},
        "joints": {},
        "translations": {"leftFootIK": ik_keys},
        "extra": {},
        "extra_translations": {},
        "contacts": [
            {"start": 0, "end": 10, "effector": "leftFoot", "pos": list(contact_pos), "mean_slide": 0.5}
        ],
        "morphs": {},
        "meta": {},
    }


def test_height_scale():
    src, tgt = make_profiles(2.0)
    assert height_scale(src, tgt) == pytest.approx(2.0)


def test_scale_root_and_translations():
    src, tgt = make_profiles(2.0)
    out = retarget_motion(make_canonical(), src, tgt, config={"foot_lock": {"enabled": False}})
    assert out["root"]["pos"][0][1:] == pytest.approx([0.0, 0.0, 2.0])
    assert out["translations"]["leftFootIK"][0][1:] == pytest.approx([0.0, 0.0, 0.0])
    assert out["meta"]["retarget"]["scale"] == pytest.approx(2.0)


def test_foot_lock_is_constant_over_segment():
    src, tgt = make_profiles(1.0)
    out = retarget_motion(make_canonical(ik_keys=[[0, 0.0, 0.5, 0.0]]), src, tgt)
    keys = out["translations"]["leftFootIK"]
    in_segment = [k for k in keys if 0 <= k[0] <= 10]
    assert len(in_segment) == 11
    values = {tuple(round(v, 6) for v in k[1:]) for k in in_segment}
    assert len(values) == 1
    assert next(iter(values)) == pytest.approx((0.0, 0.5, 0.0))
    assert out["contacts"][0]["locked_chunks"][0][2] == pytest.approx([0.5, 0.5, 0.0])


def test_foot_lock_eliminates_slide():
    src, tgt = make_profiles(1.0)
    motion = make_canonical(ik_keys=[[0, 0.0, 0.0, 0.0], [10, 0.2, 0.0, 0.0]])
    before = contact_slide_stats(motion, src)
    out = retarget_motion(motion, src, tgt, config={"foot_lock": {"clamp_unreachable": True}})
    after = contact_slide_stats(out, tgt)
    assert before["mean_slide"] > 0.0
    assert after["mean_slide"] == pytest.approx(0.0, abs=1e-9)


def test_high_drift_segment_is_not_locked():
    """源脚在一个窗口内移动太多，说明是迈步，不应硬锁。"""
    src, tgt = make_profiles(1.0)
    motion = make_canonical(ik_keys=[[0, 0.0, 0.0, 0.0], [10, 5.0, 0.0, 0.0]])
    out = retarget_motion(motion, src, tgt)
    assert out["meta"]["retarget"]["locked"] == 0
    assert out["meta"]["retarget"]["skipped_drift"] == 1


def test_unreachable_contact_is_clamped():
    src, tgt = make_profiles(1.0)
    motion = make_canonical(contact_pos=(0.5, 0.0, 30.0), ik_keys=[[0, 0.0, 0.0, 30.0]])
    out = retarget_motion(
        motion, src, tgt, config={"foot_lock": {"clamp_unreachable": True}}
    )
    assert out["meta"]["retarget"]["clamped"] == 1
    locked = out["contacts"][0]["locked_chunks"][0][2]
    hip = tgt["rest"]["左足"]["head"]
    hip = (hip[0], hip[1], hip[2] + 1.0)  # root 的 z 位移
    leg_len = ((0.5 ** 2 + 2.5 ** 2) ** 0.5) * 2
    assert ((locked[0] - hip[0]) ** 2 + (locked[1] - hip[1]) ** 2 + (locked[2] - hip[2]) ** 2) ** 0.5 <= leg_len * 0.99


def test_missing_ik_is_skipped():
    src, tgt = make_profiles(1.0)
    tgt["map"].pop("leftFootIK")
    out = retarget_motion(make_canonical(), src, tgt)
    assert out["meta"]["retarget"]["skipped_no_ik"] == 1
    assert out["meta"]["retarget"]["locked"] == 0


def test_spine_chain_is_distributed():
    from mmd_retarget.canonical import qmul
    from mmd_retarget.retarget import retarget_rotations

    # 30° 绕 Z
    q = (0.0, 0.0, 0.2588190451, 0.9659258263)
    joints = {"spine": [[0, *q]]}
    target = {"map": {"spine": "上半身", "spine1": "上半身1", "spine2": "上半身2"}}
    out, split = retarget_rotations(joints, target)
    assert split == ["spine", "spine1", "spine2"]
    assert len(out["spine1"]) == 1
    # 每段 10°，复合回 30°
    total = (0.0, 0.0, 0.0, 1.0)
    for name in ("spine", "spine1", "spine2"):
        total = qmul(total, tuple(out[name][0][1:]))
    assert abs(total[2] - q[2]) < 1e-6 and abs(total[3] - q[3]) < 1e-6


def test_spine_split_only_extends_missing_tail():
    from mmd_retarget.retarget import retarget_rotations

    q1 = (0.0, 0.0, 0.1, 0.9949874)
    joints = {"spine": [[0, 0, 0, 0.2588, 0.9659]], "spine1": [[0, *q1]]}
    target = {"map": {"spine": "上半身", "spine1": "上半身1", "spine2": "上半身2"}}
    out, split = retarget_rotations(joints, target)
    assert out["spine"] == joints["spine"]  # 不拆已有完整前缀
    assert split == ["spine1", "spine2"]


def test_rotation_passthrough_without_target_chain():
    from mmd_retarget.retarget import retarget_rotations

    joints = {"leftUpperArm": [[0, 0.1, 0.2, 0.3, 0.9]]}
    out, split = retarget_rotations(joints, {"map": {"leftUpperArm": "左腕"}})
    assert out == joints and split == []


def test_smooth_series_limits_step():
    from mmd_retarget.retarget import smooth_series

    vals = [(0.0, 0.0, 0.0)] * 10 + [(1.0, 0.0, 0.0)] * 10
    out = smooth_series(vals, window=1, max_rate=0.2)
    max_step = max(((out[i][0] - out[i - 1][0]) ** 2) ** 0.5 for i in range(1, len(out)))
    assert max_step <= 0.2 + 1e-9
    # 首尾仍然收敛到原值
    assert out[0] == pytest.approx((0.0, 0.0, 0.0))
    assert out[-1] == pytest.approx((1.0, 0.0, 0.0))


def test_foot_lock_smoothing_reduces_jump():
    from mmd_retarget.retarget import smooth_foot_lock

    motion = {
        "frames": 41,
        "contacts": [
            {"start": 0, "end": 10, "effector": "leftFoot", "locked_chunks": [[0, 10, [0, 0, 0]]]},
            {"start": 11, "end": 30, "effector": "leftFoot", "locked_chunks": [[11, 30, [2, 0, 0]]]},
        ],
        "translations": {
            "leftFootIK": [
                [0, 0.0, 0.0, 0.0],
                [10, 0.0, 0.0, 0.0],
                [11, 2.0, 0.0, 0.0],
                [30, 2.0, 0.0, 0.0],
                [31, 0.0, 0.0, 0.0],
                [40, 0.0, 0.0, 0.0],
            ]
        },
    }
    profile = {"map": {"leftFootIK": "左足ＩＫ"}, "rest": {"左足ＩＫ": {"head": [0, 0, 0]}}}
    stats = smooth_foot_lock(motion, profile, {"smoothing": {"window": 1, "max_rate_m_per_frame": 0.01}})
    assert stats["series"] == 1
    assert stats["max_after"] < stats["max_before"]
    assert stats["max_after"] <= 0.13 + 1e-6
