# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""M3 被动件物理：裙 / 发的骨链 PBD。

做法
----
- 骨链（裙 `Q_*`、发 `髮_*` / `Bone_Hair*`）表示成一串质点；
- 链根钉在动画驱动的骨骼 head 上，其余质点做 Verlet 积分；
- 约束：相邻距离（骨长）、胶囊碰撞（腿/躯干/翅膀）、每帧最大步长；
- 最后把质点折线转回骨骼局部旋转，并限制单帧角度变化（防“芭蕾裙”）；
- 结果写进 canonical 的 ``extra``（无语义骨），由 writer 原样写出。

这是**骨链近似**，不是布料：没有褶皱、没有自碰撞。优点是稳定、快、可烘焙。
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any

from .canonical import forward_positions, forward_rotations, qmul, qrot

__all__ = ["DEFAULT_CONFIG", "find_chains", "simulate"]

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "gravity_m_s2": 9.8,
    "damping": 0.985,
    "iterations": 4,
    "substeps": 2,
    "max_step_units": 0.6,
    "max_angle_deg": 12.0,
    "collision_margin_units": 0.0,
    # 用 profile.rest[*].mesh_radius 把“网格比骨头胖”的部分加进碰撞半径。
    "use_mesh_radius": False,
    "mesh_radius_scale": 0.7,
    "skirt_shape_stiffness": 0.0,
    "hair_shape_stiffness": 0.05,
    "chains": {"skirt": False, "hair": True},
    "colliders": {
        "skirt": [
            "hips", "spine", "spine1", "spine2",
            "leftUpperLeg", "rightUpperLeg",
            "leftLowerLeg", "rightLowerLeg",
            "leftFoot", "rightFoot",
        ],
        "hair": [
            "hips", "spine", "spine1", "spine2", "neck", "head",
            "leftShoulder", "rightShoulder",
        ],
    },
    "hair_prefixes": ["髮", "Bone_Hair"],
    "wing_prefixes": ["上翼_", "下翼_"],
    "wing_radius": 0.12,
    "assumed_height_m": 1.6,
}

_IDENTITY = (0.0, 0.0, 0.0, 1.0)
_SKIRT_RE = re.compile(r"^Q_(\d+)_(\d+)$")
_HAIR_RE = re.compile(
    r"^(?P<pre>[左右])?(?P<head>Bone_Hair[A-Za-z]*|髮2?)[_]?(?P<num>\d+)(?P<suf>\.[LR])?$"
)


def _merge(base: dict, override: dict | None) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _model_height(profile: dict) -> float:
    ys = [v["head"][1] for v in profile.get("rest", {}).values()]
    return max(ys) if ys else 20.0


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(v):
    n = math.sqrt(_dot(v, v)) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _q_from_to(a, b):
    a, b = _norm(a), _norm(b)
    d = _dot(a, b)
    if d > 0.999999:
        return _IDENTITY
    if d < -0.999999:
        ref = (0.0, 1.0, 0.0) if abs(a[1]) < 0.9 else (0.0, 0.0, 1.0)
        axis = (
            a[1] * ref[2] - a[2] * ref[1],
            a[2] * ref[0] - a[0] * ref[2],
            a[0] * ref[1] - a[1] * ref[0],
        )
        axis = _norm(axis)
        return (axis[0], axis[1], axis[2], 0.0)
    axis = (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )
    q = (axis[0], axis[1], axis[2], 1.0 + d)
    n = math.sqrt(sum(v * v for v in q)) or 1.0
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def _q_angle(a, b):
    d = abs(sum(x * y for x, y in zip(a, b)))
    return 2.0 * math.acos(max(-1.0, min(1.0, d)))


def _q_slerp(a, b, t):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0.0:
        b = tuple(-v for v in b)
        d = -d
    if d > 0.9995:
        q = tuple(a[i] + (b[i] - a[i]) * t for i in range(4))
        n = math.sqrt(sum(v * v for v in q)) or 1.0
        return tuple(v / n for v in q)
    theta = math.acos(max(-1.0, min(1.0, d)))
    s = math.sin(theta)
    wa = math.sin((1.0 - t) * theta) / s
    wb = math.sin(t * theta) / s
    return tuple(a[i] * wa + b[i] * wb for i in range(4))


def find_chains(profile: dict, kind: str, cfg: dict) -> list[dict]:
    """按名字找出骨链。返回 ``[{key, bones}]``，bones 已按链序排列。"""
    rest = profile.get("rest", {})
    groups: dict[tuple, list[tuple[int, str]]] = {}

    if kind == "skirt":
        for name in rest:
            m = _SKIRT_RE.match(name)
            if m:
                groups.setdefault(("Q", m.group(2)), []).append((int(m.group(1)), name))
    elif kind == "hair":
        prefixes = tuple(cfg.get("hair_prefixes", ()))
        for name in rest:
            m = _HAIR_RE.match(name)
            if not m:
                continue
            head = m.group("head")
            if not any(head.startswith(p) or p in head for p in prefixes):
                continue
            side = m.group("pre") or m.group("suf") or ""
            key = (head, side)
            groups.setdefault(key, []).append((int(m.group("num")), name))
    else:
        return []

    chains = []
    for key, items in groups.items():
        items.sort()
        bones = [name for _n, name in items]
        if len(bones) < 2:
            continue
        chains.append({"key": "/".join(str(k) for k in key), "bones": bones})
    chains.sort(key=lambda c: c["key"])
    return chains


