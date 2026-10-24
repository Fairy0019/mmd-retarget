#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# 一条命令跑通：profile -> canonical -> retarget -> physics -> validate
#
# 用法:
#   MODEL=/path/dst.pmx MOTION=/path/motion.vmd ./tools/demo_pipeline.sh
#   SRC_MODEL=/path/src.pmx MODEL=... MOTION=... ./tools/demo_pipeline.sh
#
# 可选环境变量:
#   OUT=out           输出目录
#   STEP=20           validate 采样间隔
#   PHYSICS=1         启用头发物理（默认 1）
#   SKIRT=1           连裙摆一起跑（实验，默认 0）
#   VALIDATE=0        跳过 Blender 检测
set -euo pipefail

: "${MODEL:?set MODEL=/path/to/target.pmx}"
: "${MOTION:?set MOTION=/path/to/motion.vmd}"
SRC_MODEL="${SRC_MODEL:-$MODEL}"
OUT="${OUT:-out}"
STEP="${STEP:-20}"
PHYSICS="${PHYSICS:-1}"
SKIRT="${SKIRT:-0}"
VALIDATE="${VALIDATE:-1}"
BLENDER="${BLENDER:-blender}"
if [ -z "${MR:-}" ]; then
  if [ -x ".venv/bin/python" ]; then MR=".venv/bin/python -m mmd_retarget"; else MR="python -m mmd_retarget"; fi
fi

mkdir -p "$OUT"
echo "== 1/6 skeleton profiles =="
$MR skeleton "$SRC_MODEL" -o "$OUT/src.json"
$MR skeleton "$MODEL" -o "$OUT/dst.json"

echo "== 2/6 canonical =="
$MR inspect "$MOTION" -p "$OUT/src.json" -o "$OUT/motion.json"

echo "== 3/6 retarget =="
$MR retarget "$OUT/motion.json" -s "$OUT/src.json" -t "$OUT/dst.json" \
  -o "$OUT/retargeted.vmd" -c configs/retarget.json

if [ "$PHYSICS" = "1" ]; then
  echo "== 4/6 physics =="
  extra=""
  [ "$SKIRT" = "1" ] && extra="--skirt"
  $MR physics "$OUT/motion.json" -p "$OUT/dst.json" \
    -o "$OUT/motion_phys.json" --vmd "$OUT/final.vmd" \
    -c configs/physics.json $extra
else
  cp "$OUT/retargeted.vmd" "$OUT/final.vmd"
fi

if [ "$VALIDATE" = "1" ]; then
  echo "== 5/6 validate =="
  "$BLENDER" -b --python tools/blender_cli.py -- validate \
    --model "$MODEL" --motion "$OUT/final.vmd" \
    -o "$OUT/report.csv" --json "$OUT/report.json" \
    --step "$STEP" --visibility \
    --thumbnails "$OUT/thumbs" --contact-sheet "$OUT/sheet.html"
  echo "== 6/6 done =="
else
  echo "== 5/6 validate skipped =="
fi

echo
echo "输出目录: $OUT"
ls -lh "$OUT" | sed -n '1,20p'
