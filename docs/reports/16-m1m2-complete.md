# M1 stage 5 + M2 stage 4：间隙约束、twist、检测能力补齐

- 日期：2026-10-24
- 版本：v0.0.3
- 测试：**87 passed**
- 范围：M1 剩余项（间隙、twist、骨盆补偿诊断）+ M2 剩余项（规则配置、多点可见性、多机位、contact sheet）

---

## 1. M1 新增

### 1.1 手臂间隙约束

- 从 `skeleton_profile.colliders` 取**躯干类**胶囊（排除手臂/腿自身，否则会把自己判成穿模）；
- 每帧把胶囊端点随骨骼变换到世界，检查**手腕、肘、前臂中点**到胶囊表面的余量；
- 有穿透时沿最近点方向推手腕目标，重解两骨 IK；单帧最大 8cm（可配），迭代 2 次；
- **意图接触白名单**：只有“目标比源更穿”才推。源动作里手贴着小腹的帧保留。

### 1.2 twist 恢复

- 两骨 IK 需要把链当直线，解算前会清掉 `腕捩/手捩`；
- 解算后把**绕骨轴**的分量加回去（绕轴旋转不改变手腕位置）；
- 轴角从**局部旋转**提取（用世界旋转会把整条手臂摆动算进来，第一版踩过）；
- `factor` 默认 0.5，对应 MMD 常见的捻り。

### 1.3 骨盆补偿（诊断）

- 对 53 / 46 个“够不到”的窗口，报告需要的 root 位移（最大 177 / 184 mm）；
- **未自动应用**：canonical 的脚位置目前是 root 相对量，直接位移 root 会让 Blender 里的
  脚和统计模型不一致。需要先统一“脚世界坐标 = root + IK 位移”的口径（M1 stage 6）。

### 1.4 修掉一个 IK 兜底 bug

极向量与目标轴共线时，旧的垂直向量兜底算出了 `(0,0,0)`，导致肘部落回轴上、
两骨长度不成立（手臂完全伸直时手腕位置回到错误值）。改为取任意稳定垂直方向。

---

## 2. M2 新增

| 能力 | 做法 |
|---|---|
| 部位规则配置化 | 新模块 `parts.py`，材质/骨骼关键字、左右命名（`左腕` 与 `腕.L` 都支持）、pair 与 outside 规则均可 JSON 覆盖 |
| 多点可见性 | 取最深的 k 个点（默认 3），按可见比例输出 `yes / partial / no`，新增 `visible_ratio` 列 |
| 多机位 | `--camera a,b`；逐机位判定写入 `visible_cameras`，任一机位可见即视为可见 |
| contact sheet | 纯 Python 生成 HTML 网格（按 severity 排序、可点击），不依赖 PIL |
| CSV/JSON | 新增 `visible_ratio`、`visible_cameras` 字段；旧 CSV 仍可读 |

---

## 3. 实测

### 3.1 同模型（薇斯纳 → 薇斯纳）

| 项 | 数值 |
|---|---|
| 身高比例 | 1.0000 |
| 手腕误差 | mean 0 / max 0 单位 |
| 间隙推离 | 0 帧（源与目标同体型，全部判为意图接触） |
| twist | 1 根（左腕捩，峰值 6.3°），均值 2.9° |
| 骨盆诊断 | 53 帧，最大 177.1 mm |
| 脚锁 | 1708 帧 / 15.1%，滑步 0.1541 → 0.0298 |

### 3.2 跨模型（薇斯纳 → Lumine Tactical）

| 项 | 数值 |
|---|---|
| 身高比例 | 0.8871（20.76 → 18.42 单位） |
| 手腕误差 | mean 0 / max 0 单位 |
| 间隙推离 | **338 帧**，均值 19.9 mm，最大 60 mm（上限）；意图接触保留 1314 帧 |
| twist | 1 根，均值 2.9° |
| 骨盆诊断 | 46 帧，最大 183.8 mm |
| 脚锁 | 1639 帧 / 14.5%，滑步 0.1541 → 0.0254 |
| 脊柱链 | 3 段（spine / spine2 / spine3） |

> 跨模型是本项目第一次用“体型不同的两副骨架”跑完整管线，比例逻辑不再是合成测试。

### 3.3 M2 检测（真实场景，两机位）

```bash
blender -b scene.blend --python tools/blender_validate.py -- \
  --out report.csv --step 30 --start 0 --end 5640 \
  --visibility --visibility-points 3 \
  --camera "机位_近景,摄像机" \
  --thumbnails thumbs --contact-sheet sheet.html
```

| 项 | 数值 |
|---|---|
| 部位面数 | torso 19225 / hair 21070 / skirt 2271 / wings 3712 / 四肢 2338–3523 |
| 记录 | 682 条（high 18 / medium 379 / low 285） |
| 耗时 | 37.5 s（141 帧 + 缩略图） |
| contact sheet | 17 帧 |
| high 分布 | 全部为腿–裙（与报告 12 一致） |

示例：

```csv
frame,part_a,part_b,depth_mm,pairs,visible,visible_ratio,visible_cameras,severity,suggestion
600,leftLeg,skirt,61.288,200,yes,0.667,"机位_近景:yes;摄像机:yes",high,physics:skirt
1110,leftLeg,skirt,30.059,200,no,0.0,"机位_近景:no;摄像机:no",high,physics:skirt
```

---

## 4. 边界（仍然是近似）

- 间隙用**胶囊**而不是真实网格，手臂贴身但未穿透时可能不触发；
- 可见性是**射线**单点/多点采样，不是像素级遮挡；`partial` 表示部分采样点可见；
- 部位规则默认针对日文 MMD 模型，换模型需提供 `--parts-config`；
- 骨盆补偿只给诊断数字，未自动改 root；
- 跨模型只验证了一对（薇斯纳 → Lumine），比例与 rest/roll 的普适性仍待更多模型。

## 5. 复现

```bash
# M1（纯 Python）
mmd-retarget skeleton model.pmx -o target.json
mmd-retarget inspect motion.vmd -p source.json -o motion.json
mmd-retarget retarget motion.json -s source.json -t target.json -o out.vmd

# M2（Blender）
blender -b scene.blend --python tools/blender_validate.py -- \
  --out report.csv --visibility --camera "camA,camB" \
  --thumbnails thumbs --contact-sheet sheet.html
```
