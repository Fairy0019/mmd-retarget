# C4-B：裙摆布料代理（工具已实现，未做视觉验收）

- 日期：2026-10-26
- 版本：v0.1.2
- 测试：102 passed（未新增单测，纯 Blender 工具）
- 状态：**脚本可运行（5 帧冒烟通过），300 帧/全片与视觉验收待做**

---

## 1. 为什么是“布料 → 骨骼”

直接把布料网格作为成品会打断 VMD/渲染管线。这里让布料只负责**生成形状**，
最终烘焙回 `Q_*` 骨，原网格/材质/权重都不动。

流程：

```
复制裙片面 → SkirtCloth 代理
  腰部 pin（Q_0_* 权重，退化用最高 12% 顶点）
  身体低模 + Collision
  顺序推进帧（布料自己填 cache）
  第一遍：每帧每根 Q 骨的顶点质心（此时 Q 骨仍 identity，避免二次变换）
  第二遍：质心 → Q 骨旋转，写入 Action（单帧 ≤12°）
  删除代理，保存 .blend
```

## 2. 为什么不用 `ptcache.bake_all`

这个模型有 447 个 `Child Of` 刚体，场景里存在一个 **5640 帧的 rigid body
cache**；`bake_all` 会连它一起烘，5 帧的任务会变成 5640 帧（实测卡住）。

因此改为**顺序帧推进**：布料在 `frame_set` 时自行填充内存 cache，采样一遍
即可。代价是不能中断续跑，全片需要一次跑完。

## 3. 冒烟测试（5 帧）

```bash
blender -b scene.blend --python tools/skirt_cloth.py -- \
  --out /tmp/cloth5.blend --start 1 --end 5 --quality 1
```

| 项 | 结果 |
|---|---|
| 裙片材质 | 3 个（25/26/37） |
| pin 顶点 | 218 / 3049 |
| 链/骨 | 15 链 / 117 骨 |
| 采样 | 5 帧 × 117 骨 |
| Q 骨旋转 | 逐帧变化（非线性） |
| 代理清理 | `SkirtCloth` / `BodyCollision` 已删除 |
| 场景范围 | 恢复 1..5640 |
| Action | 1079 条曲线（原 611 + Q 骨 468） |

## 4. 用法

```bash
# 300 帧试验（先低质量确认稳定）
blender -b scene.blend --python tools/skirt_cloth.py -- \
  --out scene_cloth.blend --start 1 --end 300 --quality 3

# 全片（较慢，建议服务器跑）
blender -b scene.blend --python tools/skirt_cloth.py -- \
  --out scene_cloth.blend --start 1 --end 5640 --quality 6
```

参数：`--materials`、`--bones`、`--quality`、`--mass`、`--bending`、
`--collision-distance`、`--proxy-ratio`、`--max-angle-deg`、`--dry-run`。

## 5. 未验证 / 风险

1. **没有视觉验收**：5 帧只证明链路通，不证明好看；
2. **布料参数未经调参**：quality/mass/bending 只是默认值；
3. **薄片隧穿**：布料与低模碰撞代理可能互穿；
4. **长序列稳定性**：5640 帧未跑，可能抖动/漂移；
5. **无断点续跑**：顺序采样，中断要重来；
6. **与 C4-A 的关系**：布料烘焙的是 Q 骨，原网格仍需 Q 骨权重
   （先跑 `skirt_reweight.py`，或模型自带 Q 权重）。

## 6. 下一步

1. 服务器跑 300 帧（quality 3），用 `render_acceptance.py` 出 10 张图；
2. 与 C4-A/原始做 contact sheet 对比；
3. 通过后再全片；不通过调 `--mass/--bending/--quality`，不要改骨链参数。
