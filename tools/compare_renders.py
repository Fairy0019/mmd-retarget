# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""把多组同帧渲染拼成 HTML contact sheet（行=帧，列=方案）。

用法::

    python tools/compare_renders.py --out compare.html \
      --labels 原始,C4-A,C4-B \
      --dirs /tmp/acc_orig,/tmp/acc_c4a,/tmp/acc_c4b
"""
from __future__ import annotations

import argparse
import html
import shutil
from pathlib import Path


def _frames(directory: Path) -> dict[int, Path]:
    out = {}
    for p in directory.glob("frame_*.png"):
        try:
            out[int(p.stem.split("_")[1])] = p
        except (IndexError, ValueError):
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--dirs", required=True)
    ap.add_argument("--title", default="C4 comparison")
    args = ap.parse_args()

    labels = [x.strip() for x in args.labels.split(",") if x.strip()]
    dirs = [Path(x.strip()) for x in args.dirs.split(",") if x.strip()]
    if len(labels) != len(dirs):
        raise SystemExit("labels and dirs count mismatch")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sets = [_frames(d) for d in dirs]
    frames = sorted(set.intersection(*(set(s) for s in sets))) if sets else []

    rows = []
    for f in frames:
        cells = []
        for label, directory, s in zip(labels, dirs, sets):
            dst_dir = out.parent / (out.stem + "_files") / f"{label}_{f:05d}"
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / s[f].name
            if not dst.exists():
                shutil.copy2(s[f], dst)
            rel = dst.relative_to(out.parent).as_posix()
            cells.append(
                f'<td><a href="{rel}"><img loading="lazy" src="{rel}" alt="{html.escape(label)} {f}"></a>'
                f"<div class=cap>{html.escape(label)} · {f}</div></td>"
            )
        rows.append(f"<tr><th>{f}</th>{''.join(cells)}</tr>")

    doc = f"""<!doctype html><meta charset="utf-8"><title>{html.escape(args.title)}</title>
<style>
 body{{background:#111;color:#ddd;font:13px/1.4 system-ui,sans-serif;margin:20px}}
 table{{border-collapse:collapse}} th{{padding:6px;color:#888;font-weight:400}}
 td{{padding:6px;vertical-align:top}} img{{width:260px;display:block;border-radius:4px}}
 .cap{{color:#999;margin-top:4px}} h1{{font-size:18px}}
</style>
<h1>{html.escape(args.title)} · {len(frames)} frames × {len(labels)} variants</h1>
<table><tr><th></th>{''.join(f'<th>{html.escape(x)}</th>' for x in labels)}</tr>
{''.join(rows)}</table>
"""
    out.write_text(doc, encoding="utf-8")
    print(f"wrote {out}: {len(frames)} frames x {len(labels)} variants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
