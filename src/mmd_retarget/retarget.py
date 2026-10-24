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

from .canonical import forward_positions, forward_rotations, qmul, qrot, qslerp, sample_keys

__all__ = [
    "DEFAULT_CONFIG",
    "SPINE_CHAIN",
    "height_scale",
    "retarget_rotations",
    "retarget_arms",
    "retarget_motion",
    "contact_slide_stats",
]

#: 需要按链长分配的脊柱语义（源模型常常只有 上半身，目标有三段）。
SPINE_CHAIN = ("spine", "spine1", "spine2", "spine3")
_IDENTITY_Q = (0.0, 0.0, 0.0, 1.0)

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
        # 承重判断：窗口内至少多少比例是支撑脚才值得锁。
        "support_ratio": 0.5,
        # 支撑脚允许更大的源漂移（脚锁本来就是要消掉它）。
        "max_support_drift_m": 0.12,
        # 粗略的人体身高，用于米制阈值换算。
        "assumed_height_m": 1.6,
    },
    "arm_ik": {
        "enabled": True,
    },
    "smoothing": {
        # 锚定式：锁定帧是硬约束，只改未锁定段（见报告 09/10）。
        "enabled": True,
        "window": 2,
        "max_rate_m_per_frame": 0.01,
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


def _split_rotation(keys: list[list[float]], n: int) -> list[list[float]]:
    """把一段旋转均分成 n 份（同一轴时乘积严格等于原旋转）。"""
    if n <= 1:
        return keys
    out = []
    for k in keys:
        q = qslerp(_IDENTITY_Q, (k[1], k[2], k[3], k[4]), 1.0 / n)
        out.append([k[0], *q])
    return out


def retarget_rotations(joints: dict, target: dict) -> tuple[dict, list[str]]:
    """局部旋转映射 + 脊柱链拆分。

    MMD 的 VMD 局部旋转已经是「相对 rest」的旋转，同一语义骨直接复制即可；
    唯一需要处理的是**链长差**：源只有 ``上半身``，目标有
    ``上半身/上半身1/上半身2``。把源的局部旋转均分到目标链上，末端世界
    朝向保持不变（同轴时严格相等）。
    """
    out = copy.deepcopy(joints)
    target_map = target.get("map", {})
    chain = [s for s in SPINE_CHAIN if s in target_map]
    split: list[str] = []

    i = 0
    while i < len(chain):
        sem = chain[i]
        if sem not in joints:
            i += 1
            continue
        j = i + 1
        while j < len(chain) and chain[j] not in joints:
            j += 1
        n = j - i
        if n > 1:
            for name in chain[i:j]:
                out[name] = _split_rotation(joints[sem], n)
                split.append(name)
        i = j
    return out, split


def _qinv(q):
    return (-q[0], -q[1], -q[2], q[3])


def _qfrom_to(a, b):
    """最短弧：把单位向量 a 转到 b 的四元数。"""
    d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    if d > 1.0 - 1e-9:
        return _IDENTITY_Q
    if d < -1.0 + 1e-9:
        # 反向：任取一个垂直轴转 180°
        axis = (0.0, 1.0, 0.0) if abs(a[1]) < 0.9 else (1.0, 0.0, 0.0)
        cx = a[1] * axis[2] - a[2] * axis[1]
        cy = a[2] * axis[0] - a[0] * axis[2]
        cz = a[0] * axis[1] - a[1] * axis[0]
        n = math.sqrt(cx * cx + cy * cy + cz * cz) or 1.0
        return (cx / n, cy / n, cz / n, 0.0)
    cx = a[1] * b[2] - a[2] * b[1]
    cy = a[2] * b[0] - a[0] * b[2]
    cz = a[0] * b[1] - a[1] * b[0]
    w = 1.0 + d
    n = math.sqrt(cx * cx + cy * cy + cz * cz + w * w) or 1.0
    return (cx / n, cy / n, cz / n, w / n)


def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def retarget_arms(
    motion: dict, source_motion: dict, source: dict, target: dict, *, scale: float
) -> dict:
    """两骨解析 IK：把源手腕世界轨迹搬到目标手臂。

    只处理 upperArm / lowerArm 两个关节；twist 骨保持 identity，
    hand 的局部旋转沿用源（末端朝向不保证，但不影响手腕位置）。
    """
    frames = int(motion.get("frames", 0))
    smap, tmap = source.get("map", {}), target.get("map", {})
    srest, trest = source.get("rest", {}), target.get("rest", {})
    stats = {
        "sides": 0,
        "reach_clamped": 0,
        "mean_wrist_error": 0.0,
        "max_wrist_error": 0.0,
    }

    # 源动作的腕捩/手捩关键帧会让“上臂-前臂”不再是两段直线；
    # 两骨 IK 解算前先清掉它们，否则手腕会偏几厘米。
    for sem in list(motion.get("joints", {})):
        if "Twist" in sem:
            motion["joints"].pop(sem, None)

    for side in ("left", "right"):
        su, sl, sh = (f"{side}UpperArm", f"{side}LowerArm", f"{side}Hand")
        if not all(k in smap and k in tmap for k in (su, sl, sh)):
            continue
        sbones = [smap[su], smap[sl], smap[sh]]
        t_up, t_low, t_hand = tmap[su], tmap[sl], tmap[sh]
        if not all(b in srest for b in sbones) or not all(b in trest for b in (t_up, t_low, t_hand)):
            continue

        s_pos = forward_positions(
            source,
            source_motion.get("joints", {}),
            source_motion.get("translations", {}),
            source_motion.get("root", {}),
            frames,
            sbones,
        )
        if not s_pos.get(sbones[0]):
            continue
        t_pos = forward_positions(
            target, motion.get("joints", {}), motion.get("translations", {}),
            motion.get("root", {}), frames, [t_up],
        )
        if not t_pos.get(t_up):
            continue
        parent_bone = trest[t_up].get("parent")
        parent_q = (
            forward_rotations(target, motion.get("joints", {}), motion.get("root", {}), frames, [parent_bone]).get(parent_bone, [])
            if parent_bone
            else []
        )

        S0 = tuple(trest[t_up]["head"])
        E0 = tuple(trest[t_low]["head"])
        W0 = tuple(trest[t_hand]["head"])
        L1 = math.dist(S0, E0)
        L2 = math.dist(E0, W0)
        u0 = _norm((E0[0] - S0[0], E0[1] - S0[1], E0[2] - S0[2]))
        v0 = _norm((W0[0] - E0[0], W0[1] - E0[1], W0[2] - E0[2]))

        up_keys, low_keys = [], []
        goals = []
        for f in range(frames):
            Ss, Es, Ws = s_pos[sbones[0]][f], s_pos[sbones[1]][f], s_pos[sbones[2]][f]
            S = t_pos[t_up][f]
            T = (S[0] + (Ws[0] - Ss[0]) * scale,
                 S[1] + (Ws[1] - Ss[1]) * scale,
                 S[2] + (Ws[2] - Ss[2]) * scale)
            goal = T
            vec = (T[0] - S[0], T[1] - S[1], T[2] - S[2])
            d = math.sqrt(sum(x * x for x in vec)) or 1e-9
            max_d = L1 + L2 - 1e-4
            if d > max_d:
                k = max_d / d
                T = (S[0] + vec[0] * k, S[1] + vec[1] * k, S[2] + vec[2] * k)
                vec = (T[0] - S[0], T[1] - S[1], T[2] - S[2])
                d = max_d
                stats["reach_clamped"] += 1
            axis = _norm(vec)
            a = (L1 * L1 - L2 * L2 + d * d) / (2 * d)
            h2 = max(0.0, L1 * L1 - a * a)
            h = math.sqrt(h2)
            base = (S[0] + axis[0] * a, S[1] + axis[1] * a, S[2] + axis[2] * a)

            pole = (Es[0] - Ss[0], Es[1] - Ss[1], Es[2] - Ss[2])
            dot = pole[0] * axis[0] + pole[1] * axis[1] + pole[2] * axis[2]
            perp = (pole[0] - axis[0] * dot, pole[1] - axis[1] * dot, pole[2] - axis[2] * dot)
            if sum(x * x for x in perp) < 1e-9:
                perp = (axis[1] * axis[1] + axis[2] * axis[2], -axis[0] * axis[1], -axis[0] * axis[2])
            perp = _norm(perp)
            E = (base[0] + perp[0] * h, base[1] + perp[1] * h, base[2] + perp[2] * h)

            u1 = _norm((E[0] - S[0], E[1] - S[1], E[2] - S[2]))
            v1 = _norm((T[0] - E[0], T[1] - E[1], T[2] - E[2]))
            pq = parent_q[f] if parent_q else _IDENTITY_Q
            local_u = _qfrom_to(u0, qrot(_qinv(pq), u1))
            world_u = qmul(pq, local_u)
            local_v = _qfrom_to(v0, qrot(_qinv(world_u), v1))
            up_keys.append([float(f), *local_u])
            low_keys.append([float(f), *local_v])
            goals.append(goal)

        motion.setdefault("joints", {})[su] = up_keys
        motion["joints"][sl] = low_keys
        actual = forward_positions(
            target, motion.get("joints", {}), motion.get("translations", {}),
            motion.get("root", {}), frames, [t_hand],
        ).get(t_hand, [])
        errs = [math.dist(actual[f], goals[f]) for f in range(min(len(actual), len(goals)))]
        if errs:
            stats["mean_wrist_error"] = max(stats["mean_wrist_error"], sum(errs) / len(errs))
            stats["max_wrist_error"] = max(stats["max_wrist_error"], max(errs))
        stats["sides"] += 1

    return stats


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


def foot_world_positions(
    motion: dict, profile: dict, frames: int
) -> dict[str, list[tuple[float, float, float]]]:
    """每帧脚踝世界坐标：优先足 IK，缺失时回退 FK。"""
    mapping = profile.get("map", {})
    rest = profile.get("rest", {})
    out: dict[str, list[tuple[float, float, float]]] = {}
    for eff, ik_sem in (("leftFoot", "leftFootIK"), ("rightFoot", "rightFootIK")):
        ik_bone = mapping.get(ik_sem)
        keys = motion.get("translations", {}).get(ik_sem)
        if ik_bone in rest and keys:
            head = rest[ik_bone]["head"]
            out[eff] = [
                (
                    head[0] + sample_keys(keys, f, quat=False)[0],
                    head[1] + sample_keys(keys, f, quat=False)[1],
                    head[2] + sample_keys(keys, f, quat=False)[2],
                )
                for f in range(frames)
            ]
    missing = [e for e in ("leftFoot", "rightFoot") if e not in out]
    if missing:
        targets = [mapping.get(e) for e in missing if mapping.get(e) in rest]
        fk = forward_positions(
            profile, motion.get("joints", {}), motion.get("translations", {}),
            motion.get("root", {}), frames, targets,
        )
        for eff in missing:
            bone = mapping.get(eff)
            if bone in fk:
                out[eff] = fk[bone]
    return out


def support_labels(motion: dict, profile: dict) -> list[str | None]:
    """逐帧判断哪只脚承重。

    规则：

    - 只有一个接触候选 → 就是它；
    - 两个都在接触 → 把骨盆投影到两脚连线上，离投影点近的一侧承重；
    - 两脚几乎重合 → 取更低的那只；
    - 没有候选 → None。

    这是**几何启发式**，不是生物力学承重；它的用途是避免把摆动脚锁死。
    """
    frames = int(motion.get("frames", 0))
    mapping = profile.get("map", {})
    # 优先用下半身；没有就退回 root（骨盆位置近似）。
    hips_bone = mapping.get("hips") or mapping.get("root")
    rest = profile.get("rest", {})
    labels: list[str | None] = [None] * frames
    if hips_bone not in rest:
        return labels

    pelvis = forward_positions(
        profile, motion.get("joints", {}), motion.get("translations", {}),
        motion.get("root", {}), frames, [hips_bone],
    ).get(hips_bone, [])
    feet = foot_world_positions(motion, profile, frames)
    if not feet:
        return labels

    cover: list[list[str]] = [[] for _ in range(frames)]
    for c in motion.get("contacts", []):
        eff = c.get("effector")
        if eff not in ("leftFoot", "rightFoot"):
            continue
        for f in range(max(0, int(c["start"])), min(frames, int(c["end"]) + 1)):
            cover[f].append(eff)

    for f in range(frames):
        cs = cover[f]
        if len(cs) == 1:
            labels[f] = cs[0]
        elif len(cs) >= 2 and "leftFoot" in feet and "rightFoot" in feet:
            L = feet["leftFoot"][f]
            R = feet["rightFoot"][f]
            dx, dz = R[0] - L[0], R[2] - L[2]
            denom = dx * dx + dz * dz
            if denom < 1e-6:
                labels[f] = "leftFoot" if L[1] <= R[1] else "rightFoot"
            else:
                px, pz = pelvis[f][0], pelvis[f][2]
                t = ((px - L[0]) * dx + (pz - L[2]) * dz) / denom
                labels[f] = "leftFoot" if t < 0.5 else "rightFoot"
    return labels


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
    out["joints"], split = retarget_rotations(out.get("joints", {}), target)
    arm_stats = {"enabled": False}
    if cfg.get("arm_ik", {}).get("enabled", True):
        arm_stats = {
            "enabled": True,
            **retarget_arms(out, canonical, source, target, scale=height_scale(source, target)),
        }
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
        "skipped_swing": 0,
        "skipped_reach": 0,
        "max_reach_ratio": 0.0,
        "chain_split": split,
        "arm_ik": arm_stats,
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
    max_support_drift = (
        float(fl.get("max_support_drift_m", 0.12)) * target_height / assumed_h
    )
    support_ratio_min = float(fl.get("support_ratio", 0.5))
    labels = support_labels(out, target)

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
            support = sum(
                1 for f in range(chunk_start, chunk_end + 1) if labels[f] == effector
            )
            support_ratio = support / (chunk_end - chunk_start + 1)
            if support_ratio < support_ratio_min:
                stats["skipped_swing"] += 1
                continue
            limit = max_support_drift if support_ratio >= support_ratio_min else max_drift_units
            if drift > limit:
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
    stats["smoothing"] = smooth_foot_lock(out, target, cfg)
    # 平滑可能放弃一些相邻窗口；覆盖率以最终 contacts 为准。
    stats["locked"] = sum(len(c.get("locked_chunks", [])) for c in out.get("contacts", []))
    stats["locked_frames"] = sum(
        int(e) - int(s) + 1
        for c in out.get("contacts", [])
        for s, e, _ in c.get("locked_chunks", [])
    )
    stats["locked_coverage"] = (
        stats["locked_frames"] / (int(out.get("frames", 0)) * 2)
        if out.get("frames")
        else 0.0
    )
    stats["dropped_smoothing"] = stats["smoothing"].get("dropped_smoothing", 0)

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


def smooth_series(
    values: list[tuple[float, float, float]],
    *,
    window: int = 2,
    max_rate: float | None = None,
) -> list[tuple[float, float, float]]:
    """对三维序列做盒式平均 + 双向限速。

    盒式平均只影响窗口边界；常量段内部保持不变。限速是“每帧最多移动
    ``max_rate``”，用前向 + 后向两遍避免整体滞后。
    """
    if not values:
        return []
    w = max(1, int(window))
    n = len(values)
    out: list[tuple[float, float, float]] = []
    for i in range(n):
        lo = max(0, i - w)
        hi = min(n, i + w + 1)
        k = hi - lo
        out.append(
            (
                sum(values[j][0] for j in range(lo, hi)) / k,
                sum(values[j][1] for j in range(lo, hi)) / k,
                sum(values[j][2] for j in range(lo, hi)) / k,
            )
        )
    if max_rate is not None and max_rate > 0:
        for i in range(1, n):
            out[i] = _limit_step(out[i - 1], out[i], max_rate)
        for i in range(n - 2, -1, -1):
            out[i] = _limit_step(out[i + 1], out[i], max_rate)
    return out


def _limit_step(
    anchor: tuple[float, float, float], point: tuple[float, float, float], max_rate: float
) -> tuple[float, float, float]:
    d = math.dist(anchor, point)
    if d <= max_rate or d <= 1e-12:
        return point
    k = max_rate / d
    return (
        anchor[0] + (point[0] - anchor[0]) * k,
        anchor[1] + (point[1] - anchor[1]) * k,
        anchor[2] + (point[2] - anchor[2]) * k,
    )


def smooth_foot_lock(motion: dict, profile: dict, config: dict) -> dict:
    """锚定式平滑：锁定窗口内**不动**，只在未锁定段做过渡。

    如果某段空隙不够长、无法在限速内完成过渡，就放弃相邻的一个锁定
    窗口，制造更长的空隙。宁可少锁，也不制造跳变。
    """
    cfg = config.get("smoothing", {})
    if not cfg.get("enabled", True):
        return {"enabled": False}

    assumed = float(config.get("foot_lock", {}).get("assumed_height_m", 1.6))
    height = _model_height(profile) or assumed
    max_rate = float(cfg.get("max_rate_m_per_frame", 0.01)) * height / assumed
    merge_tol = float(cfg.get("merge_tolerance_m", 0.02)) * height / assumed

    frames = int(motion.get("frames", 0))
    translations = motion.get("translations", {})
    contacts = motion.get("contacts", [])
    stats = {
        "enabled": True,
        "series": 0,
        "ramped_frames": 0,
        "dropped_smoothing": 0,
        "unresolved_runs": 0,
        "max_before": 0.0,
        "max_after": 0.0,
        "locked_drift": 0.0,
        "rate": round(max_rate, 6),
    }

    def runs(mask: list[bool]):
        out = []
        i = 0
        while i < frames:
            if mask[i]:
                i += 1
                continue
            a = i
            while i < frames and not mask[i]:
                i += 1
            out.append((a, i - 1))
        return out

    rest = profile.get("rest", {})
    mapping = profile.get("map", {})
    for eff, sem in (("leftFoot", "leftFootIK"), ("rightFoot", "rightFootIK")):
        keys = translations.get(sem)
        if not keys:
            continue
        ik_bone = mapping.get(sem)
        if ik_bone not in rest:
            continue
        head = rest[ik_bone]["head"]
        related = [(i, c) for i, c in enumerate(contacts) if c.get("effector") == eff and c.get("locked_chunks")]
        if not related:
            continue

        intervals: list[list] = []
        for ci, c in related:
            for ki, (a, b, pos) in enumerate(c["locked_chunks"]):
                # locked_chunks 存的是世界坐标；translations 存的是相对 rest 的偏移。
                local = (pos[0] - head[0], pos[1] - head[1], pos[2] - head[2])
                intervals.append([int(a), int(b), local, ci, ki])
        intervals.sort(key=lambda v: v[0])

        kept: list[list] = []
        dropped: set[tuple[int, int]] = set()
        for iv in intervals:
            if kept and iv[0] <= kept[-1][1] + 1:
                if math.dist(iv[2], kept[-1][2]) <= merge_tol:
                    kept[-1][1] = max(kept[-1][1], iv[1])
                    dropped.add((iv[3], iv[4]))
                    continue
                dropped.add((iv[3], iv[4]))
                stats["dropped_smoothing"] += 1
                continue
            kept.append(iv)

        if not kept:
            continue

        dense = [sample_keys(keys, f, quat=False) for f in range(frames)]
        before = max((math.dist(dense[i], dense[i - 1]) for i in range(1, frames)), default=0.0)
        original = list(dense)

        # 迭代：空隙不够长就再放弃一个相邻窗口
        for _ in range(30):
            if not kept:
                break
            mask = [False] * frames
            for a, b, _pos, _, _ in kept:
                for fr in range(max(0, a), min(frames, b + 1)):
                    mask[fr] = True
            start_at = {a: pos for a, _b, pos, _, _ in kept}
            end_at = {b: pos for _a, b, pos, _, _ in kept}
            changed = False
            for a, b in runs(mask):
                left = end_at.get(a - 1)
                right = start_at.get(b + 1)
                if left is None and right is None:
                    continue
                if left is not None and right is not None:
                    delta = math.dist(left, right)
                elif left is not None:
                    delta = math.dist(left, original[b])
                else:
                    delta = math.dist(original[a], right)
                need = max(1, math.ceil(delta / max_rate)) if max_rate > 0 else (b - a + 1)
                if b - a + 1 < need:
                    victim = None
                    if right is not None:
                        victim = next((iv for iv in kept if iv[0] == b + 1), None)
                    elif left is not None:
                        victim = next((iv for iv in kept if iv[1] == a - 1), None)
                    if victim is None:
                        break
                    kept.remove(victim)
                    dropped.add((victim[3], victim[4]))
                    stats["dropped_smoothing"] += 1
                    changed = True
                    break
            if not changed:
                break

        if not kept:
            continue

        for ci, c in related:
            c["locked_chunks"] = [
                ch for ki, ch in enumerate(c["locked_chunks"]) if (ci, ki) not in dropped
            ]

        mask = [False] * frames
        for a, b, pos, _, _ in kept:
            for fr in range(max(0, a), min(frames, b + 1)):
                mask[fr] = True
                dense[fr] = pos

        for a, b in runs(mask):
            left = dense[a - 1] if a > 0 and mask[a - 1] else None
            right = dense[b + 1] if b + 1 < frames and mask[b + 1] else None
            n = b - a + 1
            if left is None and right is None:
                continue
            if left is not None and right is not None:
                for i in range(n):
                    t = (i + 1) / (n + 1)
                    dense[a + i] = _lerp3(left, right, t)
            elif left is not None:
                end = original[b]
                for i in range(n):
                    t = (i + 1) / (n + 1)
                    dense[a + i] = _lerp3(left, end, t)
            else:
                start = original[a]
                for i in range(n):
                    t = (i + 1) / (n + 1)
                    dense[a + i] = _lerp3(start, right, t)
            stats["ramped_frames"] += n

        drift = 0.0
        for a, b, pos, _, _ in kept:
            for fr in range(max(0, a), min(frames, b + 1)):
                drift = max(drift, math.dist(dense[fr], pos))
        stats["locked_drift"] = max(stats["locked_drift"], drift)

        after = max((math.dist(dense[i], dense[i - 1]) for i in range(1, frames)), default=0.0)
        translations[sem] = [[float(i), *dense[i]] for i in range(frames)]
        stats["series"] += 1
        stats["max_before"] = max(stats["max_before"], before)
        stats["max_after"] = max(stats["max_after"], after)

    return stats


def _lerp3(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _sample(keys: list[list[float]], frame: int) -> tuple[float, float, float]:
    return sample_keys(keys, frame, quat=False)  # type: ignore[return-value]
