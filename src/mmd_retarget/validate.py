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
    "regression_ok",
    "classify",
    "make_record",
    "write_csv",
    "read_csv",
    "write_json",
    "diff_reports",
    "summarize",
    "pick_visibility_points",
    "visibility_from_ratios",
    "write_contact_sheet",
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
    "visible_ratio",
    "visible_cameras",
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
    visible_ratio: float | None = None,
    visible_cameras: str = "",
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
        "visible_ratio": "" if visible_ratio is None else round(float(visible_ratio), 3),
        "visible_cameras": visible_cameras,
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
                "visible_ratio": (
                    float(r["visible_ratio"])
                    if r.get("visible_ratio") not in (None, "")
                    else ""
                ),
                "visible_cameras": r.get("visible_cameras", ""),
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


def regression_ok(diff: dict, *, max_new: int | None = None, max_worse: int | None = None) -> bool:
    """回归门槛：new/worse 数量超过上限则返回 False。None 表示不限制。"""
    if max_new is not None and len(diff["new"]) > max_new:
        return False
    if max_worse is not None and len(diff["worse"]) > max_worse:
        return False
    return True


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


def pick_visibility_points(candidates: list[tuple[float, object]], k: int = 3) -> list:
    """从 (深度, 点) 里取深度最大的 k 个不重复点。

    只取最深的单点会低估“可见面积”：一个点被手指遮住，不代表整块穿模看不见。
    """
    out: list = []
    for _depth, point in sorted(candidates, key=lambda c: -c[0]):
        if all(
            sum((point[i] - q[i]) ** 2 for i in range(3)) > 1e-12 for q in out
        ):
            out.append(point)
        if len(out) >= k:
            break
    return out


def visibility_from_ratios(ratios: dict[str, float]) -> tuple[str, float | None]:
    """多机位可见比例 -> (状态, 最大可见比例)。

    ``yes`` ≥ 2/3，``partial`` > 0，``no`` = 0；无机位则 ``unknown``。
    """
    if not ratios:
        return "unknown", None
    best = max(ratios.values())
    if best >= 2.0 / 3.0:
        return "yes", best
    if best > 0.0:
        return "partial", best
    return "no", 0.0


def write_contact_sheet(
    records: list[dict],
    thumbs_dir: str | Path,
    out_path: str | Path,
    *,
    title: str = "穿模 contact sheet",
) -> int:
    """把每个 high 帧的缩略图拼成 HTML contact sheet（可点击、带参数）。

    不依赖 PIL：服务器上没装图像库也能用。图片按相对路径引用，
    整个目录一起拷走即可。
    """
    import html

    thumbs_dir = Path(thumbs_dir)
    out_path = Path(out_path)
    out_dir = out_path.parent
    best: dict[int, dict] = {}
    for r in records:
        frame = int(r["frame"])
        cur = best.get(frame)
        if cur is None or float(r["depth_mm"]) > float(cur["depth_mm"]):
            best[frame] = r

    order = {"high": 0, "medium": 1, "low": 2}
    rows = sorted(
        best.values(),
        key=lambda r: (order.get(r["severity"], 9), -float(r["depth_mm"])),
    )

    cards = []
    for r in rows:
        frame = int(r["frame"])
        img = thumbs_dir / f"clip_{frame:05d}.png"
        if not img.exists():
            continue
        try:
            src = img.relative_to(out_dir).as_posix()
        except ValueError:
            src = img.as_posix()
        cards.append(
            f"""<figure class="{html.escape(r['severity'])}">
  <a href="{html.escape(src)}"><img loading="lazy" src="{html.escape(src)}" alt="frame {frame}"></a>
  <figcaption>
    <b>#{frame}</b> · {html.escape(r['part_a'])} ↔ {html.escape(r['part_b'])}<br>
    {float(r['depth_mm']):.1f} mm · {html.escape(r['severity'])} · visible={html.escape(str(r.get('visible','unknown')))}
  </figcaption>
</figure>"""
        )

    doc = f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  body {{ background:#111; color:#ddd; font:14px/1.5 system-ui, sans-serif; margin:24px; }}
  h1 {{ font-size:18px; font-weight:600; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:16px; }}
  figure {{ margin:0; background:#1b1b1f; border-radius:8px; overflow:hidden; }}
  figure.high {{ outline:2px solid #e5484d; }}
  figure.medium {{ outline:2px solid #f5a524; }}
  img {{ width:100%; display:block; }}
  figcaption {{ padding:8px 10px; color:#bbb; }}
  b {{ color:#fff; }}
</style>
<h1>{html.escape(title)} · {len(cards)} frames</h1>
<div class="grid">
{''.join(cards)}
</div>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return len(cards)
