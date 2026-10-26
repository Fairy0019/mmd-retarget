# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""C4-B：裙摆布料代理 → 烘焙回 Q 骨。

为什么这样做
------------
骨链 PBD 只能让骨点躲开腿，裙片网格仍会被顶穿（报告 17/19）。布料能给出
真正的“壳”，但直接把布料网格作为成品会打断 VMD 管线。所以这里：

1. 复制裙片面 → `SkirtCloth` 代理；
2. 腰部 pin 到身体，身体用低模碰撞代理；
3. 跑 Blender Cloth 并烘焙 cache；
4. **两遍采样**：先把每帧每根 Q 骨的顶点质心读出来（此时 Q 骨还是 identity，
   避免布料被骨骼二次变换），再解算 Q 骨旋转并写入 Action；
5. 保存 .blend，原来的网格/材质/权重不变，Q 骨驱动裙摆。

用法::

    blender -b scene.blend --python tools/skirt_cloth.py -- \
      --out scene_cloth.blend --start 1 --end 300

    # 只搭场景不烘（检查 pin/碰撞设置）
    blender -b scene.blend --python tools/skirt_cloth.py -- \
      --out scene_cloth.blend --dry-run

注意：布料质量/耗时随 `--quality` 与帧数增长；先跑 300 帧确认稳定。
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path


def _args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", default=None, help="open this .blend first")
    ap.add_argument("--out", required=True, help="save the result .blend")
    ap.add_argument("--materials", default="裙,裙内", help="skirt material keywords")
    ap.add_argument("--bones", default="Q_", help="skirt bone prefix")
    ap.add_argument("--start", type=int, default=None, help="first frame (Blender frame)")
    ap.add_argument("--end", type=int, default=None, help="last frame (Blender frame)")
    ap.add_argument("--quality", type=int, default=6, help="cloth quality (3-10)")
    ap.add_argument("--mass", type=float, default=0.2)
    ap.add_argument("--bending", type=float, default=1.0)
    ap.add_argument("--collision-distance", type=float, default=0.005)
    ap.add_argument("--proxy-ratio", type=float, default=0.12, help="body collision decimate ratio")
    ap.add_argument("--max-angle-deg", type=float, default=12.0, help="per-frame bone clamp")
    ap.add_argument("--dry-run", action="store_true", help="setup only, no bake/save")
    return ap.parse_args(argv)


def _dist(a, b) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _q_from_to(a, b):
    def norm(v):
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return (v[0] / n, v[1] / n, v[2] / n)

    a, b = norm(a), norm(b)
    d = sum(x * y for x, y in zip(a, b))
    if d > 0.999999:
        return (0.0, 0.0, 0.0, 1.0)
    if d < -0.999999:
        ref = (0.0, 1.0, 0.0) if abs(a[1]) < 0.9 else (0.0, 0.0, 1.0)
        axis = (
            a[1] * ref[2] - a[2] * ref[1],
            a[2] * ref[0] - a[0] * ref[2],
            a[0] * ref[1] - a[1] * ref[0],
        )
        axis = norm(axis)
        return (axis[0], axis[1], axis[2], 0.0)
    axis = (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )
    q = (axis[0], axis[1], axis[2], 1.0 + d)
    n = math.sqrt(sum(v * v for v in q)) or 1.0
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def _q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _q_angle(a, b) -> float:
    d = abs(sum(x * y for x, y in zip(a, b)))
    return 2.0 * math.acos(max(-1.0, min(1.0, d)))


def _q_slerp(a, b, t):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0:
        b = tuple(-v for v in b)
        d = -d
    if d > 0.9995:
        q = tuple(a[i] + (b[i] - a[i]) * t for i in range(4))
        n = math.sqrt(sum(v * v for v in q)) or 1.0
        return tuple(v / n for v in q)
    theta = math.acos(max(-1.0, min(1.0, d)))
    s = math.sin(theta) or 1e-9
    wa = math.sin((1 - t) * theta) / s
    wb = math.sin(t * theta) / s
    return tuple(a[i] * wa + b[i] * wb for i in range(4))


