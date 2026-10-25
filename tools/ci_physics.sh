#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# 物理回归 CI：固定前 900 帧样本，validate --diff 与基线比较。
#
# 用法:
#   MODEL=... MOTION=... ./tools/ci_physics.sh                 # 首次：建基线
#   MODEL=... MOTION=... ./tools/ci_physics.sh                 # 之后：回归检查
#   UPDATE_BASELINE=1 MODEL=... MOTION=... ./tools/ci_physics.sh
#
# 退出码：
#   0 = 通过（new/worse 均为 0）
#   1 = 回归（validate --max-new 0 --max-worse 0 失败）
#   2 = 环境/输入错误
set -euo pipefail

: "${MODEL:?set MODEL=/path/to/target.pmx}"
: "${MOTION:?set MOTION=/path/to/motion.vmd}"
OUT="${OUT:-ci_out}"
STEP="${STEP:-5}"
END="${END:-899}"
BASELINE="${BASELINE:-$OUT/baseline.csv}"
UPDATE_BASELINE="${UPDATE_BASELINE:-0}"
BLENDER="${BLENDER:-blender}"
if [ -z "${MR:-}" ]; then
  if [ -x ".venv/bin/python" ]; then MR=".venv/bin/python -m mmd_retarget"; else MR="python -m mmd_retarget"; fi
fi
mkdir -p "$OUT"

echo "== profiles =="
$MR skeleton "$MODEL" -o "$OUT/src.json" >/dev/null
$MR skeleton "$MODEL" -o "$OUT/dst.json" >/dev/null

echo "== canonical =="
$MR inspect "$MOTION" -p "$OUT/src.json" -o "$OUT/motion.json" >/dev/null

echo "== retarget =="
$MR retarget "$OUT/motion.json" -s "$OUT/src.json" -t "$OUT/dst.json" \
  -o "$OUT/retargeted.vmd" -c configs/retarget.json >/dev/null

echo "== physics =="
$MR physics "$OUT/motion.json" -p "$OUT/dst.json" \
  -o "$OUT/motion_phys.json" --vmd "$OUT/final.vmd" \
  -c "${PHYSICS_CONFIG:-configs/physics.json}" ${PHYSICS_EXTRA:-} >/dev/null

echo "== validate 0..$END step $STEP =="
DIFF_ARGS=()
if [ -f "$BASELINE" ] && [ "$UPDATE_BASELINE" != "1" ]; then
  DIFF_ARGS=(--diff "$BASELINE" --max-new 0 --max-worse 0)
fi

"$BLENDER" -b --python tools/blender_cli.py -- validate \
  --model "$MODEL" --motion "$OUT/final.vmd" \
  -o "$OUT/report.csv" --json "$OUT/report.json" \
  --step "$STEP" --start 0 --end "$END" --no-markers "${DIFF_ARGS[@]}"

if [ ! -f "$BASELINE" ] || [ "$UPDATE_BASELINE" = "1" ]; then
  cp "$OUT/report.csv" "$BASELINE"
  echo "== baseline updated: $BASELINE =="
fi
echo "== CI OK =="
