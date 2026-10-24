# M3：被动件骨链物理（头发启用，裙摆暂缓）

- 日期：2026-10-24
- 版本：v0.0.4
- 测试：**92 passed**
- 结论：**骨链 PBD 适合头发；裙摆需要布料/权重方案，骨链会把腿顶穿。**

---

## 1. 实现

新模块 `src/mmd_retarget/physics.py`：

- 骨链发现：裙 `Q_{seg}_{chain}`（15 条）、发 `髮_*` / `髮2_*` / `左髮_*` / `右髮_*`（4 条）；
- Verlet 积分：重力、阻尼、子步、相邻距离约束；
- 碰撞：躯干/腿/手/翅膀胶囊（翅膀按骨链生成静态胶囊），逐帧随骨骼变换；
- 形状匹配（可选）：向“身体坐标系下的 rest 位置”回拉，防止裙摆塌陷；
- 输出：逐帧骨骼局部旋转写入 canonical `extra`，由 writer 原样写出；
- 限速与单帧角度上限（默认 12°），避免“芭蕾裙”和抖动；
- CLI：`mmd-retarget physics motion.json -p profile.json -o out.json [--vmd out.vmd]`。

配置（`DEFAULT_CONFIG`）关键项：

```jsonc
{
  "gravity_m_s2": 9.8,
  "damping": 0.985,
  "iterations": 4,
  "substeps": 2,
  "max_step_units": 0.6,
  "max_angle_deg": 12.0,
  "chains": {"skirt": false, "hair": true},
  "skirt_shape_stiffness": 0.0,
  "hair_shape_stiffness": 0.05,
  "collision_margin_units": 0.0
}
```

## 2. 性能

| 范围 | 帧数 | 耗时 |
|---|---:|---:|
| 300 帧（裙+发） | 300 | 4.7 s |
| 全片（裙+发） | 5,640 | 133 s |
| 全片（仅发） | 5,640 | 约 90 s |

## 3. 实测

### 3.1 二次运动幅度（对比原始动作）

| 骨骼 | 最大位移 |
|---|---:|
| `髮_5` | 6.1 cm |
| `髮_5.L` | 14.8 cm |
| `髮_5.R` | 9.1 cm |
| `Q_7_5`（裙尖） | 11.3 cm |

发梢和裙摆都有可见的摆动，说明积分和烘焙链路是通的。

### 3.2 穿模检测（282 帧抽样，`--step 20`）

**仅头发（当前默认）**

| 指标 | 原始 | 物理后 |
|---|---:|---:|
| records | 1049 | 1041 |
| high | 51 | **45** |
| max depth | 67.96 mm | **65.85 mm** |

轻微改善，无回归。

**裙 + 发（全开）**

| 指标 | 原始 | 物理后 |
|---|---:|---:|
| high | 47 | **109** |
| max depth | 68.3 mm | 70.8 mm |
| leg–skirt records | 223 | **517** |

裙摆骨链把腿顶穿的情况明显变多，属于**负结果**。

### 3.3 两个失败尝试（避免重复）

| 尝试 | 结果 |
|---|---|
| 裙摆形状匹配 0.25 | 300 帧 high 0 → 15；裙摆回到刚性位置，腿直接穿出去 |
| 碰撞余量 +0.2 单位 | 300 帧 high 0 → 1，max depth 27.9 → 46 mm；把裙子推得过远，反而在别的部位穿得更深 |

## 4. 为什么裙摆不行

- 骨链只约束**骨骼点**，裙片网格相对骨链有偏移（内衬、下摆、厚度）；
- 腿胶囊半径是粗估，骨链被推到胶囊外，网格仍可能被腿顶穿；
- 裙摆没有弯曲刚度，重力下会塌向腿，形状匹配又把它拉回刚性姿态，两头不讨好；
- 这正是 `docs/NEXT.md` 里 C4 的判断：**裙摆需要布料模拟或重新刷权重**，骨链只能做“摆”，不能做“壳”。

因此默认：`chains.skirt = false`，头发开启；`--skirt` 可显式开启做实验。

## 5. 复现

```bash
# 生成（默认：头发）
mmd-retarget physics motion.json -p profile.json -o motion_phys.json --vmd out.vmd

# 也启用裙摆（实验）
mmd-retarget physics motion.json -p profile.json -o motion_phys.json --vmd out.vmd --skirt

# 只跑头发
mmd-retarget physics motion.json -p profile.json -o motion_phys.json --no-skirt
```

## 6. 边界

- 骨链不是布料：没有褶皱、自碰撞、厚度；
- 头发没有分组（背后/肩前）；侧发和长发用同一套参数；
- 翅膀是静态胶囊，不参与模拟；
- 碰撞是胶囊近似，`--step` 越小检测越细；
- 全片烘焙约 2 分钟，结果确定、可回滚。

## 7. 下一步

1. **裙摆 C4-A/B**：布料模拟或重新刷权重（优先），不要再调骨链参数；
2. **头发分组**：背后长发与肩前侧发分开参数，减少 `hair-torso`；
3. **与 M2 回归门槛接 CI**：每次改物理参数跑 30 秒样本；
4. 全片渲染前，用 `validate` 确认 high 不增加。
