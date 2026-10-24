# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import math

import pytest

from mmd_retarget.physics import find_chains, simulate


def _profile():
    rest = {
        "センター": {"head": [0.0, 10.0, 0.0], "parent": None},
        "上半身": {"head": [0.0, 10.0, 0.0], "tail": [0.0, 12.0, 0.0], "parent": "センター"},
        # 水平裙链，方便观察重力下垂
        "Q_0_0": {"head": [0.0, 10.0, 0.0], "tail": [1.0, 10.0, 0.0], "parent": "上半身"},
        "Q_1_0": {"head": [1.0, 10.0, 0.0], "tail": [2.0, 10.0, 0.0], "parent": "Q_0_0"},
        "Q_2_0": {"head": [2.0, 10.0, 0.0], "tail": [3.0, 10.0, 0.0], "parent": "Q_1_0"},
        # 头发链
        "髮_1": {"head": [0.0, 12.0, 0.0], "tail": [0.0, 11.0, 0.0], "parent": "上半身"},
        "髮_2": {"head": [0.0, 11.0, 0.0], "tail": [0.0, 10.0, 0.0], "parent": "髮_1"},
        # 前缀式侧发（左髮_N）
        "左髮_1": {"head": [0.2, 12.0, 0.0], "tail": [0.3, 11.0, 0.0], "parent": "上半身"},
        "左髮_2": {"head": [0.3, 11.0, 0.0], "tail": [0.4, 10.0, 0.0], "parent": "左髮_1"},
    }
    return {
        "model": "synthetic",
        "map": {"root": "センター"},
        "rest": rest,
        "colliders": [
            {
                "bone": "上半身",
                "semantic": "spine",
                "type": "capsule",
                "a": [0.0, 10.0, 0.0],
                "b": [0.0, 12.0, 0.0],
                "radius": 0.3,
            }
        ],
    }


def _motion(frames: int = 12) -> dict:
    return {
        "schema": 1,
        "fps": 30,
        "frames": frames,
        "root": {"pos": [[0, 0.0, 0.0, 0.0]], "rot": []},
        "joints": {},
        "translations": {},
        "extra": {},
        "extra_translations": {},
        "contacts": [],
        "morphs": {},
        "meta": {},
    }


def test_find_chains_skirt_and_hair():
    profile = _profile()
    cfg = {"hair_prefixes": ["髮"]}
    skirt = find_chains(profile, "skirt", cfg)
    hair = find_chains(profile, "hair", cfg)
    assert [c["bones"] for c in skirt] == [["Q_0_0", "Q_1_0", "Q_2_0"]]
    assert [c["bones"] for c in hair] == [["髮_1", "髮_2"], ["左髮_1", "左髮_2"]]


def test_simulation_bakes_extra_keys_and_pins_root():
    profile = _profile()
    out = simulate(
        _motion(12),
        profile,
        config={
            "chains": {"skirt": True, "hair": False},
            "colliders": {"skirt": []},
            "max_step_units": 10.0,
            "max_angle_deg": 180.0,
        },
    )
    for bone in ("Q_0_0", "Q_1_0", "Q_2_0"):
        keys = out["extra"][bone]
        assert len(keys) == 12
        for k in keys:
            assert len(k) == 5
            q = k[1:]
            assert math.sqrt(sum(v * v for v in q)) == pytest.approx(1.0, abs=1e-6)
    stats = out["meta"]["physics"]
    assert stats["enabled"] is True
    assert len(stats["chains"]) == 1


def test_gravity_produces_rotation():
    profile = _profile()
    out = simulate(
        _motion(12),
        profile,
        config={
            "chains": {"skirt": True, "hair": False},
            "colliders": {"skirt": []},
            "max_step_units": 10.0,
            "max_angle_deg": 180.0,
        },
    )
    last = out["extra"]["Q_0_0"][-1][1:]
    # 水平链在重力下下垂，末端骨骼不应还是单位四元数
    assert abs(last[3]) < 0.9999


def test_max_angle_clamp():
    profile = _profile()
    out = simulate(
        _motion(20),
        profile,
        config={
            "chains": {"skirt": True, "hair": False},
            "colliders": {"skirt": []},
            "max_step_units": 10.0,
            "max_angle_deg": 1.0,
        },
    )
    for bone in ("Q_0_0", "Q_1_0", "Q_2_0"):
        keys = out["extra"][bone]
        for a, b in zip(keys, keys[1:]):
            qa, qb = a[1:], b[1:]
            dot = abs(sum(x * y for x, y in zip(qa, qb)))
            angle = math.degrees(2.0 * math.acos(max(-1.0, min(1.0, dot))))
            assert angle <= 1.0 + 1e-3


def test_collision_push_counted():
    profile = _profile()
    # 在裙链下方放一个胶囊，下落时会推挤
    profile["colliders"].append(
        {
            "bone": "上半身",
            "semantic": "spine1",
            "type": "capsule",
            "a": [1.0, 8.5, 0.0],
            "b": [2.0, 8.5, 0.0],
            "radius": 0.6,
        }
    )
    out = simulate(
        _motion(30),
        profile,
        config={
            "chains": {"skirt": True, "hair": False},
            "colliders": {"skirt": ["spine", "spine1"]},
            "max_step_units": 10.0,
            "max_angle_deg": 180.0,
        },
    )
    assert out["meta"]["physics"]["collision_pushes"] > 0
