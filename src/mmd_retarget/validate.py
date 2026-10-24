# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""穿模报告：severity、CSV/JSON、回归 diff。

本模块不依赖 Blender；BVH 检测在 :mod:`mmd_retarget.validate_blender`。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

__all__ = [
    "SEVERITY_LEVELS",
    "classify",
    "make_record",
    "write_csv",
    "read_csv",
    "write_json",
    "diff_reports",
    "summarize",
]

#: (severity, 最小深度 mm)，从高到低。
SEVERITY_LEVELS = (("high", 30.0), ("medium", 10.0), ("low", 2.0))

CSV_FIELDS = (
    "frame",
    "part_a",
    "part_b",
    "depth_mm",
    "pairs",
    "visible",
    "severity",
    "suggestion",
)

_SUGGESTIONS = {
    ("arm", "torso"): "retarget:arm_ik",
    ("arm", "skirt"): "retarget:arm_ik / physics:skirt",
    ("arm", "hair"): "retarget:arm_ik",
    ("leg", "skirt"): "physics:skirt",
    ("leg", "torso"): "retarget:leg_ik",
    ("hair", "torso"): "physics:hair",
    ("wing", "torso"): "physics:wing",
}


def classify(depth_mm: float) -> str | None:
    """按深度返回 severity；低于 2 mm 视为接触噪声，返回 None。"""
    for name, minimum in SEVERITY_LEVELS:
        if depth_mm >= minimum:
            return name
    return None


def _suggestion(part_a: str, part_b: str) -> str:
    def kind(part: str) -> str:
        return part.replace("left", "").replace("right", "").lower()

    a, b = kind(part_a), kind(part_b)
    for (x, y), text in _SUGGESTIONS.items():
        if {x, y} == {a, b}:
            return text
    return "manual"


def make_record(
    frame: int,
    part_a: str,
    part_b: str,
    depth_mm: float,
    *,
    pairs: int = 0,
    visible: str = "unknown",
) -> dict:
    severity = classify(depth_mm)
    if severity is None:
        raise ValueError(f"depth {depth_mm} mm below reporting threshold")
    return {
        "frame": int(frame),
        "part_a": part_a,
        "part_b": part_b,
        "depth_mm": round(float(depth_mm), 3),
        "pairs": int(pairs),
        "visible": visible,
        "severity": severity,
        "suggestion": _suggestion(part_a, part_b),
    }


def write_csv(records: list[dict], path: str | Path) -> None:
    path = Path(path)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in records:
            writer.writerow({k: r.get(k, "") for k in CSV_FIELDS})


def read_csv(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        out.append(
            {
                "frame": int(r["frame"]),
                "part_a": r["part_a"],
                "part_b": r["part_b"],
                "depth_mm": float(r["depth_mm"]),
                "pairs": int(r.get("pairs") or 0),
                "visible": r.get("visible") or "unknown",
                "severity": r["severity"],
                "suggestion": r.get("suggestion", ""),
            }
        )
    return out


def write_json(records: list[dict], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _index(records: list[dict]) -> dict[tuple[int, str, str], float]:
    out: dict[tuple[int, str, str], float] = {}
    for r in records:
        key = (int(r["frame"]), r["part_a"], r["part_b"])
        out[key] = max(out.get(key, 0.0), float(r["depth_mm"]))
    return out


def diff_reports(old: list[dict], new: list[dict], *, tolerance_mm: float = 1.0) -> dict:
    """比较两次报告：新增 / 修复 / 变差 / 变好。"""
    a, b = _index(old), _index(new)
    result = {"new": [], "fixed": [], "worse": [], "better": []}
    for key, depth in b.items():
        if key not in a:
            result["new"].append({**dict(zip(("frame", "part_a", "part_b"), key)), "depth_mm": depth})
        elif depth > a[key] + tolerance_mm:
            result["worse"].append(
                {**dict(zip(("frame", "part_a", "part_b"), key)), "old": a[key], "new": depth}
            )
        elif depth < a[key] - tolerance_mm:
            result["better"].append(
                {**dict(zip(("frame", "part_a", "part_b"), key)), "old": a[key], "new": depth}
            )
    for key, depth in a.items():
        if key not in b:
            result["fixed"].append({**dict(zip(("frame", "part_a", "part_b"), key)), "depth_mm": depth})
    return result


def summarize(records: list[dict]) -> dict:
    by_sev: dict[str, int] = {}
    for r in records:
        by_sev[r["severity"]] = by_sev.get(r["severity"], 0) + 1
    return {
        "records": len(records),
        "frames": len({r["frame"] for r in records}),
        "by_severity": by_sev,
        "max_depth_mm": max((r["depth_mm"] for r in records), default=0.0),
    }
