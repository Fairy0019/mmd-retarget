# 任务 1.1 · 头发分组验收

- 日期：2026-10-25
- 计划：`docs/plans/2026-10-26-server-next.md` 任务 1.1
- 对象：薇斯纳 + 恋爱循环，canonical 全片 5,640 帧
- 结论：**通过**。分组版 `hair-torso` 不高于对照组，侧发碰撞更少。

---

## 1. 方法

同一份 canonical / profile，只改 `hair_groups.side`：

| 组 | 配置 |
|---|---|
| 默认（分组） | `side: {gravity_scale: 0.7, max_angle_deg: 8, shape_stiffness: 0.08}`，`back: {}` |
| 对照（不分组） | `side` 显式改成与 back/global 相同：`gravity_scale 1.0 / max_angle 12 / stiffness 0.05` |

```bash
mmd-retarget physics motion.json -p profile.json \
  -o phys_default.json --vmd phys_default.vmd -c configs/physics.json

mmd-retarget physics motion.json -p profile.json \
  -o phys_control.json --vmd phys_control.vmd -c /tmp/physics_control.json

blender -b --python tools/blender_cli.py -- validate \
  --model 薇斯纳.pmx --motion phys_*.vmd \
  -o hair_*.csv --step 20 --no-markers
```

物理耗时：各 **47 s**（5,640 帧，仅头发）。

## 2. 结果

| 指标（hair–torso） | 默认（分组） | 对照（不分组） |
|---|---:|---:|
| 记录数 | **238** | 240 |
| high（≥30 mm） | 0 | 0 |
| ≥10 mm | 13 | 13 |
| ≥5 mm | **76** | 82 |
| 中位深度 | **4.322 mm** | 4.405 mm |
| 平均深度 | **4.989 mm** | 5.039 mm |
| 最大深度 | 16.286 mm | 16.286 mm |
| 侧发 collision pushes | **8,216** | 8,498 |

全片 high：

| | 默认 | 对照 |
|---|---:|---:|
| high | 47 | 47 |
| max depth | 67.36 mm | 67.36 mm |

全片 high 的 47 条仍然全部是腿–裙（与报告 12/17 一致），头发分组不影响它。

## 3. 判读

- **通过标准**：分组版不高于对照组。high 持平（0），max 持平，
  记录数/中位/平均/≥5 mm 都略低；
- 侧发 pushes 从 8,498 降到 8,216（-3.3%），说明 side 组更轻的参数
  确实减少了侧发与肩膀的碰撞；
- 最大 16.3 mm 在两组完全相同（frame 1420），说明它不是侧发参数能解决的，
  更可能是背后长发/固定姿势，需要分组以外的碰撞体或造型调整。

## 4. 风险

- 只验证了一副模型、一段动作；换长发/短发模型需要重跑；
- 分组依据是骨名（`左/右/.L/.R`），命名不规范的模型会全部落到 `back`；
- 数值低不等于好看：侧发摆幅变小可能显得“贴头”，需要视觉验收（任务 1.5）。

## 5. 结论

任务 1.1 **通过**。保留默认分组参数。
