# 阶段报告 11 · M2 stage 1 BVH 穿模检测与报告

- 日期：2026-10-24
- 范围：`src/mmd_retarget/validate.py`、`validate_blender.py`、`tools/blender_validate.py`、CLI `validate`
- 结论：**BVH 检测、severity、CSV、回归 diff 已可用**；可见性、缩略图、
  精确穿透深度尚未完成。M2 标记为 stage 1/2。

---

## 1. 实现

### 1.1 部位划分

不按材质硬切，而是两层规则：

1. 材质名含 `裙` / `髮` / `翼` → 裙子 / 头发 / 翅膀；
2. 其余按**主导骨骼**分：`左/右 + 肩腕ひじ手首` → 手臂，
   `左/右 + 足ひざつま先` → 腿，`上半身/下半身/腰/首/頭/センター` → 躯干。

`裙内` 内衬不参与检测——腿在裙子内部是正常的，只有穿过外层才算穿模
（但外层的正反面并不总是可靠，见 §4）。

### 1.2 检测

每帧：

1. `evaluated_get(depsgraph)` 拿变形后的网格；
2. 每个部位用 `BVHTree.FromPolygons` 建 BVH；
3. 对 8 个部位对做 `overlap`；
4. 对重叠三角形对，取三角形顶点到对方 BVH 的最近点；用
   `dot(normal, p - nearest)` 判断在表面内侧还是外侧；
5. 深度取最大距离，换算成 mm（按 1.6 m 身高 / 骨骼最高点）。

部位对：

```
leftArm-torso, rightArm-torso,
leftArm-skirt, rightArm-skirt,
leftLeg-skirt, rightLeg-skirt,
hair-torso, wings-torso
```

### 1.3 报告

CSV 字段：

```csv
frame,part_a,part_b,depth_mm,pairs,visible,severity,suggestion
200,rightLeg,skirt,32.006,180,unknown,high,physics:skirt
```

- severity：`>=30mm high`、`>=10mm medium`、`>=2mm low`；
- suggestion 按部位对给出（`retarget:arm_ik` / `physics:skirt` 等）；
- `visible` 目前固定 `unknown`（没有最终机位）；
- high 帧可选在 Blender 时间轴打 marker。

回归 diff 按键 `(frame, part_a, part_b)` 比较最大深度，输出
`new / fixed / worse / better`。

## 2. 真实动作结果

源动作，采样 282 帧（每 20 帧），耗时 **24 s**：

```
records  : 1,051
severity : high 52 / medium 572 / low 427
max depth: 67.96 mm
```

按部位对：

| 对 | 记录数 | 最大深度 |
|---|---|---|
| leftArm–torso | 282 | 31.0 mm |
| rightArm–torso | 266 | 25.5 mm |
| hair–torso | 241 | 15.2 mm |
| leftLeg–skirt | 107 | 68.0 mm |
| rightLeg–skirt | 102 | 65.2 mm |
| rightArm–skirt | 40 | 18.4 mm |
| leftArm–skirt | 13 | 14.1 mm |

解读：

- **手臂–躯干**：几乎每一帧都有 10–31 mm 的重叠，是 M1 手臂 IK/间隙
  约束要解决的主要问题；
- **头发–躯干**：长发贴背，4–15 mm，多数是正常接触/被遮挡，需要可见性
  才能定级；
- **腿–裙子**：60 mm 级别的“穿模”很可能是腿在裙子**内部**、或裙子
  内外层法线不一致导致的误报，不能直接当 high 处理。

## 3. 重定向结果对比

把报告 10 的输出（`retargeted9.vmd`）用同一套检测跑一遍：

```
records  : 1,097
severity : high 76 / medium 580 / low 441
max depth: 65.40 mm
diff     : new 109, fixed 63, worse 168, better 174
```

结论：**M1 stage 3 没有降低穿模**。原因很明确：

- 手臂 IK/间隙约束还没做，手臂–躯干的重叠不会因为脚锁/脊柱链而消失；
- 脊柱链拆分改变了胸口朝向，部分帧变好、部分变差；
- 脚锁只影响脚，不影响上半身。

这份 diff 的价值不是“证明重定向有效”，而是**建立了回归基线**：
以后每次改 retarget，都可以用同一份 CSV 看 new/fixed/worse/better。

## 4. 漏洞与风险

### 4.1 深度是近似值

用顶点到对方表面的最近距离，不是精确的体积交。三角形边穿过但顶点都在
外面的情况会漏检；`overlap` 也可能包含 broad-phase 假阳性。

**定位**：这份报告适合“找问题帧”，不适合做毫米级验收。M2 验收口径是
人工 1 小时内定位 high 帧，当前精度够用。

### 4.2 衣物内外层

`裙内` 已排除，但外层裙面是开放/双面壳体，法线方向不稳定。
“腿在裙子里面”与“腿穿出裙子”用同一个 `dot` 判据无法可靠区分。
需要：

- 给裙子标内外层（材质或法线一致性）；
- 或者用“腿的顶点是否在裙子闭合体积外”做判定；
- 或者把腿–裙结果降级为 `candidate`，等 M3 物理后再验。

### 4.3 没有可见性

`visible=unknown`，severity 只按深度。头发/裙子的很多 high 可能在最终
机位完全看不见。M2 的下一 stage 必须加：

1. 场景相机（或配置机位）；
2. 从相机向穿透点发射射线，判断是否被其他几何遮挡；
3. 只在可见时保留 `high`，否则降为 `hidden`。

### 4.4 采样会漏单帧尖峰

`--step 20` 是 0.67 秒一帧，单帧穿刺可能漏掉。最终验收应至少
`--step 1`（全帧），成本约 24 s × 20 ≈ 8 分钟，可接受。

### 4.5 部位划分靠骨骼名

`Bone_CapeDecor01_L`、`髮_13` 这类非标准名会落到 `other`，不参与检测。
当前模型的披肩/头饰就没有被覆盖。需要一张可配置的部位规则表，而不是
硬编码日文关键字。

### 4.6 没有缩略图

high 帧的快速人工确认还需要渲染缩略图/contact sheet。当前只能靠
Blender 手动跳帧。

## 5. 用法

```bash
# 独立运行（推荐）
blender -b --python tools/blender_validate.py -- \
  --model /path/model.pmx \
  --motion /path/motion.vmd \
  --out report.csv --step 20 --markers

# 或在已加载场景的 Blender 里
blender -b --python tools/blender_cli.py -- validate -o report.csv --step 20

# 回归对比
blender -b --python tools/blender_cli.py -- validate \
  --model model.pmx --motion out.vmd -o new.csv --diff old.csv
```

## 6. 测试

- 纯 Python：severity 阈值、CSV 往返、diff、summary，共 6 个测试；
- Blender 端：在真实 63k 顶点模型 + 5,640 帧动作上跑通，282 帧 / 24 s；
- 全仓：**75 passed**。

## 7. 下一步（M2 stage 2）

1. 可见性：相机射线 + 遮挡判断，`visible` 落成 yes/no；
2. 全帧检测（step 1）与耗时优化；
3. 衣物内外层判定，降低腿–裙误报；
4. high 帧缩略图/contact sheet；
5. 回归阈值（允许 new/worse 的数量上限，超过则 CI 失败）；
6. 部位规则配置化（JSON），不再硬编码日文关键字。
