# 阶段报告 13 · M2 stage 3 缩略图、JSON 与回归门槛

- 日期：2026-10-24
- 范围：`validate_blender` 缩略图、CLI `--json` / `--max-new` / `--max-worse`
- 结论：M2 的“报告能定位 high 帧”闭环完成。43 个 high 帧已渲染缩略图；
  全量 282 帧 + 可见性 + 缩略图耗时 **126 s**。

---

## 1. 缩略图

每个 high 帧渲染一张 320×320 PNG：

- 相机：`--camera` 指定；否则用默认正面机位；
- 引擎：**Cycles CPU，8 samples**；
- 灯光：没有灯时自动加一盏 Sun；
- 背景：深灰世界；
- 输出：`clip_00410.png`（VMD 帧号补零）。

真实动作（282 帧采样）：

```
high 记录 : 52
唯一帧    : 43
缩略图    : 43 张 / 4.4 MB
总耗时    : 126 s（无缩略图 31 s）
```

### 1.1 Workbench 在服务器上是空的

第一版用 `BLENDER_WORKBENCH`，渲染出来是纯白/纯背景。日志：

```
EGL Error (0x3009): EGL_BAD_MATCH
Error: Trying to bind "Storage" ssbo to slot 8 which is above the reported limit of 8
```

无 GPU 的 headless 环境没有足够的 SSBO slot，Workbench 直接摆烂。
换 **Cycles CPU** 后正常。代价是每张约 2 s，但只渲染 high 帧，可接受。

## 2. JSON 与回归门槛

```bash
# 同时输出 CSV + JSON
blender -b --python tools/blender_cli.py -- validate \
  --model model.pmx --motion out.vmd \
  -o report.csv --json report.json --step 20 --visibility

# 回归：new 不超过 5 条、worse 不超过 10 条，否则退出码 1
blender -b --python tools/blender_cli.py -- validate \
  --model model.pmx --motion out.vmd \
  -o new.csv --diff old.csv --max-new 5 --max-worse 10
```

`--diff` 输出 `new / fixed / worse / better`；超过门槛时打印
`regression: FAILED` 并返回 1，可直接接 CI。

## 3. 当前 M2 能力清单

| 能力 | 状态 |
|---|---|
| BVH 相交 | ✅ |
| 穿透深度（近似） | ✅ 顶点采样 |
| 部位划分 | ✅ 材质 + 主导骨骼 |
| 可见性 | ✅ 单点射线 |
| severity | ✅ 2/10/30 mm |
| CSV | ✅ |
| JSON | ✅ |
| timeline marker | ✅（headless 需保存 .blend 才持久） |
| 缩略图 | ✅ Cycles CPU |
| 回归 diff + 门槛 | ✅ |
| 全帧检测 | ✅（`--step 1`，约 8 min） |

## 4. 漏洞与风险

### 4.1 缩略图是单机位

只有一张正面图，裙子/头发在背面或侧面的穿模可能看不出来。最终验收
应该用最终机位，或者渲染 2–3 个角度。

### 4.2 没有 contact sheet

43 张图要人工逐张看。下一步应拼成 6×8 的 contact sheet，并叠加
frame 号/部位/深度。

### 4.3 默认机位/默认灯光

自动创建的 Sun 和正面机位只为“能看见”，不是审美渲染。不要把缩略图
当交付截图。

### 4.4 marker 不持久

`scene.timeline_markers` 只在内存里；headless 跑完不保存 .blend，
marker 就丢了。需要加 `--save-blend` 或在交互式 Blender 里跑。

### 4.5 单点可见性

报告 12 已说明：只测最深顶点，不是像素覆盖率。缩略图可以人工补足，
但自动 severity 仍可能把“边缘可见”判成 no。

### 4.6 全帧成本

`--step 1` 约 8 分钟（不含缩略图）。如果 high 帧多，缩略图会再放大
10–20 倍。最终验收建议：先 step 10 定位，再对候选区间 step 1 复核。

## 5. 测试

- 纯 Python：76 passed（新增 regression_ok）；
- Blender：6 帧冒烟 + 282 帧全量 + 43 张缩略图，均跑通；
- 缩略图人工抽查：frame 4100 可见角色全身，图像非空。

## 6. 下一步

1. contact sheet + 帧号/部位/深度叠加；
2. 多机位缩略图；
3. `--save-blend` 保存 marker；
4. 穿透区域多点可见性；
5. 部位规则配置化；
6. 把 `--step 1` 的全帧检测接进 CI（先跑 30 秒样本）。