def _capsule_frames(profile, motion, semantic_filter, extra_prefixes=(), extra_radius=0.1):
    """逐帧世界胶囊；来源 = profile.colliders 的语义过滤 + 额外骨链。"""
    rest = profile.get("rest", {})
    frames = int(motion.get("frames", 0))
    joints = motion.get("joints", {})
    trans = motion.get("translations", {})
    root = motion.get("root", {})

    colliders = [
        c for c in profile.get("colliders", [])
        if c.get("semantic") in semantic_filter and c.get("bone") in rest
    ]
    bones = sorted({c["bone"] for c in colliders})
    extra_bones = [
        b for b in rest
        if extra_prefixes and any(b.startswith(p) for p in extra_prefixes)
    ]
    bones += [b for b in sorted(extra_bones) if b not in bones]

    if not bones:
        return [[] for _ in range(frames)]
    pos = forward_positions(profile, joints, trans, root, frames, bones)
    rot = forward_rotations(profile, joints, root, frames, bones)

    out = []
    for f in range(frames):
        caps = []
        for c in colliders:
            bone = c["bone"]
            if not pos.get(bone) or not rot.get(bone):
                continue
            head = rest[bone]["head"]
            q = rot[bone][f]
            p = pos[bone][f]
            off_a = _sub(c["a"], head)
            off_b = _sub(c["b"], head)
            ra, rb = qrot(q, off_a), qrot(q, off_b)
            caps.append((_add(p, ra), _add(p, rb), float(c.get("radius", 0.05))))
        for bone in extra_bones:
            if not pos.get(bone) or not rot.get(bone):
                continue
            head = rest[bone]["head"]
            tail = rest[bone]["tail"]
            p = pos[bone][f]
            q = rot[bone][f]
            ra = qrot(q, _sub(head, head))
            rb = qrot(q, _sub(tail, head))
            caps.append((_add(p, ra), _add(p, rb), extra_radius))
        out.append(caps)
    return out


def _push_out(p, capsules, margin=0.0, extra=0.0):
    x, y, z = p
    for a, b, r in capsules:
        ab = _sub(b, a)
        denom = _dot(ab, ab)
        if denom < 1e-12:
            closest = a
        else:
            t = max(0.0, min(1.0, _dot(_sub((x, y, z), a), ab) / denom))
            closest = _add(a, _mul(ab, t))
        d = math.dist((x, y, z), closest)
        limit = r + margin + extra
        if d < limit and d > 1e-9:
            k = (limit - d) / d
            x += (x - closest[0]) * k
            y += (y - closest[1]) * k
            z += (z - closest[2]) * k
    return (x, y, z)


