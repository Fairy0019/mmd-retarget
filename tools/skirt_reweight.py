# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""C4-A：把裙片权重从腿/骨盆转移到 Q 裙骨。

原理
----
模型自带 15 条 `Q_*` 裙骨，但裙片的主要权重在腿和骨盆上，所以腿一动裙子
就整片跟着走。这个脚本把“裙片顶点”的权重改到最近的 1–2 根 Q 骨上，让
`physics --skirt` 驱动的裙骨真正控制裙摆，而不是被腿拖拽。

用法::

    blender -b scene.blend --python tools/skirt_reweight.py -- \
      --out scene_reweight.blend --materials 裙,裙内

不改变网格拓扑、材质或形态键；只改顶点组。建议先 `--dry-run` 看会改多少顶点。
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", default=None, help="open this .blend first")
    ap.add_argument("--out", required=True, help="save the result to this .blend")
    ap.add_argument("--materials", default="裙", help="comma separated material keywords")
    ap.add_argument("--bones", default="Q_", help="skirt bone name prefix")
    ap.add_argument("--strip", default="足,ひざ,足首,つま先,下半身,腰", help="groups to remove")
    ap.add_argument("--influences", type=int, default=2, help="1 or 2 nearest skirt bones")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args(argv)


def _dist_point_segment(p, a, b) -> float:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    denom = ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2]
    if denom < 1e-12:
        return math.dist(p, a)
    t = ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1] + (p[2] - a[2]) * ab[2]) / denom
    t = max(0.0, min(1.0, t))
    q = (a[0] + ab[0] * t, a[1] + ab[1] * t, a[2] + ab[2] * t)
    return math.dist(p, q)


def main() -> int:
    import bpy

    args = _parse_args()
    if args.blend:
        bpy.ops.wm.open_mainfile(filepath=args.blend)

    mesh = max(
        (o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups),
        key=lambda o: len(o.data.vertices),
    )
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    keywords = [k.strip() for k in args.materials.split(",") if k.strip()]
    strip_keys = [k.strip() for k in args.strip.split(",") if k.strip()]

    skirt_bones = [b for b in arm.data.bones if b.name.startswith(args.bones)]
    if not skirt_bones:
        print(f"error: no bones starting with {args.bones!r}", file=sys.stderr)
        return 2

    mw = arm.matrix_world
    segments = [
        (
            b.name,
            tuple(mw @ b.head_local),
            tuple(mw @ b.tail_local),
        )
        for b in skirt_bones
    ]

    mats = mesh.data.materials
    skirt_verts: set[int] = set()
    for poly in mesh.data.polygons:
        mat = mats[poly.material_index] if poly.material_index < len(mats) else None
        if mat and any(k in mat.name for k in keywords):
            skirt_verts.update(poly.vertices)

    group_index = {g.index: g.name for g in mesh.vertex_groups}
    strip_group_ids = {
        g.index for g in mesh.vertex_groups if any(k in g.name for k in strip_keys)
    }
    todo = []
    for vi in skirt_verts:
        v = mesh.data.vertices[vi]
        names = {group_index.get(g.group, "") for g in v.groups}
        if any(name.startswith(args.bones) for name in names):
            continue
        todo.append(vi)

    print(f"[reweight] skirt verts={len(skirt_verts)} to-change={len(todo)} skirt bones={len(skirt_bones)}")
    if args.dry_run:
        return 0

    mw_mesh = mesh.matrix_world
    group_index_by_name = {g.name: g for g in mesh.vertex_groups}

    def ensure(name: str):
        if name not in group_index_by_name:
            group_index_by_name[name] = mesh.vertex_groups.new(name=name)
        return group_index_by_name[name]

    changed = 0
    for vi in todo:
        pos = tuple(mw_mesh @ mesh.data.vertices[vi].co)
        ranked = sorted(
            ((_dist_point_segment(pos, a, b), name) for name, a, b in segments),
            key=lambda x: x[0],
        )[: max(1, min(2, args.influences))]
        # 移除腿/骨盆权重
        for gi in strip_group_ids:
            try:
                mesh.vertex_groups[gi].remove([vi])
            except RuntimeError:
                pass
        # 反距离权重（避免 0 距离除零）
        eps = 1e-4
        inv = [(name, 1.0 / (d + eps)) for d, name in ranked]
        total = sum(w for _n, w in inv) or 1.0
        for name, w in inv:
            ensure(name).add([vi], w / total, "REPLACE")
        changed += 1

    print(f"[reweight] changed={changed}")
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out), relative_remap=True, compress=True)
    print(f"[reweight] saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
