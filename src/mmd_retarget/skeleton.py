# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""从 PMX 生成 ``skeleton_profile.json``。

profile 是「模型 → 语义」的桥：

- ``map``：语义关节名 → 模型里的实际骨名；
- ``rest``：每根骨的 rest head/tail/parent/layer；
- ``limits``：从 PMX IK link 里能拿到的关节限位（弧度）；
- ``colliders``：按骨骼顶点包围盒估计的胶囊碰撞体。

约定
----
语义名采用 ``leftUpperArm`` / ``leftLowerArm`` / ``leftFoot`` 这类
小驼峰；左右前缀固定为 ``left`` / ``right``。PMX 本身没有 bone roll，
因此 ``rest[*].roll`` 统一写 0.0，真正的 roll 在 M1 由 Blender 的
head/tail + local axis 计算。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .pmx import Pmx, PmxBone

__all__ = [
    "SEMANTIC_SPECS",
    "build_profile",
    "write_profile",
    "load_profile",
    "mapped_for_bones",
]

# 语义后缀 → 日文骨名。左右由 _side_specs() 自动展开。
_CORE = {
    "master": ("全ての親",),
    "control": ("操作中心",),
    "root": ("センター",),
    "groove": ("グルーブ",),
    "waist": ("腰",),
    "hips": ("下半身",),
    "spine": ("上半身",),
    "spine1": ("上半身1",),
    "spine2": ("上半身2",),
    "spine3": ("上半身3",),
    "neck": ("首",),
    "head": ("頭",),
    "bothEyes": ("両目",),
}

# 左右对称：语义后缀 → 日文基名（不含 左/右）。
_SIDE = {
    "Eye": ("目",),
    "Ear": ("耳",),
    "Shoulder": ("肩",),
    "ShoulderP": ("肩P",),
    "ShoulderC": ("肩C",),
    "UpperArm": ("腕",),
    "UpperArmTwist": ("腕捩",),
    "UpperArmTwist1": ("腕捩1",),
    "UpperArmTwist2": ("腕捩2",),
    "UpperArmTwist3": ("腕捩3",),
    "LowerArm": ("ひじ",),
    "LowerArmTwist": ("手捩",),
    "LowerArmTwist1": ("手捩1",),
    "LowerArmTwist2": ("手捩2",),
    "LowerArmTwist3": ("手捩3",),
    "Hand": ("手首",),
    "Thumb0": ("親指０",),
    "Thumb1": ("親指１",),
    "Thumb2": ("親指２",),
    "Index1": ("人指１",),
    "Index2": ("人指２",),
    "Index3": ("人指３",),
    "Middle1": ("中指１",),
    "Middle2": ("中指２",),
    "Middle3": ("中指３",),
    "Ring1": ("薬指１",),
    "Ring2": ("薬指２",),
    "Ring3": ("薬指３",),
    "Pinky1": ("小指１",),
    "Pinky2": ("小指２",),
    "Pinky3": ("小指３",),
    "UpperLeg": ("足",),
    "LowerLeg": ("ひざ",),
    "Foot": ("足首",),
    "Toe": ("つま先",),
    "UpperLegD": ("足D",),
    "LowerLegD": ("ひざD",),
    "FootD": ("足首D",),
    "ToeD": ("つま先D",),
    "FootIK": ("足ＩＫ", "足IK"),
    "ToeIK": ("つま先ＩＫ", "つま先IK"),
    "Breast": ("胸",),
}


def _side_specs() -> dict[str, tuple[str, ...]]:
    """展开左右语义，并附上 ``腕.L`` 这类英文后缀写法。"""
    out: dict[str, tuple[str, ...]] = {}
    for side, ja, en, suffix in (
        ("left", "左", "left", ".L"),
        ("right", "右", "right", ".R"),
    ):
        for key, names in _SIDE.items():
            candidates: list[str] = []
            for n in names:
                candidates.append(ja + n)
                # 少数模型用 腕.L / ひじ.R 而不是 左腕
                candidates.append(n + suffix)
            out[en + key] = tuple(dict.fromkeys(candidates))
    return out


