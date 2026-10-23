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
import sys

from . import __version__


def cmd_stub(args: argparse.Namespace) -> int:
    print(f"[{args.command}] not implemented yet (mmd-retarget {__version__})")
    print("see docs/PLAN.md for milestones")
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
    i.set_defaults(func=cmd_stub)

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
