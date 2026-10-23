# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""canonical motion：与模型解耦的动作表示。

结构（schema = 1）::

    {
      "schema": 1,
      "fps": 30,
      "frames": 5640,
      "source": {"model": "初音ミク", "vmd": "...", "profile": "..."},
      "root": {"pos": [[t,x,y,z], ...], "rot": [[t,x,y,z,w], ...]},
      "joints": {"leftUpperArm": [[t,x,y,z,w], ...], ...},
      "translations": {"leftFootIK": [[t,x,y,z], ...]},
      "extra": {"ﾈｸﾀｲ１": [[t,x,y,z,w], ...]},
      "extra_translations": {"左袖": [[t,x,y,z], ...]},
      "contacts": [{"start": 120, "end": 168, "effector": "leftFoot", ...}],
      "morphs": {"まばたき": [[t, weight], ...]},
      "meta": {...}
    }

设计取舍
--------
- 关键帧**保持稀疏**，不重采样；乱序/重复帧在这里排序去重；
- 语义骨进 ``joints``；没有语义映射的骨进 ``extra`` 原样透传，
  这样同模型 round-trip 不丢物理骨；
- ``root`` 的位置和旋转分开存，因为 VMD 里两者的关键帧时刻经常不同；
- 接触段由「高度 + 速度」在源骨架上做 FK 得到，属于**初值**，
  M1 会用 IK 重新求。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .vmd import Vmd

__all__ = [
    "CANONICAL_SCHEMA",
    "build_canonical",
    "save_canonical",
    "load_canonical",
    "detect_contacts",
    "sample_keys",
    "qmul",
    "qrot",
    "qslerp",
]

CANONICAL_SCHEMA = 1

#: 接触检测的默认阈值（全部相对模型高度，避免不同体型硬编码）。
CONTACT_DEFAULTS = {
    "height_margin": 0.02,  # 高于局部最低点多远以内算“贴地”（×身高）
    "window": 12,  # 局部最低点的半窗口（帧），用来吸收身体上下起伏
    "min_frames": 5,
    "max_gap": 3,
}

_IDENTITY = (0.0, 0.0, 0.0, 1.0)


# ---------------------------------------------------------------------------
# 四元数（纯 Python，避免为几万次采样引入 numpy 依赖）
# ---------------------------------------------------------------------------


def qmul(a: tuple[float, float, float, float], b: tuple[float, float, float, float]):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def qrot(q: tuple[float, float, float, float], v: tuple[float, float, float]):
    """用单位四元数旋转向量。"""
    x, y, z, w = q
    vx, vy, vz = v
    # t = 2 * cross(q.xyz, v)
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def qslerp(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    t: float,
) -> tuple[float, float, float, float]:
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0.0:
        b = (-b[0], -b[1], -b[2], -b[3])
        dot = -dot
    if dot > 0.9995:
        q = tuple(a[i] + (b[i] - a[i]) * t for i in range(4))
    else:
        theta = math.acos(min(1.0, dot))
        sin_theta = math.sin(theta)
        wa = math.sin((1.0 - t) * theta) / sin_theta
        wb = math.sin(t * theta) / sin_theta
        q = tuple(a[i] * wa + b[i] * wb for i in range(4))
    n = math.sqrt(sum(v * v for v in q)) or 1.0
    return tuple(v / n for v in q)  # type: ignore[return-value]


def _lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(len(a)))


# ---------------------------------------------------------------------------
# 关键帧清洗与采样
# ---------------------------------------------------------------------------


def _clean(keys: list, value_len: int) -> list[list[float]]:
    """按帧号排序，重复帧保留最后一个（MMD 的实际行为）。"""
    by_frame: dict[int, list[float]] = {}
    for k in keys:
        by_frame[int(k[0])] = [float(v) for v in k]
    return [by_frame[t] for t in sorted(by_frame)]


