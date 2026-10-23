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
from .vmd import VmdError, read_vmd


def cmd_stub(args: argparse.Namespace) -> int:
    print(f"[{args.command}] not implemented yet (mmd-retarget {__version__})")
    print("see docs/PLAN.md for milestones")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    suffix = path.suffix.lower()
    if suffix != ".vmd":
        print(f"error: unsupported format for now: {suffix or '(none)'}", file=sys.stderr)
        print("M0 目前只支持 .vmd；PMX 解析在下一步接入。", file=sys.stderr)
        return 2

    try:
        motion = read_vmd(path, strict=False)
    except VmdError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

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
    s.set_defaults(func=cmd_stub)

    i = sub.add_parser("inspect", help="parse a VMD/PMX and print a summary")
    i.add_argument("file")
    i.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    i.set_defaults(func=cmd_inspect)

    r = sub.add_parser("retarget", help="retarget canonical motion to a target skeleton")
    r.add_argument("motion")
    r.add_argument("-s", "--source", required=True)
    r.add_argument("-t", "--target", required=True)
    r.add_argument("-o", "--out", required=True)
    r.add_argument("-c", "--config", default=None)
    r.set_defaults(func=cmd_stub)

    ph = sub.add_parser("physics", help="bake passive physics (skirt/hair/sleeves)")
    ph.add_argument("-c", "--config", default=None)
    ph.set_defaults(func=cmd_stub)

    v = sub.add_parser("validate", help="detect and report clipping")
    v.add_argument("-c", "--camera", default="final")
    v.add_argument("-o", "--out", default="report.csv")
    v.add_argument("--frames", default=None)
    v.set_defaults(func=cmd_stub)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