def _skirt_material_indices(obj, keywords) -> set[int]:
    idx = set()
    for i, slot in enumerate(obj.material_slots):
        if slot.material and any(k in slot.material.name for k in keywords):
            idx.add(i)
    return idx


def _make_proxy(src, name: str, mat_idx: set[int]):
    import bpy
    import bmesh

    proxy = src.copy()
    proxy.data = src.data.copy()
    proxy.name = name
    proxy.data.name = name + "_mesh"
    for col in src.users_collection:
        col.objects.link(proxy)

    bm = bmesh.new()
    bm.from_mesh(proxy.data)
    bm.faces.ensure_lookup_table()
    doomed = [f for f in bm.faces if f.material_index not in mat_idx]
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bm.to_mesh(proxy.data)
    bm.free()
    proxy.data.update()
    return proxy


def _pin_group(proxy, arm, prefix: str) -> str:
    """腰部 pin：优先 Q_0_* 权重，退化为裙片最高 12% 的顶点。"""
    import bpy

    group = proxy.vertex_groups.new(name="cloth_pin")
    names = {g.index: g.name for g in proxy.vertex_groups}
    pinned = 0
    for v in proxy.data.vertices:
        if any(
            names.get(g.group, "").startswith(prefix + "0_") and g.weight > 0.05
            for g in v.groups
        ):
            group.add([v.index], 1.0, "REPLACE")
            pinned += 1
    if pinned == 0:
        zs = [(proxy.matrix_world @ v.co).z for v in proxy.data.vertices]
        if zs:
            top = max(zs)
            floor = top - (top - min(zs)) * 0.12
            for v in proxy.data.vertices:
                if (proxy.matrix_world @ v.co).z >= floor:
                    group.add([v.index], 1.0, "REPLACE")
                    pinned += 1
    print(f"[cloth] pin vertices: {pinned}/{len(proxy.data.vertices)}")
    return group.name


def _setup_cloth(proxy, pin_group: str, args, start: int, end: int):
    mod = proxy.modifiers.new("Cloth", "CLOTH")
    s = mod.settings
    for attr, value in (
        ("quality", args.quality),
        ("mass", args.mass),
        ("bending_stiffness", args.bending),
        ("vertex_group_mass", pin_group),
        ("pin_stiffness", 1.0),
    ):
        try:
            setattr(s, attr, value)
        except Exception as exc:
            print(f"[cloth] warn: {attr} -> {exc}")
    cs = getattr(s, "collision_settings", None)
    if cs is not None:
        for attr, value in (
            ("distance_min", args.collision_distance),
            ("use_self_collision", False),
        ):
            try:
                setattr(cs, attr, value)
            except Exception as exc:
                print(f"[cloth] warn collision: {attr} -> {exc}")
    # modifiers.new() 默认追加在末尾，即 Armature 之后，保持不动
    # 布料 cache 范围要显式设，否则 bake_all 会按场景默认范围（可能是全片）跑。
    try:
        pc = mod.point_cache
        pc.frame_start = start
        pc.frame_end = end
        print(f"[cloth] cache range {pc.frame_start}..{pc.frame_end}")
    except Exception as exc:
        print(f"[cloth] warn cache: {exc}")
    return mod