def sample_keys(keys: list[list[float]], frame: int, *, quat: bool):
    """在稀疏关键帧上采样。超出范围时保持首/尾姿态。"""
    if not keys:
        return _IDENTITY if quat else (0.0, 0.0, 0.0)
    if frame <= keys[0][0]:
        return tuple(keys[0][1:])
    if frame >= keys[-1][0]:
        return tuple(keys[-1][1:])

    lo, hi = 0, len(keys) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if keys[mid][0] <= frame:
            lo = mid
        else:
            hi = mid
    t0, t1 = int(keys[lo][0]), int(keys[hi][0])
    if t1 == t0:
        return tuple(keys[hi][1:])
    alpha = (frame - t0) / (t1 - t0)
    a = tuple(keys[lo][1:])
    b = tuple(keys[hi][1:])
    if quat:
        return qslerp(a, b, alpha)  # type: ignore[arg-type]
    return _lerp(a, b, alpha)


# ---------------------------------------------------------------------------
# 构建 canonical
# ---------------------------------------------------------------------------


def _reverse_map(profile: dict) -> dict[str, str]:
    return {bone: sem for sem, bone in profile.get("map", {}).items()}


def _split_motion(vmd: Vmd, profile: dict) -> tuple[dict, dict, dict, dict, dict]:
    """把 VMD 拆成 root / joints / extra / translations / extra_translations。"""
    bone_to_sem = _reverse_map(profile)
    root_bone = profile.get("map", {}).get("root", "センター")

    joints: dict[str, list] = {}
    extra: dict[str, list] = {}
    translations: dict[str, list] = {}
    extra_translations: dict[str, list] = {}
    root_rot: list = []
    root_pos: list = []

    # 先找出“有位移”的骨。对这些骨要保留**全部**位置键（包括 0），
    # 否则在 0 → 非 0 之间会被错误地外推成第一个非零值。
    moving_bones = {
        f.bone for f in vmd.bone_frames if any(abs(v) > 1e-6 for v in f.position)
    }

    for frame in vmd.bone_frames:
        t = float(frame.frame)
        if frame.bone == root_bone:
            root_rot.append([t, *frame.rotation])
            if root_bone in moving_bones:
                root_pos.append([t, *frame.position])
            continue

        sem = bone_to_sem.get(frame.bone)
        target = joints if sem else extra
        name = sem or frame.bone
        target.setdefault(name, []).append([t, *frame.rotation])

        if frame.bone in moving_bones:
            # 绝大多数骨的位置恒为 0；只有 IK / 袖等少数骨有位移。
            dest = translations if sem else extra_translations
            dest.setdefault(name, []).append([t, *frame.position])

    joints = {k: _clean(v, 4) for k, v in joints.items()}
    extra = {k: _clean(v, 4) for k, v in extra.items()}
    translations = {k: _clean(v, 3) for k, v in translations.items()}
    extra_translations = {k: _clean(v, 3) for k, v in extra_translations.items()}
    root_rot = _clean(root_rot, 4)
    root_pos = _clean(root_pos, 3)
    return (
        {"pos": root_pos, "rot": root_rot},
        joints,
        extra,
        translations,
        extra_translations,
    )


def _model_height(profile: dict) -> float:
    ys = [v["head"][1] for v in profile.get("rest", {}).values()]
    return max(ys) if ys else 20.0


def _chain_to(profile: dict, bone: str) -> list[str]:
    """从根到指定骨的祖先链（含自身）。"""
    rest = profile.get("rest", {})
    chain: list[str] = []
    seen: set[str] = set()
    current: str | None = bone
    while current and current in rest and current not in seen:
        chain.append(current)
        seen.add(current)
        current = rest[current].get("parent")
    chain.reverse()
    return chain


