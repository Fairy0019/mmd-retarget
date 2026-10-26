# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""视觉验收：批量渲染抽样帧 + HTML 对照表。

用法::

    blender -b scene.blend --python tools/render_acceptance.py -- \
      --out ../renders/acceptance --frames 0:300:30 --camera 机位_近景

    # 或先由 Blender 打开 .blend
    blender -b --python tools/render_acceptance.py -- --blend scene.blend ...

帧号是 **Blender 帧号**（VMD 第 0 帧 = Blender 第 1 帧）。
"""
from __future__ import annotations

import argparse
import html
import os
import sys
from pathlib import Path


def _parse_frames(spec: str) -> list[int]:
    if ":" in spec:
        parts = [int(p) for p in spec.split(":")]
        if len(parts) != 3:
            raise ValueError("--frames 形如 0:300:30 或 0,60,120")
        start, end, step = parts
        return list(range(start, end + 1, max(1, step)))
    return [int(p) for p in spec.split(",") if p.strip()]


def _build_html(frames: list[int], out_dir: Path, title: str) -> Path:
    cards = []
    for frame in frames:
        name = f"frame_{frame:05d}.png"
        if not (out_dir / name).exists():
            continue
        cards.append(
            f'<figure><a href="{name}"><img loading="lazy" src="{name}" alt="{frame}"></a>'
            f"<figcaption>frame {frame}</figcaption></figure>"
        )
    doc = f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
 body {{ background:#111; color:#ddd; font:14px/1.5 system-ui,sans-serif; margin:24px; }}
 .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:14px; }}
 figure {{ margin:0; background:#1b1b1f; border-radius:8px; overflow:hidden; }}
 img {{ width:100%; display:block; }}
 figcaption {{ padding:6px 10px; color:#aaa; }}
</style>
<h1>{html.escape(title)} · {len(cards)} frames</h1>
<div class="grid">{''.join(cards)}</div>
"""
    path = out_dir / "index.html"
    path.write_text(doc, encoding="utf-8")
    return path


def main() -> int:
    import bpy

    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", default=None, help="open this .blend before rendering")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--frames", default="0:300:60", help="0:300:30 or 0,60,120")
    ap.add_argument("--camera", default=None, help="camera object name")
    ap.add_argument("--motion", default=None, help="import this VMD before rendering")
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--height", type=int, default=1200)
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--engine", default="BLENDER_EEVEE", choices=["BLENDER_EEVEE", "CYCLES"])
    ap.add_argument("--title", default="MMD visual acceptance")
    ap.add_argument(
        "--clay", action="store_true",
        help="override all materials with neutral clay (recommended for clipping/silhouette)",
    )
    args = ap.parse_args(argv)

    if args.blend:
        bpy.ops.wm.open_mainfile(filepath=args.blend)

    scene = bpy.context.scene
    if args.motion:
        bpy.ops.preferences.addon_enable(module="bl_ext.user_default.mmd_tools")
        scene.frame_set(0)  # VMD 导入按当前帧偏移，必须先归零
        bpy.ops.mmd_tools.import_vmd(
            filepath=args.motion, scale=1.0, margin=0, update_scene_settings=True
        )
    if args.camera:
        cam = bpy.data.objects.get(args.camera)
        if cam is None or cam.type != "CAMERA":
            print(f"error: camera not found: {args.camera}", file=sys.stderr)
            return 2
        scene.camera = cam
    if scene.camera is None:
        print("error: scene has no camera; pass --camera", file=sys.stderr)
        return 2

    frames = _parse_frames(args.frames)
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    scene.render.engine = args.engine
    if args.engine == "BLENDER_EEVEE":
        scene.eevee.taa_render_samples = args.samples
    else:
        scene.cycles.samples = args.samples
        scene.cycles.device = "CPU"
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.use_file_extension = True
    scene.render.engine = args.engine

    if args.clay:
        mat = bpy.data.materials.new("acceptance_clay")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (0.55, 0.56, 0.60, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.65
        bpy.context.view_layer.material_override = mat
        print("[acceptance] clay material override enabled")

    print(f"[acceptance] camera={scene.camera.name} frames={len(frames)} out={out_dir}")
    for frame in frames:
        scene.frame_set(frame)
        scene.render.filepath = str(out_dir / f"frame_{frame:05d}.png")
        bpy.ops.render.render(write_still=True)
        print(f"[acceptance] rendered {frame}")

    index = _build_html(frames, out_dir, args.title)
    print(f"[acceptance] done: {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
