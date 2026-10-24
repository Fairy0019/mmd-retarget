# 架构

## 1. 模块

| 模块 | 职责 | 依赖 |
|---|---|---|
| `vmd` | VMD 读写：Shift-JIS 15 字节骨名、30fps、贝塞尔插值、morph、相机 | 无 |
| `pmx` | PMX 读取：骨骼 rest/层级、权重、材质（最小集） | 无 |
| `skeleton` | 生成 `skeleton_profile`：骨长、rest 矩阵、roll、限位、语义映射 | `pmx` |
| `canonical` | 动作的模型无关表示（语义关节 + 根轨迹 + 接触段 + morph） | `vmd` |
| `retarget` | 比例/rest 适配、承重/脚锁、骨盆补偿、手臂 IK/间隙、twist、平滑 | 纯 Python |
| `physics` | 被动件骨链 PBD（重力/阻尼/距离约束/胶囊碰撞） | 纯 Python |
| `parts` | M2 部位规则（材质/骨骼关键字、左右命名、pair、outside 规则） | 无 |
| `validate` | severity、CSV/JSON、回归 diff、summary | 无 |
| `validate_blender` | 网格 BVH、穿透深度、可见性、缩略图、contact sheet | Blender bpy |
| `writer` | 目标模型的 VMD 导出 | `vmd` |
| `cli` | 子命令：skeleton / inspect / retarget / physics / validate | 以上 |

> 解析层（`vmd` / `pmx`）刻意不依赖 Blender，便于单测与 C++ 下沉。

## 2. 数据模型

### 2.1 `canonical_motion.json`（schema 1）

```jsonc
{
  "schema": 1,
  "fps": 30,
  "frames": 5640,
  "source": { "model": "初音ミク", "vmd": "motion.vmd", "profile": "miku.json" },
  "root": {
    "pos": [ [0, 0,0,0] ],
    "rot": [ [0, 0,0,0,1] ]
  },
  "joints": {
    "leftUpperArm": [ [0, 0,0,0,1], [1, -0.02,0,0.01,0.999] ]
  },
  "translations": { "leftFootIK": [ [0, 0.1,1.2,0] ] },
  "extra": { "ﾈｸﾀｲ１": [ [0, 0,0,0,1] ] },
  "extra_translations": { "左袖": [ [0, 0,0,0] ] },
  "contacts": [
    { "start": 120, "end": 168, "effector": "leftFoot",
      "pos": [0.1,0.0,0.02], "min_y": 0.01,
      "mean_slide": 0.02, "max_slide": 0.06 }
  ],
  "morphs": { "まばたき": [ [0,0.0], [12,1.0], [16,0.0] ] }
}
```

- 关节用**语义名**（`leftUpperArm`），与模型解耦；
- 旋转用四元数 `[x,y,z,w]`，与帧号成对；
- `root` 的 pos / rot 分开存：VMD 里两者关键帧时刻经常不同；
- `extra` 是**没有语义映射**的骨（头发/裙/袖），同模型 round-trip 时
  原样透传，换模型时丢弃；物理件由 M3 重新模拟；
- 接触段是**区间**，不是单帧；`mean_slide` / `max_slide` 记录源动作在
  该段内的滑步量（单位/帧），供 M1 判断锁定强度。

### 2.2 `skeleton_profile.json`

```jsonc
{
  "model": "薇斯纳",
  "map": { "leftUpperArm": "腕.L", "leftLowerArm": "ひじ.L" },
  "rest": {
    "腕.L": { "head": [..], "tail": [..], "roll": 0.0, "parent": "肩.L" }
  },
  "limits": { "ひじ.L": { "min": [0,0,0], "max": [0,0,2.4] } },
  "colliders": [
    { "bone": "上半身", "type": "capsule", "radius": 0.11, "a": [..], "b": [..] }
  ]
}
```

### 2.3 `configs/retarget.json`

配置统一用 JSON；文件只需写想覆盖的字段，其余走 `DEFAULT_CONFIG`。

```jsonc
{
  "foot_lock": {
    "enabled": true,
    "chunk_frames": 20,
    "max_lock_drift_m": 0.04,
    "pelvic_compensation": { "mode": "apply", "max_shift_m": 0.08 }
  },
  "arm_ik": { "clearance_m": 0.015, "max_push_m": 0.06 },
  "twist": { "enabled": true, "factor": 0.5 },
  "smoothing": { "max_rate_m_per_frame": 0.01 }
}
```

### 2.4 报告

```csv
frame,part_a,part_b,depth_mm,visible,severity,suggestion
921,hand,torso,38.2,yes,high,retarget:arm_ik
```

## 3. 关键算法

### 3.1 Rest-relative retarget

不直接复制局部四元数，而是计算**世界空间旋转增量**：

```
ΔR_world = R_source_world(t) · R_source_rest⁻¹
R_target_world(t) = ΔR_world · R_target_rest
```

再转换回目标骨骼的局部空间。这样 rest pose / roll 的差异被吸收，
不会出现"整体偏内 3°"的系统误差。

### 3.2 脚锁

1. 用脚踝世界速度 + 高度阈值检测接触段；
2. 接触段内锁定脚的世界位置（允许 ≤5mm 漂移）；
3. 用腿 IK 解算，骨盆做高度补偿。

### 3.3 手臂 IK + 间隙

- 目标：源动作的手腕世界轨迹；
- 约束：手/肘与躯干、裙摆胶囊保持 ≥1.5cm；
- 极向量取源肘方向，避免肘部翻转；
- 若所需推离 > 8cm，标记为"编舞不可行"，交人工。

### 3.4 时间平滑

对**修正量**（而不是相交计数）做 `膨胀 → 平均 → 限速`：

```
push_raw[t]  = 清干净所需推离
push_dil[t]  = max(push_raw[t-k .. t+k])
push_smooth  = mean(push_dil[t-2 .. t+2])
push_final   = clamp_rate(push_smooth, max_rate)
```

> 先膨胀再平均：否则单帧尖峰会被平均抹平，导致该帧完全不修。

### 3.5 被动件 PBD

- 每条骨链：Verlet 积分 + 距离约束 + 阻尼；
- 碰撞体：胶囊/球（不用原网格）；
- 单帧最大修正角限制（5–12°），避免"芭蕾裙"；
- 结果转成骨骼旋转，烘焙关键帧。

### 3.6 可见性

把相交面片投影到最终机位，结合深度缓冲判断是否被遮挡；
只有**可见像素上的穿透**记为 `high`。

## 4. 运行方式

```bash
# 1) 生成目标骨架档案
blender -b --python -m mmd_retarget.cli -- skeleton model.pmx -o profile.json

# 2) 转成 canonical motion
python -m mmd_retarget.cli inspect motion.vmd -o motion.json

# 3) 重定向
python -m mmd_retarget.cli retarget motion.json -s src.json -t dst.json -o out.vmd --config retarget.yaml

# 4) 被动件物理
blender -b scene.blend --python -m mmd_retarget.cli -- physics --config physics.yaml

# 5) 验收
blender -b scene.blend --python -m mmd_retarget.cli -- validate --camera final --out report.csv
```

> 2)–3) 纯 Python 可脱离 Blender 运行；1) 4) 5) 需要 bpy。

## 5. 目录规划

```
src/mmd_retarget/
├── vmd.py          # VMD 读写
├── pmx.py          # PMX 读取
├── skeleton.py     # profile 生成
├── canonical.py    # 动作标准化
├── retarget.py     # 重定向
├── physics.py      # PBD
├── validate.py     # 检测
├── writer.py       # 导出
└── cli.py
tests/
examples/           # 只用自制/授权素材
```
