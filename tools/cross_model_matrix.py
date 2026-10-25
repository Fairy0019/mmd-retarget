# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""跨模型矩阵：源 profile × 目标 profile × canonical → 一行指标。

用法::

    python tools/cross_model_matrix.py \
      --motion motion.json --source src.json --target dst.json --label "Vesna->Lumine"

输出 JSON（可重定向到 csv/ndjson 汇总）。真实第二副 PMX 到位后，直接
`skeleton lumine.pmx -o lumine.json` 再跑本脚本即可。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mmd_retarget.canonical import load_canonical  # noqa: E402
from mmd_retarget.retarget import contact_slide_stats, retarget_motion  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--motion", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    motion = load_canonical(args.motion)
    source = json.loads(Path(args.source).read_text(encoding="utf-8"))
    target = json.loads(Path(args.target).read_text(encoding="utf-8"))
    config = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else None

    out = retarget_motion(motion, source, target, config=config)
    st = out["meta"]["retarget"]
    slide = contact_slide_stats(out, target)
    height = st.get("target_height") or 1.0
    mpu = 1.6 / height
    row = {
        "label": args.label or f"{source.get('model')}->{target.get('model')}",
        "source": source.get("model"),
        "target": target.get("model"),
        "scale": st.get("scale"),
        "source_height": st.get("source_height"),
        "target_height": st.get("target_height"),
        "wrist_error_mean_units": st.get("arm_ik", {}).get("mean_wrist_error", 0.0),
        "wrist_error_max_units": st.get("arm_ik", {}).get("max_wrist_error", 0.0),
        "arm_reach_clamped": st.get("arm_ik", {}).get("reach_clamped", 0),
        "clearance_pushed": st.get("arm_ik", {}).get("clearance_pushed", 0),
        "locked_chunks": st.get("locked"),
        "chunks": st.get("chunks"),
        "locked_coverage": round(st.get("locked_coverage", 0.0), 4),
        "slide_units_per_frame": round(slide.get("mean_slide", 0.0), 5),
        "slide_mm_per_frame": round(slide.get("mean_slide", 0.0) * mpu * 1000, 3),
        "pelvic_applied": st.get("pelvic_applied"),
        "pelvic_residual": st.get("pelvic_residual"),
        "skipped_reach": st.get("skipped_reach"),
    }
    print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