#: 所有语义键 → 候选骨名（按优先级）。
SEMANTIC_SPECS: dict[str, tuple[str, ...]] = {**_CORE, **_side_specs()}

#: 用于碰撞体的身体语义（不包含手指、眼睛、IK、物理件）。
_COLLIDER_SEMANTICS = (
    "hips",
    "spine",
    "spine1",
    "spine2",
    "neck",
    "head",
    "leftShoulder",
    "rightShoulder",
    "leftUpperArm",
    "rightUpperArm",
    "leftLowerArm",
    "rightLowerArm",
    "leftHand",
    "rightHand",
    "leftUpperLeg",
    "rightUpperLeg",
    "leftLowerLeg",
    "rightLowerLeg",
    "leftFoot",
    "rightFoot",
)


def _effective_tail(pmx: Pmx, bone: PmxBone, children: dict[int, list[int]]) -> tuple[float, float, float]:
    """碰撞体用的“实际骨段”末端。

    PMX 的 tail 字段经常只是显示用的提示点（例如 センター 的 tail 指向
    地面），真正参与形变的是「父 head → 第一个子 bone head」。因此优先
    取第一个子骨的 head。
    """
    if bone.length > 1e-6:
        return bone.tail
    kids = children.get(bone.index)
    if kids:
        return pmx.bones[kids[0]].head
    return bone.head


def _point_segment_distance(p, a, b) -> float:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    denom = ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2]
    if denom < 1e-12:
        return ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2 + (p[2] - a[2]) ** 2) ** 0.5
    t = ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1] + (p[2] - a[2]) * ab[2]) / denom
    t = max(0.0, min(1.0, t))
    q = (a[0] + ab[0] * t, a[1] + ab[1] * t, a[2] + ab[2] * t)
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2) ** 0.5


def _mesh_radius(pmx: Pmx, bone: PmxBone) -> float | None:
    """权重顶点包围盒到骨段的**最大垂直距离**。

    M3 的裙摆骨链需要知道“网格比骨头胖多少”，否则骨点躲开了腿，
    裙片网格仍会被腿顶穿。
    """
    box = pmx.bone_vertex_bbox.get(bone.index)
    if box is None:
        return None
    (x0, y0, z0), (x1, y1, z1) = box
    corners = [
        (x, y, z)
        for x in (x0, x1)
        for y in (y0, y1)
        for z in (z0, z1)
    ]
    radius = max(_point_segment_distance(c, bone.head, bone.tail) for c in corners)
    return round(min(max(radius, 0.0), 0.6), 4)


def _capsule_radius(pmx: Pmx, bone: PmxBone) -> float | None:
    """按权重 ≥ 0.5 的顶点包围盒估计半径。

    这是给 M2 的**初值**，不是精确几何。最终穿透检测应使用 Blender 里的
    实际网格 BVH，而不是这个胶囊。
    """
    box = pmx.bone_vertex_bbox.get(bone.index)
    count = pmx.bone_vertex_count.get(bone.index, 0)
    if box is None or count < 10:
        return None
    (x0, _y0, z0), (x1, _y1, z1) = box
    # 几何平均比 max 更抗“袖子/头发被权重拉长”的离群轴。
    radius = 0.5 * ((abs(x1 - x0) * abs(z1 - z0)) ** 0.5)
    # 上下限防止个别权重错误把胶囊撑爆。
    return round(min(max(radius, 0.05), 1.2), 4)


