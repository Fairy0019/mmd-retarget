# -*- coding: utf-8 -*-
"""命令行入口（骨架）。

里程碑 M0–M4 逐步补齐：
  skeleton  生成 skeleton_profile
  inspect   解析 VMD/PMX 并输出摘要
  retarget  身体重定向
  physics   被动件物理
  validate  穿模检测与报告
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .canonical import build_canonical, load_canonical, save_canonical
from .retarget import contact_slide_stats, retarget_motion
from .pmx import PmxError, read_pmx
from .skeleton import load_profile, write_profile
from .validate import (
    diff_reports,
    read_csv,
    regression_ok,
    summarize,
    write_csv,
    write_json,
)
from .vmd import VmdError, read_vmd, write_vmd
from .writer import canonical_to_vmd


def cmd_stub(args: argparse.Namespace) -> int:
    print(f"[{args.command}] not implemented yet (mmd-retarget {__version__})")
    print("see docs/PLAN.md for milestones")
    return 0


def cmd_skeleton(args: argparse.Namespace) -> int:
    path = Path(args.model)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2
    try:
        pmx = read_pmx(path)
        profile = write_profile(pmx, args.out)
    except (PmxError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    stats = profile["stats"]
    print(f"model     : {pmx.name}")
    print(f"bones     : {stats['bones']}")
    print(f"mapped    : {stats['mapped']}/{stats['semantics']} semantics "
          f"({stats['map_coverage'] * 100:.1f}%)")
    print(f"limits    : {stats['limits']}")
    print(f"colliders : {stats['colliders']}")
    if profile["map_missing"]:
        print(f"missing   : {', '.join(profile['map_missing'])}")
    print(f"written   : {args.out}")
    return 0


def cmd_retarget(args: argparse.Namespace) -> int:
    """M0：canonical → 目标骨架的 pass-through 回写。

    真正的 rest/比例适配、脚锁、IK 在 M1 接入；这里只验证数据层闭环。
    """
    try:
        motion = load_canonical(args.motion)
        source = load_profile(args.source)
        target = load_profile(args.target)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if motion.get("schema") != 1:
        print(f"error: unsupported canonical schema: {motion.get('schema')}", file=sys.stderr)
        return 2

    config = None
    if args.config:
        try:
            config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"error: config: {exc}", file=sys.stderr)
            return 1

    before = contact_slide_stats(motion, source)
    result = retarget_motion(motion, source, target, config=config)
    after = contact_slide_stats(result, target)
    out = canonical_to_vmd(result, target)
    try:
        write_vmd(out, args.out)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    missing = [
        sem for sem in motion.get("joints", {}) if sem not in target.get("map", {})
    ]
    stats = result.get("meta", {}).get("retarget", {})
    height = stats.get("target_height") or 18.0
    mpu = 1.6 / height  # 粗略假设角色身高 1.6 m
    print(f"canonical : {args.motion}")
    print(f"source    : {source.get('model', '?')} -> target: {target.get('model', '?')}")
    print(f"scale     : {stats.get('scale', 1.0):.4f} (height {stats.get('source_height', '?')} -> {stats.get('target_height', '?')})")
    print(f"keys      : {len(out.bone_frames):,} bone / {len(out.morph_frames):,} morph")
    print(f"morphs    : {len(out.morphs)}")
    if out.dropped_bones:
        print(f"dropped   : {len(out.dropped_bones)} extra bones (目标模型没有)")
    if missing:
        print(f"unmapped  : {len(missing)} semantics 在目标 profile 中缺失")
    if stats.get("chain_split"):
        print(f"spine     : split across {len(stats['chain_split'])} target bones "
              f"({', '.join(stats['chain_split'])})")
    print(
        f"foot lock : {stats.get('locked', 0)}/{stats.get('chunks', 0)} chunks, "
        f"{stats.get('locked_frames', 0)} frames "
        f"({stats.get('locked_coverage', 0.0) * 100:.1f}%), "
        f"skip swing {stats.get('skipped_swing', 0)} / drift {stats.get('skipped_drift', 0)} "
        f"/ reach {stats.get('skipped_reach', 0)}"
    )
    print(
        f"slide     : mean {before['mean_slide']:.4f} -> {after['mean_slide']:.4f} units/frame "
        f"(全段；未锁窗口仍保留源滑步)"
    )
    smooth = stats.get("smoothing", {})
    if smooth.get("enabled") and smooth.get("series"):
        print(
            f"smooth    : max step {smooth['max_before']:.3f} -> {smooth['max_after']:.3f} "
            f"units/frame (limit {smooth['rate']:.3f}); "
            f"ramp {smooth['ramped_frames']} frames, drop {smooth['dropped_smoothing']} chunks, "
            f"drift {smooth['locked_drift']:.2e}"
        )
    print("note      : M1 stage 3（比例 + 承重 + 脚锁 + 锚定平滑 + 脊柱链）")
    print(f"written   : {args.out}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        import bpy  # noqa: F401
    except ImportError:
        print("error: validate 需要 Blender（bpy 不可用）", file=sys.stderr)
        print("用法: blender -b --python tools/blender_validate.py -- ...", file=sys.stderr)
        return 2

    from .validate_blender import run_validation

    try:
        records = run_validation(
            model_path=args.model,
            motion_path=args.motion,
            out_csv=args.out,
            step=args.step,
            start=args.start,
            end=args.end,
            threshold_mm=args.threshold,
            markers=not args.no_markers,
            visibility=args.visibility,
            camera=args.camera,
            thumbnails=args.thumbnails,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    stats = summarize(records)
    print(f"records   : {stats['records']}")
    print(f"frames    : {stats['frames']}")
    print(f"severity  : {stats['by_severity']}")
    print(f"max depth : {stats['max_depth_mm']:.2f} mm")
    print(f"written   : {args.out}")
    if args.json:
        write_json(records, args.json)
        print(f"json      : {args.json}")

    if args.diff:
        old = read_csv(args.diff)
        d = diff_reports(old, records)
        print(
            f"diff      : new {len(d['new'])}, fixed {len(d['fixed'])}, "
            f"worse {len(d['worse'])}, better {len(d['better'])}"
        )
        if not regression_ok(d, max_new=args.max_new, max_worse=args.max_worse):
            print(
                f"regression: FAILED (max_new={args.max_new}, max_worse={args.max_worse})",
                file=sys.stderr,
            )
            return 1
        if args.max_new is not None or args.max_worse is not None:
            print("regression: OK")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    suffix = path.suffix.lower()
    if suffix == ".pmx":
        try:
            pmx = read_pmx(path)
        except (PmxError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        info = pmx.summary()
        if args.json:
            info["file"] = str(path)
            info["bytes"] = path.stat().st_size
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 0
        print(f"file      : {path} ({path.stat().st_size:,} bytes)")
        print(f"model     : {pmx.name} / {pmx.name_en}")
        print(f"format    : PMX {pmx.version} ({pmx.encoding})")
        print(f"vertices  : {info['vertices']:,} ({info['triangles']:,} triangles)")
        print(f"bones     : {info['bones']} ({info['ik_bones']} IK)")
        print(f"materials : {info['materials']}")
        print(f"morphs    : {info['morphs']}")
        print(f"textures  : {info['textures']}")
        return 0

    if suffix != ".vmd":
        print(f"error: unsupported format for now: {suffix or '(none)'}", file=sys.stderr)
        print("M0 支持 .vmd 与 .pmx。", file=sys.stderr)
        return 2

    try:
        motion = read_vmd(path, strict=False)
    except VmdError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "out", None):
        if not args.profile:
            print("error: --out 需要 --profile（接触段/语义映射依赖骨架档案）", file=sys.stderr)
            return 2
        try:
            profile = load_profile(args.profile)
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        canonical = build_canonical(
            motion,
            profile,
            source_path=str(path),
            profile_path=args.profile,
        )
        save_canonical(canonical, args.out)
        meta = canonical["meta"]
        print(f"canonical : {args.out}")
        print(f"joints    : {meta['joints']} semantic / {meta['extra_bones']} extra bones")
        print(f"morphs    : {meta['morphs']}")
        print(f"contacts  : {meta['contacts']}")
        print(f"frames    : {canonical['frames']} ({canonical['frames'] / canonical['fps']:.1f} s)")

    info = motion.summary()
    info["file"] = str(path)
    info["bytes"] = path.stat().st_size
    info["sections_parsed"] = motion.sections_parsed

    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    print(f"file      : {path} ({info['bytes']:,} bytes)")
    print(f"model     : {motion.model_name}")
    print(f"frames    : {info['frame_start']} – {info['frame_end']} "
          f"({info['duration_sec']} s @ 30 fps)")
    print(f"bones     : {info['bones']} unique / {info['bone_frames']:,} keyframes")
    print(f"morphs    : {info['morphs']} unique / {info['morph_frames']:,} keyframes")
    print(
        "other     : "
        f"camera={info['camera_frames']} light={info['light_frames']} "
        f"shadow={info['shadow_frames']} ik={info['ik_frames']}"
    )
    if motion.trailer or not motion.sections_parsed:
        print(
            f"warning   : 未解析尾部 {info['trailer_bytes']} 字节"
            f"（sections_parsed={info['sections_parsed']}）；写回时原样保留"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mmd-retarget",
        description="MMD motion retargeting / collision correction / validation",
    )
    p.add_argument("--version", action="version", version=f"mmd-retarget {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("skeleton", help="generate skeleton_profile.json from a PMX")
    s.add_argument("model")
    s.add_argument("-o", "--out", default="skeleton_profile.json")
    s.set_defaults(func=cmd_skeleton)

    i = sub.add_parser("inspect", help="parse a VMD/PMX and print a summary")
    i.add_argument("file")
    i.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    i.add_argument("-o", "--out", default=None, help="write canonical_motion.json")
    i.add_argument("-p", "--profile", default=None, help="skeleton profile for --out")
    i.set_defaults(func=cmd_inspect)

    r = sub.add_parser("retarget", help="retarget canonical motion to a target skeleton")
    r.add_argument("motion")
    r.add_argument("-s", "--source", required=True)
    r.add_argument("-t", "--target", required=True)
    r.add_argument("-o", "--out", required=True)
    r.add_argument("-c", "--config", default=None)
    r.set_defaults(func=cmd_retarget)

    ph = sub.add_parser("physics", help="bake passive physics (skirt/hair/sleeves)")
    ph.add_argument("-c", "--config", default=None)
    ph.set_defaults(func=cmd_stub)

    v = sub.add_parser("validate", help="detect and report clipping (Blender only)")
    v.add_argument("-c", "--camera", default=None, help="camera object name for visibility")
    v.add_argument("-o", "--out", default="report.csv")
    v.add_argument("--model", default=None, help="import this PMX before validating")
    v.add_argument("--motion", default=None, help="import this VMD before validating")
    v.add_argument("--step", type=int, default=20, help="sample every N frames")
    v.add_argument("--start", type=int, default=0)
    v.add_argument("--end", type=int, default=None)
    v.add_argument("--threshold", type=float, default=2.0, help="min depth mm")
    v.add_argument("--diff", default=None, help="compare against an old CSV")
    v.add_argument("--max-new", type=int, default=None, help="fail if new records exceed N")
    v.add_argument("--max-worse", type=int, default=None, help="fail if worse records exceed N")
    v.add_argument("--no-markers", action="store_true")
    v.add_argument("--visibility", action="store_true", help="ray-cast visibility check")
    v.add_argument("--thumbnails", default=None, help="render high frames to this directory")
    v.add_argument("--json", default=None, help="also write records as JSON")
    v.set_defaults(func=cmd_validate)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
