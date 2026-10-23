# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""VMD 解析/写出性能基准。

用法::

    python tools/bench_vmd.py                    # 140 骨 × 5640 帧
    python tools/bench_vmd.py --bones 80 --frames 1800

不依赖任何外部素材：基准数据在内存里用固定记录拼出来，所以可以安全地
放进 CI 或服务器定时任务。
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mmd_retarget.vmd import build_vmd, parse_vmd  # noqa: E402

LINEAR64 = bytes.fromhex(
    "14141414141414146b6b6b6b6b6b6b6b"
    "141414141414146b6b6b6b6b6b6b6b01"
    "1414141414146b6b6b6b6b6b6b6b0100"
    "14141414146b6b6b6b6b6b6b6b010000"
)


def make_payload(n_bones: int, n_frames: int) -> bytes:
    """每个骨骼在每个整数帧都有一条关键帧。"""
    name = "センター".encode("cp932").ljust(15, b"\x00")
    record = struct.pack("<15sI3f4f64s", name, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, LINEAR64)
    per_bone = b"".join(
        record[:15] + struct.pack("<I", f) + record[19:] for f in range(n_frames)
    )
    bones = per_bone * n_bones
    return (
        b"Vocaloid Motion Data 0002".ljust(30, b"\x00")
        + "bench".encode("cp932").ljust(20, b"\x00")
        + struct.pack("<I", n_bones * n_frames)
        + bones
        + struct.pack("<IIIII", 0, 0, 0, 0, 0)
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bones", type=int, default=140)
    ap.add_argument("--frames", type=int, default=5640)
    args = ap.parse_args()

    t0 = time.perf_counter()
    data = make_payload(args.bones, args.frames)
    t_gen = time.perf_counter() - t0
    print(f"payload: {len(data) / 1e6:.1f} MB, {args.bones} bones x {args.frames} frames")

    t0 = time.perf_counter()
    vmd = parse_vmd(data)
    t_parse = time.perf_counter() - t0

    t0 = time.perf_counter()
    out = build_vmd(vmd)
    t_build = time.perf_counter() - t0

    assert out == data, "round-trip mismatch"
    print(f"generate : {t_gen * 1000:8.1f} ms")
    print(f"parse    : {t_parse * 1000:8.1f} ms  ({len(vmd.bone_frames) / t_parse:,.0f} frames/s)")
    print(f"build    : {t_build * 1000:8.1f} ms")
    print("round-trip: byte-exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