def _collision_proxy(body, ratio: float, exclude_materials: set[int] | None = None):
    import bmesh

    proxy = body.copy()
    proxy.data = body.data.copy()
    proxy.name = "BodyCollision"
    for col in body.users_collection:
        col.objects.link(proxy)
    # 碰撞体不能包含裙子自身：否则布料在和自己的一份静态拷贝打架，
    # 会被顶回腰部/塌成一团（300 帧 quality 3 的首轮失败原因）。
    if exclude_materials:
        bm = bmesh.new()
        bm.from_mesh(proxy.data)
        bm.faces.ensure_lookup_table()
        doomed = [f for f in bm.faces if f.material_index in exclude_materials]
        if doomed:
            bmesh.ops.delete(bm, geom=doomed, context="FACES")
        bm.to_mesh(proxy.data)
        bm.free()
        proxy.data.update()
    mod = proxy.modifiers.new("Decimate", "DECIMATE")
    mod.ratio = max(0.02, min(1.0, ratio))
    cm = proxy.modifiers.new("Collision", "COLLISION")
    try:
        cm.settings.thickness_outer = 0.01
        cm.settings.thickness_inner = 0.005
        cm.settings.cloth_friction = 5.0
    except Exception as exc:
        print(f"[cloth] warn collision: {exc}")
    proxy.hide_render = True
    proxy.display_type = "WIRE"
    return proxy


def _bone_chains(arm, prefix: str):
    import re

    pat = re.compile(r"^" + re.escape(prefix) + r"(\d+)_(\d+)$")
    groups: dict[int, list[tuple[int, str]]] = {}
    for b in arm.data.bones:
        m = pat.match(b.name)
        if m:
            groups.setdefault(int(m.group(2)), []).append((int(m.group(1)), b.name))
    chains = []
    for _j, items in sorted(groups.items()):
        items.sort()
        if len(items) >= 2:
            chains.append([name for _i, name in items])
    return chains


def _sample_centroids(proxy, arm, chains, start: int, end: int):
    """两遍中的第一遍：每帧每根 Q 骨的顶点质心（armature space）。"""
    import bpy

    inv = arm.matrix_world.inverted()
    names = {g.index: g.name for g in proxy.vertex_groups}
    bone_verts: dict[str, list[tuple[int, float]]] = {}
    for v in proxy.data.vertices:
        for g in v.groups:
            name = names.get(g.group, "")
            if name and g.weight > 0.02:
                bone_verts.setdefault(name, []).append((v.index, g.weight))

    scene = bpy.context.scene
    frames = list(range(start, end + 1))
    out: dict[str, list[tuple[float, float, float]]] = {
        b: [] for chain in chains for b in chain
    }
    for f in frames:
        scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        ev = proxy.evaluated_get(dg)
        me = ev.to_mesh()
        mw = ev.matrix_world
        coords = [inv @ (mw @ v.co) for v in me.vertices]
        for chain in chains:
            for bone in chain:
                items = bone_verts.get(bone, [])
                if not items:
                    out[bone].append((0.0, 0.0, 0.0))
                    continue
                wsum = sum(w for _i, w in items) or 1.0
                x = sum(coords[i].x * w for i, w in items) / wsum
                y = sum(coords[i].y * w for i, w in items) / wsum
                z = sum(coords[i].z * w for i, w in items) / wsum
                out[bone].append((x, y, z))
        ev.to_mesh_clear()
    print(f"[cloth] sampled {len(frames)} frames x {len(out)} bones")
    return frames, out