def build_profile(pmx: Pmx) -> dict:
    """生成可 JSON 序列化的 skeleton profile。"""
    by_name = pmx.bone_by_name()
    children: dict[int, list[int]] = {}
    for b in pmx.bones:
        if 0 <= b.parent < len(pmx.bones):
            children.setdefault(b.parent, []).append(b.index)

    mapping: dict[str, str] = {}
    missing: list[str] = []
    for semantic, candidates in SEMANTIC_SPECS.items():
        found = next((c for c in candidates if c in by_name), None)
        if found is None:
            missing.append(semantic)
        else:
            mapping[semantic] = found

    rest: dict[str, dict] = {}
    for b in pmx.bones:
        rest[b.name] = {
            "head": [round(v, 6) for v in b.head],
            "tail": [round(v, 6) for v in b.tail],
            "length": round(b.length, 6),
            "parent": pmx.bones[b.parent].name if 0 <= b.parent < len(pmx.bones) else None,
            "layer": b.layer,
            "flags": b.flags,
            "roll": 0.0,
        }
        mesh_radius = _mesh_radius(pmx, b)
        if mesh_radius is not None:
            rest[b.name]["mesh_radius"] = mesh_radius
        if b.local_axis_x is not None and b.local_axis_z is not None:
            rest[b.name]["local_axis"] = {
                "x": [round(v, 6) for v in b.local_axis_x],
                "z": [round(v, 6) for v in b.local_axis_z],
            }

    # IK link 的限位是 PMX 里唯一可靠的关节约束来源。
    limits: dict[str, dict] = {}
    for b in pmx.bones:
        for link_index, has_limit, lo, hi in b.ik_links:
            if not has_limit or not (0 <= link_index < len(pmx.bones)):
                continue
            name = pmx.bones[link_index].name
            limits[name] = {
                "min": [round(v, 6) for v in lo],
                "max": [round(v, 6) for v in hi],
                "source": "ik_link",
            }

    colliders: list[dict] = []
    for semantic in _COLLIDER_SEMANTICS:
        name = mapping.get(semantic)
        if name is None:
            continue
        b = by_name[name]
        radius = _capsule_radius(pmx, b)
        if radius is None:
            # 很多模型把腿部蒙皮放在 D 骨上（左足D/ひざD），本体骨没有权重。
            fallback = mapping.get(semantic + "D")
            if fallback:
                radius = _capsule_radius(pmx, by_name[fallback])
        if radius is None:
            continue
        tail = _effective_tail(pmx, b, children)
        if sum((tail[i] - b.head[i]) ** 2 for i in range(3)) ** 0.5 < 0.05:
            continue
        colliders.append(
            {
                "bone": name,
                "semantic": semantic,
                "type": "capsule",
                "role": "body",
                "a": [round(v, 6) for v in b.head],
                "b": [round(v, 6) for v in tail],
                "radius": radius,
            }
        )

    return {
        "schema": 1,
        "generator": f"mmd-retarget {__version__}",
        "model": pmx.name,
        "model_en": pmx.name_en,
        "source": pmx.path,
        "format": "pmx",
        "version": pmx.version,
        "encoding": pmx.encoding,
        "units": {"length": "pmx", "angle": "rad"},
        "roll_note": "PMX 无 bone roll；M1 在 Blender 中按 head/tail/local_axis 计算",
        "map": mapping,
        "map_missing": missing,
        "rest": rest,
        "limits": limits,
        "colliders": colliders,
        "morphs": [m.name for m in pmx.morphs],
        "stats": {
            "bones": len(pmx.bones),
            "mapped": len(mapping),
            "semantics": len(SEMANTIC_SPECS),
            "map_coverage": round(len(mapping) / len(SEMANTIC_SPECS), 4),
            "limits": len(limits),
            "colliders": len(colliders),
            "morphs": len(pmx.morphs),
        },
    }


def write_profile(pmx: Pmx, path: str | Path) -> dict:
    """生成并写入 profile，返回 profile 本体。"""
    profile = build_profile(pmx)
    path = Path(path)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return profile


def load_profile(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def mapped_for_bones(profile: dict, bone_names: list[str]) -> dict[str, object]:
    """统计一组骨名（通常是 VMD 里的骨名）的语义覆盖率。"""
    mapping: dict[str, str] = profile.get("map", {})
    mapped = {sem: bone for sem, bone in mapping.items() if bone in bone_names}
    unmapped = [b for b in bone_names if b not in mapping.values()]
    return {
        "total": len(bone_names),
        "mapped": len(mapped),
        "coverage": round(len(mapped) / len(bone_names), 4) if bone_names else 0.0,
        "unmapped": unmapped,
    }
