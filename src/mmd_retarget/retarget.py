# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""M1 第一层：比例缩放 + rest-relative 骨架映射 + 脚锁。

范围（M1 stage 1）
------------------
- 用身高比例把 root / IK 位移缩放到目标骨架；
- 语义骨按名字重映射，旋转先原样传递（rest-relative 世界增量在下一层）；
- 脚锁：把接触段内的 `足IK` 目标钉在段平均位置，消除滑步；
- 可达性检查：髋到脚目标超过腿长时向髋部收，避免 IK 拉断。

未做：手臂 IK、间隙约束、时间平滑、脊柱链拆分。这些在 M1 stage 2/3。
"""
from __future__ import annotations

import copy
import math
from typing import Any

from .canonical import forward_positions, sample_keys

__all__ = [
    "DEFAULT_CONFIG",
    "height_scale",
    "retarget_motion",
    "contact_slide_stats",
]

DEFAULT_CONFIG: dict[str, Any] = {
    "scale": {"mode": "height"},
    "foot_lock": {
        "enabled": True,
        # 腿长保留 2% 余量，避免完全伸直导致 IK 抖动。
        "reach_margin": 0.02,
        # 默认不硬拉：够不到就跳过并报告，交给人工/下一层骨盆补偿。
        "clamp_unreachable": False,
        # 单个锁定窗口内允许的源脚漂移；超过则判为“迈步”不锁。
        "max_lock_drift_m": 0.04,
        "chunk_frames": 20,
        # 粗略的人体身高，用于米制阈值换算。
        "assumed_height_m": 1.6,
    },
}


def _deep_merge(base: dict, override: dict | None) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _model_height(profile: dict) -> float:
    ys = [v["head"][1] for v in profile.get("rest", {}).values()]
    return max(ys) if ys else 20.0


def height_scale(source: dict, target: dict) -> float:
    """目标身高 / 源身高。MMD 的 1 单位比例大致等价于体型比例。"""
    hs = _model_height(source)
    ht = _model_height(target)
    if hs <= 1e-9:
        return 1.0
    return ht / hs


def _scale_keys(keys: list[list[float]], scale: float) -> list[list[float]]:
    return [[k[0], k[1] * scale, k[2] * scale, k[3] * scale] for k in keys]


def _upsert_translation(
    keys: list[list[float]], start: int, end: int, value: tuple[float, float, float]
) -> list[list[float]]:
    """把 [start, end] 内的位移键替换为常量 value（逐帧写入）。

    段外的键保留；段边界会与相邻键形成线性过渡，M1 的平滑层会再处理。
    """
    kept = [k for k in keys if k[0] < start or k[0] > end]
    dense = [[float(f), value[0], value[1], value[2]] for f in range(start, end + 1)]
    return sorted(kept + dense, key=lambda k: k[0])


def _leg_geometry(profile: dict, side: str) -> tuple[float, tuple[float, float, float]] | None:
    """返回 (腿长, 髋关节 rest head)。"""
    mapping = profile.get("map", {})
    rest = profile.get("rest", {})
    upper = mapping.get(f"{side}UpperLeg")
    lower = mapping.get(f"{side}LowerLeg")
    foot = mapping.get(f"{side}Foot")
    if not (upper and lower and foot and all(b in rest for b in (upper, lower, foot))):
        return None
    hip = tuple(rest[upper]["head"])
    knee = tuple(rest[lower]["head"])
    ankle = tuple(rest[foot]["head"])
    length = math.dist(hip, knee) + math.dist(knee, ankle)
    return length, hip  # type: ignore[return-value]


def _clamp_to_reach(
    pos: tuple[float, float, float], hip: tuple[float, float, float], max_len: float
) -> tuple[float, float, float]:
    d = math.dist(hip, pos)
    if d <= max_len or d <= 1e-9:
        return pos
    k = max_len / d
    return (
        hip[0] + (pos[0] - hip[0]) * k,
        hip[1] + (pos[1] - hip[1]) * k,
        hip[2] + (pos[2] - hip[2]) * k,
    )


def retarget_motion(
    canonical: dict,
    source: dict,
    target: dict,
    *,
    config: dict | None = None,
) -> dict:
    """返回一份新的 canonical（已按目标骨架缩放并锁脚）。"""
    cfg = _deep_merge(DEFAULT_CONFIG, config)
    out = copy.deepcopy(canonical)
    scale = height_scale(source, target)
    s_mapping = source.get("map", {})
    t_mapping = target.get("map", {})
    s_rest = source.get("rest", {})
    t_rest = target.get("rest", {})

    # root / IK / 其它位移统一缩放
    if out.get("root", {}).get("pos"):
        out["root"]["pos"] = _scale_keys(out["root"]["pos"], scale)
    for name, keys in list(out.get("translations", {}).items()):
        out["translations"][name] = _scale_keys(keys, scale)
    for name, keys in list(out.get("extra_translations", {}).items()):
        out["extra_translations"][name] = _scale_keys(keys, scale)

    stats = {
        "scale": round(scale, 6),
        "source_height": round(_model_height(source), 6),
        "target_height": round(_model_height(target), 6),
        "contacts": 0,
        "chunks": 0,
        "locked": 0,
        "locked_frames": 0,
        "locked_coverage": 0.0,
        "clamped": 0,
        "skipped_no_ik": 0,
        "skipped_drift": 0,
        "skipped_reach": 0,
        "max_reach_ratio": 0.0,
    }

    if not cfg["foot_lock"].get("enabled", True):
        out["meta"]["retarget"] = stats
        return out

    fl = cfg["foot_lock"]
    margin = float(fl.get("reach_margin", 0.02))
    clamp = bool(fl.get("clamp_unreachable", True))
    chunk_frames = max(1, int(fl.get("chunk_frames", 20)))
    assumed_h = float(fl.get("assumed_height_m", 1.6))
    target_height = stats["target_height"] or assumed_h
    max_drift_units = float(fl.get("max_lock_drift_m", 0.04)) * target_height / assumed_h

    geometry = {
        "leftFoot": _leg_geometry(target, "left"),
        "rightFoot": _leg_geometry(target, "right"),
    }
    # 髋关节随 root / 旋转运动；可达性必须用每帧的髋位置，而不是 rest。
    hip_bones = {}
    for side in ("left", "right"):
        bone = t_mapping.get(f"{side}UpperLeg")
        if bone and bone in t_rest:
            hip_bones[side] = bone
    hips = forward_positions(
        target,
        out.get("joints", {}),
        out.get("translations", {}),
        out.get("root", {}),
        int(out.get("frames", 0)),
        list(hip_bones.values()),
    )

    for contact in out.get("contacts", []):
        stats["contacts"] += 1
        effector = contact.get("effector", "")
        side = "left" if effector == "leftFoot" else "right"
        ik_sem = "leftFootIK" if side == "left" else "rightFootIK"
        s_ik_bone = s_mapping.get(ik_sem)
        t_ik_bone = t_mapping.get(ik_sem)
        if not (s_ik_bone and t_ik_bone and s_ik_bone in s_rest and t_ik_bone in t_rest):
            stats["skipped_no_ik"] += 1
            continue
        keys = out.get("translations", {}).get(ik_sem)
        if not keys:
            stats["skipped_no_ik"] += 1
            continue

        t_head = t_rest[t_ik_bone]["head"]
        hip_bone = hip_bones.get(side)
        hip_series = hips.get(hip_bone, []) if hip_bone else []
        geo = geometry.get(effector)
        locked_chunks = []

        for chunk_start in range(int(contact["start"]), int(contact["end"]) + 1, chunk_frames):
            chunk_end = min(int(contact["end"]), chunk_start + chunk_frames - 1)
            pts = []
            for f in range(chunk_start, chunk_end + 1):
                tx, ty, tz = _sample(keys, f)
                pts.append((t_head[0] + tx, t_head[1] + ty, t_head[2] + tz))
            mean = tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))
            drift = max(math.dist(p, mean) for p in pts)
            stats["chunks"] += 1
            if drift > max_drift_units:
                stats["skipped_drift"] += 1
                continue

            locked = mean
            if geo and hip_series:
                leg_len, _ = geo
                hip_mean = tuple(
                    sum(hip_series[f][i] for f in range(chunk_start, chunk_end + 1))
                    / (chunk_end - chunk_start + 1)
                    for i in range(3)
                )
                ratio = math.dist(hip_mean, locked) / leg_len if leg_len > 1e-9 else 0.0
                stats["max_reach_ratio"] = max(stats["max_reach_ratio"], ratio)
                if ratio > 1.0 + 1e-9:
                    if clamp:
                        locked = _clamp_to_reach(locked, hip_mean, leg_len * (1.0 - margin))
                        stats["clamped"] += 1
                    else:
                        stats["skipped_reach"] += 1
                        continue

            translation = (locked[0] - t_head[0], locked[1] - t_head[1], locked[2] - t_head[2])
            keys = _upsert_translation(keys, chunk_start, chunk_end, translation)
            out["translations"][ik_sem] = keys
            locked_chunks.append([chunk_start, chunk_end, [round(v, 6) for v in locked]])
            stats["locked"] += 1

        contact["locked_chunks"] = locked_chunks
        stats["locked_frames"] += sum(e - s0 + 1 for s0, e, _ in locked_chunks)

    stats["locked_coverage"] = (
        stats["locked_frames"] / (int(out.get("frames", 0)) * 2)
        if out.get("frames")
        else 0.0
    )

    out["meta"]["retarget"] = stats
    return out


def contact_slide_stats(motion: dict, profile: dict) -> dict:
    """从 canonical 的足 IK 位移重建接触段滑步。

    返回 ``{"segments": n, "mean_slide": x, "max_slide": y, "coverage": z}``。
    没有 IK 数据时退回 contact 里已有的统计。
    """
    mapping = profile.get("map", {})
    rest = profile.get("rest", {})
    translations = motion.get("translations", {})
    frames = int(motion.get("frames", 0))
    slides: list[float] = []
    drifts: list[float] = []
    covered = 0

    for c in motion.get("contacts", []):
        effector = c.get("effector", "")
        ik_sem = "leftFootIK" if effector == "leftFoot" else "rightFootIK"
        ik_bone = mapping.get(ik_sem)
        keys = translations.get(ik_sem)
        if not (ik_bone in rest and keys):
            slides.append(c.get("mean_slide", 0.0))
            drifts.append(c.get("mean_slide", 0.0) * (int(c["end"]) - int(c["start"]) + 1))
            covered += int(c["end"]) - int(c["start"]) + 1
            continue
        head = rest[ik_bone]["head"]
        pts = []
        for f in range(int(c["start"]), int(c["end"]) + 1):
            x, y, z = _sample(keys, f)
            pts.append((head[0] + x, head[1] + y, head[2] + z))
        seg = [math.dist(pts[i], pts[i - 1]) for i in range(1, len(pts))]
        if seg:
            slides.append(sum(seg) / len(seg))
        mean = tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))
        drifts.append(max(math.dist(p, mean) for p in pts))
        covered += len(pts)

    return {
        "segments": len(motion.get("contacts", [])),
        "mean_slide": sum(slides) / len(slides) if slides else 0.0,
        "max_slide": max(slides) if slides else 0.0,
        "mean_drift": sum(drifts) / len(drifts) if drifts else 0.0,
        "max_drift": max(drifts) if drifts else 0.0,
        "coverage": covered / (frames * 2) if frames else 0.0,
    }


def _sample(keys: list[list[float]], frame: int) -> tuple[float, float, float]:
    return sample_keys(keys, frame, quat=False)  # type: ignore[return-value]
