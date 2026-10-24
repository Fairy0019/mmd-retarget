# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender 端穿模检测入口。

用法::

    blender -b --python tools/blender_validate.py -- \
      --model /path/model.pmx \
      --motion /path/motion.vmd \
      --out report.csv \
      --step 20 --start 0 --end 5639 \
      --threshold-mm 2 --markers

也可以先在 ``scene.blend`` 里准备好模型/动作，再省略 ``--model/--motion``。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mmd_retarget.validate_blender import run_validation  # noqa: E402


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--motion", default=None)
    ap.add_argument("--out", default="report.csv")
    ap.add_argument("--step", type=int, default=20)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--threshold-mm", type=float, default=2.0)
    ap.add_argument("--max-pairs", type=int, default=200)
    ap.add_argument("--no-markers", action="store_true")
    ap.add_argument("--visibility", action="store_true")
    ap.add_argument("--camera", default=None)
    ap.add_argument("--thumbnails", default=None)
    args = ap.parse_args(argv)

    run_validation(
        model_path=args.model,
        motion_path=args.motion,
        out_csv=args.out,
        step=args.step,
        start=args.start,
        end=args.end,
        threshold_mm=args.threshold_mm,
        max_pairs=args.max_pairs,
        markers=not args.no_markers,
        visibility=args.visibility,
        camera=args.camera,
        thumbnails=args.thumbnails,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
