# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender 端 BVH 穿模检测（M2）。

必须在 Blender 里运行；纯 Python 部分见 :mod:`mmd_retarget.validate`。

做法
----
1. 按材质 + 主导骨骼把网格分成 arm / leg / torso / skirt / hair / wings；
2. 每帧对每个部位建 BVH；
3. 对指定部位对做 ``overlap``，再用顶点到对方表面的最近距离估计穿透深度；
4. 输出 CSV，并可选地在时间轴上打 marker。

这是**近似深度**：用顶点采样而不是精确的 CSG/体积求交，适合定位问题帧，
不适合做毫米级验收。M2 的验收口径是“人工按报告能在 1 小时内定位 high
帧”，这个精度足够。
"""
from __future__ import annotations

import math
import time
from collections import Counter
from pathlib import Path

from .validate import make_record, write_csv

__all__ = ["run_validation", "PART_PAIRS"]

PART_PAIRS = (
    ("leftArm", "torso"),
    ("rightArm", "torso"),
    ("leftArm", "skirt"),
    ("rightArm", "skirt"),
    ("leftLeg", "skirt"),
    ("rightLeg", "skirt"),
    ("hair", "torso"),
    ("wings", "torso"),
)

#: 这些 pair 里“肢体跑到衣物外面”才是穿模。
OUTSIDE_IS_BAD = {
    ("leftLeg", "skirt"),
    ("rightLeg", "skirt"),
}

_ARM_KEYS = ("肩", "腕", "ひじ", "手首", "手捩")
_LEG_KEYS = ("足", "ひざ", "つま先")
_TORSO_KEYS = ("上半身", "下半身", "腰", "首", "頭", "センター", "グルーブ", "全ての親")


def _bone_part(name: str) -> str | None:
    if name.startswith("左"):
        if any(k in name for k in _ARM_KEYS):
            return "leftArm"
        if any(k in name for k in _LEG_KEYS):
            return "leftLeg"
    if name.startswith("右"):
        if any(k in name for k in _ARM_KEYS):
            return "rightArm"
        if any(k in name for k in _LEG_KEYS):
            return "rightLeg"
    if any(k in name for k in _TORSO_KEYS):
        return "torso"
    return None


def _material_part(name: str) -> str | None:
    # 裙内是内衬；腿在裙子内部是正常的，只有穿过**外层**裙面才算穿模。
    if "裙内" in name:
        return None
    if "裙" in name:
        return "skirt"
    if "髮" in name or "前髪" in name:
        return "hair"
    if "翼" in name:
        return "wings"
    return None


def _prepare_parts(obj, arm):
    """返回 {part: [(i,j,k), ...]}，顶点索引对应原网格。"""
    bone_names = set(arm.data.bones.keys())
    group_name = {g.index: g.name for g in obj.vertex_groups}

    dominant: list[str | None] = []
    for v in obj.data.vertices:
        best_name, best_w = None, -1.0
        for g in v.groups:
            name = group_name.get(g.group)
            if name in bone_names and g.weight > best_w:
                best_name, best_w = name, g.weight
        dominant.append(best_name)

    parts: dict[str, list[tuple[int, int, int]]] = {p: [] for p in (
        "leftArm", "rightArm", "leftLeg", "rightLeg", "torso", "skirt", "hair", "wings"
    )}
    materials = obj.data.materials
    for poly in obj.data.polygons:
        if len(poly.vertices) != 3:
            continue
        mat = materials[poly.material_index] if poly.material_index < len(materials) else None
        part = _material_part(mat.name) if mat else None
        if part is None:
            votes = Counter(
                _bone_part(dominant[i]) for i in poly.vertices if dominant[i] is not None
            )
            part = votes.most_common(1)[0][0] if votes else None
        if part:
            parts[part].append(tuple(poly.vertices))
    return parts


def _depth_mm(
    bvh_a, polys_a, bvh_b, polys_b, verts, ia, ib, mm_per_unit, outside_is_bad=False
):
    """估计穿透深度。

    ``outside_is_bad`` 用于“衣物包住肢体”的场景（腿 vs 裙）：腿在裙子
    **内部**是正常的，只有穿到外层外面才算穿模，所以判据取反。
    """
    depth = 0.0
    worst = None
    for tri, bvh in ((polys_b[ib], bvh_a), (polys_a[ia], bvh_b)):
        for vi in tri:
            p = verts[vi]
            loc, normal, _idx, dist = bvh.find_nearest(p)
            if loc is None or normal is None:
                continue
            side = normal.dot(p - loc)
            if (side > 0.0) if outside_is_bad else (side < 0.0):
                if dist > depth:
                    depth = dist
                    worst = p.copy()
    return depth * mm_per_unit, worst


def _setup_camera(scene, camera: str | None, obj):
    import bpy
    from mathutils import Vector

    if camera and camera in bpy.data.objects:
        scene.camera = bpy.data.objects[camera]
        return
    if scene.camera is not None:
        return
    # 默认机位：正面偏上，框住整个模型。它只是“能看见”的演示机位，
    # 不是最终渲染机位；验收时应显式传 --camera。
    bpy.context.view_layer.update()
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    zs = [c.z for c in corners]
    top = max(zs)
    center = sum(corners, Vector()) / 8.0
    cam_data = bpy.data.cameras.new("validate_cam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("validate_cam", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = (center.x + top * 0.8, center.y - top * 2.0, center.z + top * 0.15)
    direction = center - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam


def _visible(scene, depsgraph, point, height: float) -> str:
    cam = scene.camera
    if cam is None:
        return "unknown"
    origin = cam.matrix_world.translation
    direction = point - origin
    if direction.length < 1e-9:
        return "unknown"
    direction.normalize()
    hit, loc, _nor, _idx, _obj, _mat = scene.ray_cast(depsgraph, origin, direction)
    if not hit:
        return "yes"
    # 第一个命中点就在穿透点附近 → 可见；否则被其他几何挡住。
    return "yes" if (loc - point).length < max(0.01 * height, 0.02) else "no"


def run_validation(
    *,
    model_path: str | None,
    motion_path: str | None,
    out_csv: str,
    step: int = 20,
    start: int = 0,
    end: int | None = None,
    threshold_mm: float = 2.0,
    max_pairs: int = 200,
    max_depth_pairs: int = 40,
    markers: bool = True,
    visibility: bool = False,
    camera: str | None = None,
    assumed_height_m: float = 1.6,
) -> list[dict]:
    import bpy
    from mathutils.bvhtree import BVHTree

    if model_path:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.preferences.addon_enable(module="bl_ext.user_default.mmd_tools")
        bpy.ops.mmd_tools.import_model(
            filepath=model_path,
            scale=1.0,
            types={"MESH", "ARMATURE"},
            clean_model=True,
            rename_bones=False,
        )
    if motion_path:
        bpy.ops.mmd_tools.import_vmd(
            filepath=motion_path, scale=1.0, margin=0, update_scene_settings=True
        )

    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups]
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not meshes or not arms:
        raise RuntimeError("scene has no skinned mesh/armature; import a PMX + VMD first")
    obj = max(meshes, key=lambda o: len(o.data.vertices))
    arm = arms[0]

    scene = bpy.context.scene
    if visibility:
        _setup_camera(scene, camera, obj)
    end = end if end is not None else scene.frame_end - 1
    start = max(start, 0)
    end = min(end, scene.frame_end - 1)

    # 模型高度：用骨骼最高点（Blender Z-up）
    top = max((arm.matrix_world @ b.head_local).z for b in arm.data.bones)
    mm_per_unit = assumed_height_m * 1000.0 / top if top > 1e-6 else 1.0

    parts = _prepare_parts(obj, arm)
    print(f"[validate] parts: " + ", ".join(f"{k}={len(v)}" for k, v in parts.items()))
    print(f"[validate] frames {start}..{end} step {step}; {mm_per_unit:.3f} mm/unit")

    records: list[dict] = []
    markers_added: set[int] = set()
    t0 = time.perf_counter()
    frames = list(range(start, end + 1, max(1, step)))

    for n, vmd_frame in enumerate(frames, 1):
        scene.frame_set(vmd_frame + 1)  # VMD frame 0 == Blender frame 1
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        mw = ev.matrix_world
        verts = [mw @ v.co for v in me.vertices]

        bvhs = {}
        for part, polys in parts.items():
            if polys:
                bvhs[part] = BVHTree.FromPolygons(verts, polys, all_triangles=True)

        for pa, pb in PART_PAIRS:
            if pa not in bvhs or pb not in bvhs:
                continue
            pairs = bvhs[pa].overlap(bvhs[pb])
            if not pairs:
                continue
            pairs = pairs[:max_pairs]
            best = 0.0
            worst_point = None
            for ia, ib in pairs[:max_depth_pairs]:
                depth, point = _depth_mm(
                    bvhs[pa], parts[pa], bvhs[pb], parts[pb], verts, ia, ib,
                    mm_per_unit, outside_is_bad=(pa, pb) in OUTSIDE_IS_BAD,
                )
                if depth > best:
                    best, worst_point = depth, point
            if best >= threshold_mm:
                rec = make_record(vmd_frame, pa, pb, best, pairs=len(pairs))
                if visibility and worst_point is not None:
                    rec["visible"] = _visible(scene, dg, worst_point, top)
                records.append(rec)
                if markers and rec["severity"] == "high" and vmd_frame not in markers_added:
                    scene.timeline_markers.new(f"clip_{vmd_frame}", frame=vmd_frame + 1)
                    markers_added.add(vmd_frame)

        ev.to_mesh_clear()
        if n % 20 == 0:
            elapsed = time.perf_counter() - t0
            print(f"[validate] {n}/{len(frames)} frames, {elapsed:.1f}s, {len(records)} records")

    write_csv(records, out_csv)
    elapsed = time.perf_counter() - t0
    print(f"[validate] done: {len(records)} records -> {out_csv} ({elapsed:.1f}s)")
    return records
