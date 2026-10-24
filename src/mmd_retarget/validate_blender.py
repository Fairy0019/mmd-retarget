# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender 端 BVH 穿模检测（M2）。

必须在 Blender 里运行；纯 Python 部分见 :mod:`mmd_retarget.validate`。

M2 能力
-------
- 部位规则可配置（:mod:`mmd_retarget.parts`），不再硬编码日文关键字；
- BVH ``overlap`` + 顶点到对方表面的最近距离（近似穿透深度）；
- 多点可见性：取最深的 k 个点，按比例判定 ``yes / partial / no``；
- 多机位：``--camera a,b``，逐机位记录，任一机位可见即视为可见；
- 缩略图 + HTML contact sheet；
- CSV / JSON / 回归门槛（见 CLI）。

深度是近似值：用顶点采样而不是精确 CSG，适合定位问题帧，不适合毫米级验收。
"""
from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

from .parts import classify_bone, classify_material, load_rules, outside_is_bad, part_pairs
from .validate import (
    make_record,
    pick_visibility_points,
    visibility_from_ratios,
    write_contact_sheet,
    write_csv,
)

__all__ = ["run_validation", "PART_PAIRS"]

#: 兼容旧接口的默认部位对；实际以规则文件为准。
PART_PAIRS = tuple(
    tuple(p)
    for p in load_rules()["pairs"]
)


def _prepare_parts(obj, arm, rules):
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

    wanted = {"torso", "skirt", "hair", "wings"}
    for group in rules.get("limb_groups", {}):
        wanted |= {f"left{group}", f"right{group}"}
    parts: dict[str, list[tuple[int, int, int]]] = {p: [] for p in wanted}

    materials = obj.data.materials
    for poly in obj.data.polygons:
        if len(poly.vertices) != 3:
            continue
        mat = materials[poly.material_index] if poly.material_index < len(materials) else None
        part = classify_material(mat.name, rules) if mat else None
        if part is None:
            votes = Counter(
                classify_bone(dominant[i], rules)
                for i in poly.vertices
                if dominant[i] is not None
            )
            part = votes.most_common(1)[0][0] if votes else None
        if part:
            parts.setdefault(part, []).append(tuple(poly.vertices))
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


def _setup_cameras(scene, cameras: list[str], obj):
    import bpy
    from mathutils import Vector

    found = []
    for name in cameras:
        cam = bpy.data.objects.get(name)
        if cam is not None and cam.type == "CAMERA":
            found.append(cam)
    if found:
        scene.camera = found[0]
        return found
    if scene.camera is not None:
        return [scene.camera]

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
    return [cam]


def _visible_from(scene, depsgraph, cam, point, height: float) -> bool | None:
    if cam is None:
        return None
    origin = cam.matrix_world.translation
    direction = point - origin
    if direction.length < 1e-9:
        return None
    direction.normalize()
    hit, loc, _nor, _idx, _obj, _mat = scene.ray_cast(depsgraph, origin, direction)
    if not hit:
        return True
    # 第一个命中点就在穿透点附近 → 可见；否则被其他几何挡住。
    return (loc - point).length < max(0.01 * height, 0.02)


def _visibility(scene, depsgraph, cameras, points, height):
    """返回 (状态, 最大比例, "cam1:yes;cam2:no")。"""
    if not cameras or not points:
        return "unknown", None, ""
    ratios: dict[str, float] = {}
    per_cam = []
    for cam in cameras:
        seen = 0
        known = 0
        for p in points:
            hit = _visible_from(scene, depsgraph, cam, p, height)
            if hit is None:
                continue
            known += 1
            if hit:
                seen += 1
        if known == 0:
            per_cam.append(f"{cam.name}:unknown")
            continue
        ratio = seen / known
        ratios[cam.name] = ratio
        per_cam.append(f"{cam.name}:{'yes' if ratio >= 2 / 3 else ('partial' if ratio > 0 else 'no')}")
    status, best = visibility_from_ratios(ratios)
    return status, best, ";".join(per_cam)


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
    visibility_points: int = 3,
    thumbnails: str | None = None,
    thumb_size: int = 320,
    contact_sheet: str | None = None,
    parts_config: str | None = None,
    assumed_height_m: float = 1.6,
) -> list[dict]:
    import bpy
    from mathutils.bvhtree import BVHTree

    rules = load_rules(parts_config)
    pairs = part_pairs(rules)
    bad_outside = outside_is_bad(rules)

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
    cameras = []
    if visibility or thumbnails:
        names = [c.strip() for c in (camera or "").split(",") if c.strip()]
        cameras = _setup_cameras(scene, names, obj)
    if thumbnails:
        Path(thumbnails).mkdir(parents=True, exist_ok=True)
        # Workbench 在无 GPU 的服务器上会因 SSBO 限制渲染出空图；
        # Cycles CPU 虽然慢，但在 headless 下可靠。
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 8
        scene.render.resolution_x = thumb_size
        scene.render.resolution_y = thumb_size
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        if not any(o.type == "LIGHT" for o in bpy.data.objects):
            light_data = bpy.data.lights.new("validate_sun", "SUN")
            light_data.energy = 3.0
            light = bpy.data.objects.new("validate_sun", light_data)
            bpy.context.collection.objects.link(light)
            light.rotation_euler = (0.9, 0.0, 0.6)
        if scene.world is None:
            scene.world = bpy.data.worlds.new("validate_world")
        scene.world.use_nodes = True
        bg = scene.world.node_tree.nodes.get("Background")
        if bg:
            bg.inputs[0].default_value = (0.05, 0.05, 0.07, 1.0)
            bg.inputs[1].default_value = 0.5
    end = end if end is not None else scene.frame_end - 1
    start = max(start, 0)
    end = min(end, scene.frame_end - 1)

    # 模型高度：用骨骼最高点（Blender Z-up）
    top = max((arm.matrix_world @ b.head_local).z for b in arm.data.bones)
    mm_per_unit = assumed_height_m * 1000.0 / top if top > 1e-6 else 1.0

    parts = _prepare_parts(obj, arm, rules)
    print(f"[validate] parts: " + ", ".join(f"{k}={len(v)}" for k, v in parts.items()))
    print(f"[validate] frames {start}..{end} step {step}; {mm_per_unit:.3f} mm/unit")
    if cameras:
        print(f"[validate] cameras: " + ", ".join(c.name for c in cameras))

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

        high_this_frame = False
        for pa, pb in pairs:
            if pa not in bvhs or pb not in bvhs:
                continue
            overlaps = bvhs[pa].overlap(bvhs[pb])
            if not overlaps:
                continue
            overlaps = overlaps[:max_pairs]
            candidates: list[tuple[float, object]] = []
            for ia, ib in overlaps[:max_depth_pairs]:
                depth, point = _depth_mm(
                    bvhs[pa], parts[pa], bvhs[pb], parts[pb], verts, ia, ib,
                    mm_per_unit, outside_is_bad=(pa, pb) in bad_outside,
                )
                if depth > 0.0 and point is not None:
                    candidates.append((depth, point))
            best = max((c[0] for c in candidates), default=0.0)
            if best >= threshold_mm:
                rec = make_record(vmd_frame, pa, pb, best, pairs=len(overlaps))
                if visibility and candidates:
                    points = pick_visibility_points(candidates, visibility_points)
                    status, ratio, per_cam = _visibility(scene, dg, cameras, points, top)
                    rec["visible"] = status
                    rec["visible_ratio"] = "" if ratio is None else round(ratio, 3)
                    rec["visible_cameras"] = per_cam
                records.append(rec)
                if rec["severity"] == "high":
                    high_this_frame = True
                if markers and rec["severity"] == "high" and vmd_frame not in markers_added:
                    scene.timeline_markers.new(f"clip_{vmd_frame}", frame=vmd_frame + 1)
                    markers_added.add(vmd_frame)

        if thumbnails and high_this_frame:
            scene.render.filepath = str(Path(thumbnails) / f"clip_{vmd_frame:05d}.png")
            bpy.ops.render.render(write_still=True)

        ev.to_mesh_clear()
        if n % 20 == 0:
            elapsed = time.perf_counter() - t0
            print(f"[validate] {n}/{len(frames)} frames, {elapsed:.1f}s, {len(records)} records")

    write_csv(records, out_csv)
    if contact_sheet and thumbnails:
        count = write_contact_sheet(records, thumbnails, contact_sheet)
        print(f"[validate] contact sheet: {count} frames -> {contact_sheet}")
    elapsed = time.perf_counter() - t0
    print(f"[validate] done: {len(records)} records -> {out_csv} ({elapsed:.1f}s)")
    return records