def _bake_bones(arm, chains, frames, centroids, max_angle_deg: float):
    """第二遍：质心 → Q 骨旋转，写入当前 Action。"""
    import bpy
    from mathutils import Quaternion, Vector

    scene = bpy.context.scene
    rest = {b.name: b for b in arm.data.bones}
    limit = math.radians(max_angle_deg)
    prev_local: dict[str, tuple | None] = {b: None for chain in chains for b in chain}

    for idx, f in enumerate(frames):
        scene.frame_set(f)
        for chain in chains:
            root = chain[0]
            parent = rest[root].parent
            parent_pose_q = (
                arm.pose.bones[parent.name].matrix.to_quaternion()
                if parent is not None
                else Quaternion((1, 0, 0, 0))
            )
            parent_rest_q = (
                parent.matrix_local.to_quaternion()
                if parent is not None
                else Quaternion((1, 0, 0, 0))
            )
            pq = parent_pose_q
            for i, bone in enumerate(chain):
                rb = rest[bone]
                R_rest_b = rb.matrix_local.to_quaternion()
                rest_dir_world = (rb.tail_local - rb.head_local).normalized()
                if i + 1 < len(chain):
                    desired = Vector(centroids[chain[i + 1]][idx]) - Vector(centroids[bone][idx])
                else:
                    desired = (rb.tail_local - rb.head_local).copy()
                if desired.length < 1e-9:
                    continue
                desired.normalize()

                # 世界/armature 空间的最短弧，保持 rest 的 roll
                R_delta = rest_dir_world.rotation_difference(desired)
                R_pose_b = R_delta @ R_rest_b
                # pose = parent_pose * (parent_rest^-1 * bone_rest) * local
                base = pq @ (parent_rest_q.inverted() @ R_rest_b)
                local = base.inverted() @ R_pose_b
                q = (local.x, local.y, local.z, local.w)
                if prev_local[bone] is not None and _q_angle(prev_local[bone], q) > limit:
                    q = _q_slerp(prev_local[bone], q, limit / _q_angle(prev_local[bone], q))
                prev_local[bone] = q
                pb = arm.pose.bones[bone]
                pb.rotation_mode = "QUATERNION"
                # Blender Quaternion 构造顺序是 (w, x, y, z)，这里 q 是 xyzw。
                local = Quaternion((q[3], q[0], q[1], q[2]))
                pb.rotation_quaternion = local
                pb.keyframe_insert("rotation_quaternion", frame=f, group=bone)
                pq = base @ local
                parent_rest_q = R_rest_b
    print(f"[cloth] baked {len(chains)} chains over {len(frames)} frames")


def main() -> int:
    import bpy

    args = _args()
    if args.blend:
        bpy.ops.wm.open_mainfile(filepath=args.blend)

    scene = bpy.context.scene
    orig_start, orig_end = scene.frame_start, scene.frame_end
    start = args.start if args.start is not None else scene.frame_start
    end = args.end if args.end is not None else scene.frame_end
    scene.frame_start, scene.frame_end = start, end

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    keywords = [k.strip() for k in args.materials.split(",") if k.strip()]
    candidates = [(o, _skirt_material_indices(o, keywords)) for o in meshes]
    candidates = [(o, idx) for o, idx in candidates if idx]
    if not candidates:
        print("error: no skirt materials found", file=sys.stderr)
        return 2
    body, mat_idx = max(candidates, key=lambda x: len(x[0].data.vertices))
    print(f"[cloth] body={body.name} skirt materials={sorted(mat_idx)}")

    proxy = _make_proxy(body, "SkirtCloth", mat_idx)
    pin = _pin_group(proxy, arm, args.bones)
    _setup_cloth(proxy, pin, args, start, end)
    _collision_proxy(body, args.proxy_ratio, mat_idx)

    chains = _bone_chains(arm, args.bones)
    print(f"[cloth] chains={len(chains)} bones={sum(len(c) for c in chains)}")
    if not chains:
        print("error: no skirt bone chains", file=sys.stderr)
        return 2

    if args.dry_run:
        print("[cloth] dry-run: setup only")
        return 0

    # 注意：不用 bake_all。这个模型有 447 个 Child Of 刚体，场景里还有一个
    # 5640 帧的 rigid body cache，bake_all 会连它一起烘。布料在顺序帧推进时
    # 会自己填充内存 cache，采样一遍即可。
    print("[cloth] sampling (sequential frame stepping drives the cloth) ...")
    frames, centroids = _sample_centroids(proxy, arm, chains, start, end)
    _bake_bones(arm, chains, frames, centroids, args.max_angle_deg)

    # 布料代理只用于采样；成品由 Q 骨驱动原网格。删掉代理，避免渲染时重复模拟。
    for name in ("SkirtCloth", "BodyCollision"):
        ob = bpy.data.objects.get(name)
        if ob is not None:
            bpy.data.objects.remove(ob, do_unlink=True)
    print("[cloth] proxies removed")

    scene.frame_start, scene.frame_end = orig_start, orig_end
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out), relative_remap=True, compress=True)
    print(f"[cloth] saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