def forward_positions(
    profile: dict,
    joints: dict,
    translations: dict,
    root: dict,
    frames: int,
    targets: list[str],
) -> dict[str, list[tuple[float, float, float]]]:
    """对指定骨骼做源骨架 FK，返回每帧世界坐标（PMX 坐标系）。

    模型假设：

    - MMD 局部旋转按 ``world_q = parent_q * local_q`` 复合；
    - 骨骼 rest 朝向视为单位矩阵（忽略 roll）；
    - root 的位移在父空间，叠加到 root 的 rest head 上。

    这是 M0/M1 的**近似** FK。它必须定期与 Blender 的真实 pose matrix
    对拍；对不上时以 Blender 为准，本函数只用于纯 Python 的快速预估。
    """
    rest = profile.get("rest", {})
    mapping = profile.get("map", {})
    targets = [t for t in targets if t in rest]
    if not rest or not targets:
        return {t: [] for t in targets}

    order: list[str] = []
    for target in targets:
        for bone in _chain_to(profile, target):
            if bone not in order:
                order.append(bone)

    bone_to_sem = _reverse_map(profile)
    samples: dict[str, list] = {}
    for bone in order:
        sem = bone_to_sem.get(bone)
        keys = joints.get(sem) if sem else None
        if keys is None and bone in joints:
            keys = joints[bone]
        samples[bone] = keys or []

    root_bone = mapping.get("root", "センター")
    root_pos_keys = root.get("pos", [])
    root_rot_keys = root.get("rot", [])
    out: dict[str, list[tuple[float, float, float]]] = {t: [] for t in targets}

    for f in range(frames):
        world_q: dict[str, tuple[float, float, float, float]] = {}
        world_p: dict[str, tuple[float, float, float]] = {}
        for bone in order:
            head = tuple(rest[bone]["head"])
            parent = rest[bone].get("parent")
            local_q = sample_keys(samples[bone], f, quat=True) if samples[bone] else _IDENTITY
            trans = (0.0, 0.0, 0.0)
            if bone == root_bone:
                trans = sample_keys(root_pos_keys, f, quat=False)  # type: ignore[assignment]
                local_q = sample_keys(root_rot_keys, f, quat=True)  # type: ignore[assignment]
            elif bone in translations:
                trans = sample_keys(translations[bone], f, quat=False)  # type: ignore[assignment]

            if parent and parent in world_q:
                pq = world_q[parent]
                pp = world_p[parent]
                delta = (
                    head[0] - rest[parent]["head"][0],
                    head[1] - rest[parent]["head"][1],
                    head[2] - rest[parent]["head"][2],
                )
                rd = qrot(pq, delta)
                rt = qrot(pq, trans)
                world_p[bone] = (pp[0] + rd[0] + rt[0], pp[1] + rd[1] + rt[1], pp[2] + rd[2] + rt[2])
                wq = qmul(pq, local_q)
            else:
                world_p[bone] = (head[0] + trans[0], head[1] + trans[1], head[2] + trans[2])
                wq = local_q
            n = math.sqrt(sum(v * v for v in wq)) or 1.0
            world_q[bone] = (wq[0] / n, wq[1] / n, wq[2] / n, wq[3] / n)

        for target in targets:
            out[target].append(world_p[target])
    return out


