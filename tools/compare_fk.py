# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""对比纯 Python FK 与 Blender 实测 pose 位置。

用法::

    python tools/compare_fk.py profile.json canonical.json blender_pose.json

``blender_pose.json`` 由 ``tools/blender_dump_pose.py`` 生成。
输出每个骨的误差中位数/最大值，并给出结论（哪些骨受 IK 影响）。
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mmd_retarget.canonical import forward_positions  # noqa: E402

# 腿骨在 MMD 里由 IK 驱动，纯旋转 FK 不应期与 Blender 一致。
IK_AFFECTED = {
    "左ひざ",
    "右ひざ",
    "左足首",
    "右足首",
    "左つま先",
    "右つま先",
}


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    profile = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    motion = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    dump = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))

    bones = [b for b in dump["bones"]]
    positions = forward_positions(
        profile,
        motion["joints"],
        motion["translations"],
        motion["root"],
        motion["frames"],
        bones,
    )

    errors: dict[str, list[float]] = {b: [] for b in bones}
    for frame_text, row in dump["frames"].items():
        f = int(frame_text)
        for bone in bones:
            pts = positions.get(bone) or []
            if f < len(pts):
                (ax, ay, az), (bx, by, bz) = pts[f], row[bone]
                errors[bone].append(((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2) ** 0.5)

    print(f"{'bone':10s} {'median':>8s} {'p95':>8s} {'max':>8s}  note")
    for bone in bones:
        ds = errors[bone]
        if not ds:
            continue
        ds_sorted = sorted(ds)
        p95 = ds_sorted[int(0.95 * (len(ds_sorted) - 1))]
        note = "IK-driven" if bone in IK_AFFECTED else ""
        print(f"{bone:10s} {statistics.median(ds):8.3f} {p95:8.3f} {max(ds):8.3f}  {note}")

    body = [d for b, ds in errors.items() if b not in IK_AFFECTED for d in ds]
    if body:
        print(
            f"\nbody (non-IK): median={statistics.median(body):.4f} "
            f"p95={sorted(body)[int(0.95 * (len(body) - 1))]:.4f} max={max(body):.4f} (PMX units)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
