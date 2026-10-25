# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import math

import pytest

from mmd_retarget.canonical import build_canonical
from mmd_retarget.vmd import BoneFrame, MorphFrame, Vmd, parse_vmd, build_vmd
from mmd_retarget.writer import canonical_to_vmd


def profile() -> dict:
    return {
        "model": "Src",
        "map": {
            "root": "センター",
            "spine": "上半身",
            "leftFoot": "左足",
        },
        "rest": {
            "センター": {"head": [0, 0, 0], "parent": None},
            "上半身": {"head": [0, 5, 0], "parent": "センター"},
            "左足": {"head": [0, 1, 0], "parent": "センター"},
            "謎骨": {"head": [0, 2, 0], "parent": "センター"},
        },
        "morphs": ["まばたき"],
    }


def source_vmd() -> Vmd:
    return Vmd(
        model_name="Src",
        bone_frames=[
            BoneFrame("センター", 0, (0, 0, 0), (0, 0, 0, 1)),
            BoneFrame("センター", 10, (0, 0.5, 0), (0, 0, 0, 1)),
            BoneFrame("上半身", 0, (0, 0, 0), (0, 0, 0, 1)),
            BoneFrame("上半身", 10, (0, 0, 0), (0, 0.1305262, 0, 0.9914449)),
            BoneFrame("左足", 5, (0.2, 0, 0), (0, 0, 0, 1)),
            BoneFrame("謎骨", 7, (0, 0, 0), (0, 0, 0.05, 0.9987492)),
        ],
        morph_frames=[MorphFrame("まばたき", 0, 0.0), MorphFrame("まばたき", 10, 1.0)],
    )


def test_same_profile_roundtrip_is_numerically_exact():
    src = source_vmd()
    c = build_canonical(src, profile(), detect=False)
    out = canonical_to_vmd(c, profile())
    assert len(out.bone_frames) == len(src.bone_frames)
    src_map = {(f.bone, f.frame): f for f in src.bone_frames}
    out_map = {(f.bone, f.frame): f for f in out.bone_frames}
    assert set(src_map) == set(out_map)
    for key, a in src_map.items():
        b = out_map[key]
        assert b.position == pytest.approx(a.position)
        def unit(q):
            n = math.sqrt(sum(v * v for v in q))
            return [v / n for v in q]

        dot = abs(sum(x * y for x, y in zip(unit(a.rotation), unit(b.rotation))))
        assert math.degrees(2 * math.acos(min(1.0, dot))) < 1e-4
    assert [(m.morph, m.frame, m.weight) for m in out.morph_frames] == [
        (m.morph, m.frame, m.weight) for m in src.morph_frames
    ]


def test_target_without_extra_drops_it():
    src = source_vmd()
    c = build_canonical(src, profile(), detect=False)
    target = profile()
    target["rest"].pop("謎骨")
    out = canonical_to_vmd(c, target)
    assert "謎骨" not in out.bones
    assert out.dropped_bones == ["謎骨"]


def test_morph_not_in_target_is_dropped():
    src = source_vmd()
    c = build_canonical(src, profile(), detect=False)
    target = profile()
    target["morphs"] = ["別の表情"]
    out = canonical_to_vmd(c, target)
    assert out.morph_frames == []


def test_output_is_a_valid_vmd():
    src = source_vmd()
    c = build_canonical(src, profile(), detect=False)
    out = canonical_to_vmd(c, profile())
    data = build_vmd(out)
    again = parse_vmd(data)
    assert again.model_name == "Src"
    assert len(again.bone_frames) == len(out.bone_frames)
    assert again.morph_frames == out.morph_frames

def test_morph_map_renames():
    motion = {"morphs": {"まばたき": [[0, 0.0], [10, 1.0]]}}
    prof = {"map": {}, "morphs": ["blink"], "rest": {}}
    vmd = canonical_to_vmd(motion, prof, morph_map={"まばたき": "blink"})
    assert [m.morph for m in vmd.morph_frames] == ["blink", "blink"]


def test_interpolation_preserved():
    custom = bytes([7] + [20] * 63)
    vmd = Vmd(
        model_name="M",
        bone_frames=[
            BoneFrame("センター", 0, (0.0, 0.0, 0.0), (0, 0, 0, 1), custom),
            BoneFrame("センター", 10, (0.0, 0.0, 0.0), (0, 0, 0, 1), custom),
        ],
    )
    prof = {"model": "M", "map": {"root": "センター"}, "rest": {"センター": {"head": [0, 0, 0], "parent": None}}}
    canon = build_canonical(vmd, prof, detect=False)
    assert "センター" in canon["interpolation"]
    out = canonical_to_vmd(canon, prof)
    frames = [f for f in out.bone_frames if f.interpolation == custom]
    assert len(frames) == 2