def detect_contacts(
    profile: dict,
    joints: dict,
    translations: dict,
    root: dict,
    frames: int,
    *,
    config: dict | None = None,
) -> list[dict]:
    """用源骨架 FK 检测脚部接触段。

    判定只用高度（局部最低点 + 身高比例）；速度作为 ``mean_slide`` /
    ``max_slide`` 记录，不做否决——源动作本来就可能滑步，滑多少正是 M1
    脚锁要处理的量。
    """
    cfg = {**CONTACT_DEFAULTS, **(config or {})}
    mapping = profile.get("map", {})
    rest = profile.get("rest", {})
    height = _model_height(profile)

    eff = {
        "leftFoot": mapping.get("leftFoot"),
        "rightFoot": mapping.get("rightFoot"),
    }
    eff = {k: v for k, v in eff.items() if v and v in rest}
    if not eff:
        return []

    # 优先用足 IK 的目标位置：MMD 的腿是 IK 驱动，VMD 里腿骨旋转往往
    # 不足以还原脚踝位置。IK 骨 rest head + 位移键与 Blender 的实测脚踝
    # 误差约 1–2 mm（见 docs/reports/05）。
    positions: dict[str, list[tuple[float, float, float]]] = {}
    sources: dict[str, str] = {}
    for name, bone in eff.items():
        ik_sem = {
            "leftFoot": "leftFootIK",
            "rightFoot": "rightFootIK",
        }.get(name)
        ik_bone = mapping.get(ik_sem) if ik_sem else None
        keys = translations.get(ik_sem) if ik_sem else None
        if ik_bone and ik_bone in rest and keys:
            head = rest[ik_bone]["head"]
            positions[name] = [
                (
                    head[0] + sample_keys(keys, f, quat=False)[0],
                    head[1] + sample_keys(keys, f, quat=False)[1],
                    head[2] + sample_keys(keys, f, quat=False)[2],
                )
                for f in range(frames)
            ]
            sources[name] = "foot_ik"
        else:
            sources[name] = "fk"

    fallback = [n for n in eff if n not in positions]
    if fallback:
        pos_by_bone = forward_positions(
            profile, joints, translations, root, frames, targets=[eff[n] for n in fallback]
        )
        for name in fallback:
            positions[name] = pos_by_bone[eff[name]]

    margin = cfg["height_margin"] * height
    contacts: list[dict] = []

    window = int(cfg["window"])
    for name, pts in positions.items():
        rest_y = rest[eff[name]]["head"][1]
        moving = [0.0] * len(pts)
        for i in range(1, len(pts)):
            moving[i] = math.dist(pts[i], pts[i - 1])
        # 速度不做硬性否决：源动作本来就可能滑步，滑多少正是要报告的量。
        # 这里只把它作为接触段的统计字段，交给 M1 的脚锁判断。
        # 局部最低点：舞步里身体会整体上下起伏，用全局阈值会漏掉一半接触。
        local_min = []
        for f in range(len(pts)):
            lo = max(0, f - window)
            hi = min(len(pts), f + window + 1)
            local_min.append(min(pts[i][1] for i in range(lo, hi)))
        seg_start: int | None = None
        last_contact = -10
        for f, p in enumerate(pts):
            grounded = p[1] <= local_min[f] + margin
            if grounded:
                if seg_start is None:
                    seg_start = f
                last_contact = f
            elif seg_start is not None and f - last_contact > cfg["max_gap"]:
                _append_contact(
                    contacts, name, pts, seg_start, last_contact, cfg, rest_y + margin,
                    sources[name],
                )
                seg_start = None
        if seg_start is not None:
            _append_contact(
                contacts, name, pts, seg_start, last_contact, cfg, rest_y + margin,
                sources[name],
            )

    contacts.sort(key=lambda c: (c["start"], c["effector"]))
    return contacts


def _append_contact(contacts, name, pts, start, end, cfg, threshold, source="fk"):
    if end - start + 1 < cfg["min_frames"]:
        return
    window = pts[start : end + 1]
    mean = tuple(sum(p[i] for p in window) / len(window) for i in range(3))
    slides = [math.dist(window[i], window[i - 1]) for i in range(1, len(window))]
    contacts.append(
        {
            "start": start,
            "end": end,
            "effector": name,
            "pos": [round(v, 6) for v in mean],
            "min_y": round(min(p[1] for p in window), 6),
            "mean_slide": round(sum(slides) / len(slides), 6) if slides else 0.0,
            "max_slide": round(max(slides), 6) if slides else 0.0,
            "threshold": round(threshold, 6),
            "source": source,
        }
    )


def build_canonical(
    vmd: Vmd,
    profile: dict,
    *,
    source_path: str = "",
    profile_path: str = "",
    detect: bool = True,
    contact_config: dict | None = None,
) -> dict:
    root, joints, extra, translations, extra_translations = _split_motion(vmd, profile)
    max_frame = vmd.summary()["frame_end"]
    frames = int(max_frame) + 1

    morphs: dict[str, list] = {}
    for m in vmd.morph_frames:
        morphs.setdefault(m.morph, []).append([float(m.frame), float(m.weight)])
    morphs = {k: _clean(v, 1) for k, v in morphs.items()}

    contacts = []
    if detect:
        contacts = detect_contacts(
            profile, joints, translations, root, frames, config=contact_config
        )

    return {
        "schema": CANONICAL_SCHEMA,
        "fps": 30,
        "frames": frames,
        "source": {
            "model": vmd.model_name,
            "vmd": source_path,
            "profile": profile_path,
        },
        "root": root,
        "joints": joints,
        "translations": translations,
        "extra": extra,
        "extra_translations": extra_translations,
        "contacts": contacts,
        "morphs": morphs,
        "meta": {
            "joints": len(joints),
            "extra_bones": len(extra),
            "morphs": len(morphs),
            "contacts": len(contacts),
            "contact_config": {**CONTACT_DEFAULTS, **(contact_config or {})},
        },
    }


def save_canonical(motion: dict, path: str | Path) -> None:
    path = Path(path)
    path.write_text(json.dumps(motion, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def load_canonical(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