def _simulate_chain(profile, motion, chain, colliders, cfg, units_per_m, kind="skirt"):
    rest = profile.get("rest", {})
    bones = chain["bones"]
    n = len(bones)
    frames = int(motion.get("frames", 0))
    root_bone = bones[0]
    parent = rest[root_bone].get("parent")

    heads = forward_positions(
        profile, motion.get("joints", {}), motion.get("translations", {}),
        motion.get("root", {}), frames, bones,
    )
    root_pos = heads.get(root_bone)
    if not root_pos:
        return {}, {}
    parent_q = (
        forward_rotations(
            profile, motion.get("joints", {}), motion.get("root", {}), frames, [parent]
        ).get(parent, [])
        if parent and parent in rest else []
    )

    rest_pts = [tuple(rest[b]["head"]) for b in bones] + [tuple(rest[bones[-1]]["tail"])]
    lengths = [math.dist(rest_pts[i], rest_pts[i + 1]) for i in range(n)]

    dt = 1.0 / 30.0 / max(1, int(cfg.get("substeps", 2)))
    g = (0.0, -float(cfg.get("gravity_m_s2", 9.8)) * units_per_m, 0.0)
    damping = float(cfg.get("damping", 0.985))
    iterations = max(1, int(cfg.get("iterations", 4)))
    max_step = float(cfg.get("max_step_units", 0.6))
    max_angle = math.radians(float(cfg.get("max_angle_deg", 12.0)))
    margin = float(cfg.get("collision_margin_units", 0.0))
    stiffness = float(cfg.get(f"{kind}_shape_stiffness", 0.0))
    use_mesh_radius = kind == "skirt" and bool(cfg.get("use_mesh_radius", True))
    mesh_scale = float(cfg.get("mesh_radius_scale", 0.7))
    extra_margins = [
        float(rest[b].get("mesh_radius", 0.0)) * mesh_scale if use_mesh_radius else 0.0
        for b in bones
    ]

    pts = [list(p) for p in rest_pts]
    prev = [list(p) for p in rest_pts]
    prev_local = [None] * n
    keys: dict[str, list[list[float]]] = {b: [] for b in bones}
    max_step_seen = 0.0
    pushes = 0

    for f in range(frames):
        pinned = root_pos[f]
        pts[0] = list(pinned)
        prev[0] = list(pinned)
        pq_frame = parent_q[f] if parent_q else _IDENTITY
        goal = [list(pinned)]
        goal += [_add(pinned, qrot(pq_frame, _sub(rest_pts[i], rest_pts[0]))) for i in range(1, n + 1)]
        for _ in range(max(1, int(cfg.get("substeps", 2)))):
            for i in range(1, n + 1):
                v = _mul(_sub(pts[i], prev[i]), damping)
                prev[i] = list(pts[i])
                pts[i] = _add(_add(pts[i], v), _mul(g, dt * dt))
            for _it in range(iterations):
                pts[0] = list(pinned)
                if stiffness > 0.0:
                    for i in range(1, n + 1):
                        pts[i] = _add(pts[i], _mul(_sub(goal[i], pts[i]), stiffness))
                for i in range(n):
                    delta = _sub(pts[i + 1], pts[i])
                    length = math.sqrt(_dot(delta, delta))
                    if length < 1e-9:
                        continue
                    diff = (length - lengths[i]) / length * 0.5
                    if i > 0:
                        pts[i] = _add(pts[i], _mul(delta, diff))
                    pts[i + 1] = _sub(pts[i + 1], _mul(delta, diff))
                for i in range(1, n + 1):
                    before = pts[i]
                    extra = extra_margins[min(i - 1, n - 1)]
                    pts[i] = _push_out(
                        pts[i], colliders[f] if f < len(colliders) else [], margin, extra
                    )
                    if math.dist(pts[i], before) > 1e-9:
                        pushes += 1
        # 限速
        for i in range(1, n + 1):
            step = math.dist(pts[i], prev[i])
            if step > max_step:
                k = max_step / step
                pts[i] = _add(prev[i], _mul(_sub(pts[i], prev[i]), k))
                step = max_step
            max_step_seen = max(max_step_seen, step)

        pq = parent_q[f] if parent_q else _IDENTITY
        for i, bone in enumerate(bones):
            rest_dir = _norm(_sub(rest_pts[i + 1], rest_pts[i]))
            desired = _norm(_sub(pts[i + 1], pts[i]))
            local = _q_rotate(pq, rest_dir, desired)
            # 单帧角度限制，避免“芭蕾裙”
            if prev_local[i] is not None and _q_angle(prev_local[i], local) > max_angle:
                local = _q_slerp(prev_local[i], local, max_angle / _q_angle(prev_local[i], local))
            prev_local[i] = local
            keys[bone].append([float(f), *local])
            pq = qmul(pq, local)

    stats = {
        "bones": n,
        "frames": frames,
        "max_step_units": round(max_step_seen, 4),
        "collision_pushes": pushes,
    }
    return keys, stats


def _q_rotate(parent_q, rest_dir, desired_dir):
    """把 rest 方向转到父空间，再与目标方向对齐（返回局部旋转）。"""
    local_dir = qrot(_qinv(parent_q), desired_dir)
    return _q_from_to(rest_dir, local_dir)


def _qinv(q):
    return (-q[0], -q[1], -q[2], q[3])


def simulate(motion: dict, profile: dict, *, config: dict | None = None) -> dict:
    cfg = _merge(DEFAULT_CONFIG, config)
    out = copy.deepcopy(motion)
    if not cfg.get("enabled", True):
        return out

    frames = int(out.get("frames", 0))
    units_per_m = _model_height(profile) / float(cfg.get("assumed_height_m", 1.6))
    stats: dict[str, Any] = {"enabled": True, "chains": {}, "collision_pushes": 0}
    extra = out.setdefault("extra", {})

    wants = cfg.get("chains", {})
    if wants.get("skirt", True):
        chains = find_chains(profile, "skirt", cfg)
        caps = _capsule_frames(profile, out, set(cfg["colliders"]["skirt"]))
        for chain in chains:
            keys, st = _simulate_chain(profile, out, chain, caps, cfg, units_per_m, "skirt")
            if keys:
                extra.update(keys)
                stats["chains"][f"skirt:{chain['key']}"] = st
                stats["collision_pushes"] += st["collision_pushes"]

    if wants.get("hair", True):
        chains = find_chains(profile, "hair", cfg)
        caps = _capsule_frames(
            profile, out, set(cfg["colliders"]["hair"]),
            extra_prefixes=tuple(cfg.get("wing_prefixes", ())),
            extra_radius=float(cfg.get("wing_radius", 0.12)),
        )
        for chain in chains:
            keys, st = _simulate_chain(profile, out, chain, caps, cfg, units_per_m, "hair")
            if keys:
                extra.update(keys)
                stats["chains"][f"hair:{chain['key']}"] = st
                stats["collision_pushes"] += st["collision_pushes"]

    out.setdefault("meta", {})["physics"] = stats
    return out
