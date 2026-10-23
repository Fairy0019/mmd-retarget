# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""用 Blender + MMD Tools 导出真实 pose 位置，用于校验纯 Python FK。

用法::

    blender -b --python tools/blender_dump_pose.py -- model.pmx motion.vmd out.json

注意：MMD Tools 用 ``_VectorXZY`` 把 PMX 的 (x, y, z) 转成 Blender 的
(x, z, y)。本脚本输出时换回 PMX 分量顺序，方便与
``canonical.forward_positions`` 直接对比。
"""
from __future__ import annotations

import json
import sys

import bpy

BONES = [
    "センター",
    "上半身",
    "上半身2",
    "首",
    "頭",
    "左肩",
    "左腕",
    "左ひじ",
    "左手首",
    "左足",
    "左ひざ",
    "左足首",
    "左つま先",
    "右肩",
    "右腕",
    "右ひじ",
    "右手首",
    "右足",
    "右ひざ",
    "右足首",
    "右つま先",
]

# 抽帧：覆盖开头、中段、结尾和几个动作幅度大的位置。
SAMPLE_FRAMES = [0, 10, 50, 100, 200, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500, 5639]


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1 :]
    if len(argv) != 3:
        print("usage: blender -b --python tools/blender_dump_pose.py -- model.pmx motion.vmd out.json")
        return 2
    model_path, motion_path, out_path = argv

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.preferences.addon_enable(module="bl_ext.user_default.mmd_tools")
    bpy.ops.mmd_tools.import_model(
        filepath=model_path,
        scale=1.0,
        types={"MESH", "ARMATURE"},
        clean_model=True,
        rename_bones=False,
    )
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not armatures:
        print("error: no armature imported")
        return 1
    arm = armatures[0]
    bpy.ops.mmd_tools.import_vmd(
        filepath=motion_path, scale=1.0, margin=0, update_scene_settings=True
    )

    scene = bpy.context.scene
    data = {
        "model": model_path,
        "motion": motion_path,
        "blender_frame_offset": 1,  # VMD frame 0 == Blender frame 1
        "bones": [b for b in BONES if b in arm.pose.bones],
        "rest": {
            b.name: [b.head_local.x, b.head_local.y, b.head_local.z]
            for b in arm.data.bones
            if b.name in BONES
        },
        "frames": {},
    }

    for vmd_frame in SAMPLE_FRAMES:
        scene.frame_set(vmd_frame + 1)
        row = {}
        for name in data["bones"]:
            pb = arm.pose.bones[name]
            # armature space；MMD Tools 的 armature 对象通常无额外变换
            p = pb.matrix.translation
            # MMD Tools 用 _VectorXZY：(x, y, z) -> (x, z, y)。
            # 这是左右手系之间的反射，不是旋转，三个分量都取正。
            row[name] = [round(p.x, 6), round(p.z, 6), round(p.y, 6)]
        data["frames"][str(vmd_frame)] = row

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"wrote {out_path}: {len(data['frames'])} frames x {len(data['bones'])} bones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
