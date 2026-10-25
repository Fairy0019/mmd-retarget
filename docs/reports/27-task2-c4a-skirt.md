# 任务 2 · 裙摆 C4-A 权重转移验收

- 日期：2026-10-25
- 计划：`docs/plans/2026-10-26-server-next.md` 任务 2
- 对象：薇斯纳 + 恋爱循环 0–299 帧（step 5）
- 结论：**未通过**。权重转移没有降低 `leg-skirt` high；叠加物理后 max depth
  还变差。按设计转路线 B（布料），不再调骨链参数。

---

## 1. 权重转移

```bash
# 干跑
blender -b scene_accept.blend --python tools/skirt_reweight.py -- \
  --out scene_rw.blend --materials 裙,裙内 --dry-run
# 实际
blender -b scene_accept.blend --python tools/skirt_reweight.py -- \
  --out scene_rw.blend --materials 裙,裙内
```

| 项 | 数值 |
|---|---:|
| 裙片顶点 | 3,049 |
| 需要改权重 | **547**（18.0%） |
| 裙骨 | 117 |
| 耗时 | 2.0 s |

改权重后，frame 201 的裙片顶点有 88 个位移 > 1 mm，最大 71 mm——权重
确实生效了。

## 2. 数值对比

场景：`scene_accept.blend` / `scene_rw.blend`，相机 `机位_近景`，
0–299 帧 / step 5 / `--visibility`。三组：

| 组 | leg-skirt 记录 | high | 可见 high | max depth |
|---|---:|---:|---:|---:|
| 原始 | 45 | 17 | 16 | 58.57 mm |
| C4-A 权重 | 45 | **17** | **16** | **58.57 mm** |
| C4-A + 物理 | 45 | **17** | **17** | **61.25 mm** |

- 只改权重：high 持平（17=17），max 完全一样；只有 11 条记录的深度
  有 >0.01 mm 变化，且都不在最坏的帧；
- 叠加 `physics --skirt`：high 仍 17，但 max 58.57→61.25，可见 high +1。

## 3. 视觉

frame 200 clay 对比（同机位/同光照）：

- 轮廓几乎一致；
- 没有明显接缝或权重撕裂；
- 但也没有任何可见改善——裙子仍然贴着腿。

## 4. 判读

C4-A 的假设是“裙片被腿/骨盆权重拖走”。实测：

- 547 个顶点确实从腿/骨盆转到了 Q 骨；
- 但**最坏的 leg-skirt 帧不在这些顶点上**，或者 Q 骨的运动与腿足够接近，
  导致深度没有变化；
- 物理叠加后，裙骨链把裙片推得更远，反而增加 max depth——与报告 17 的
  “骨链不是布料”结论一致。

## 5. 决定

1. C4-A 工具保留，但**不作为默认流程**；不写进 demo/QUICKSTART；
2. 不调 `skirt_shape_stiffness` / `collision_margin_units` / `use_mesh_radius`
   ——报告 17/19 已证明是负结果；
3. 下一阶段按 `docs/design/C4-skirt.md` 路线 B：布料代理 + 骨链烘焙；
4. 在路线 B 完成前，`physics --skirt` 仍默认关闭。

## 6. 附带修复

跑 `blender -b scene.blend --python tools/blender_validate.py` 时发现：
打开已有 .blend 后 MMD Tools 扩展未启用，导入 VMD 报
`operator could not be found`。

修复：`validate_blender.run_validation` 在导入前无条件
`addon_enable("bl_ext.user_default.mmd_tools")`（失败则忽略）。
这属于工具链 bug，未单独开复盘（影响面仅 Blender 端验证入口）。
