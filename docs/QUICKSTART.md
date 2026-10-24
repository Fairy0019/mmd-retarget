# 30 分钟跑通

> 目标：从零到「目标模型的 VMD + 可读的穿模报告」。
> 不需要任何模型/动作素材入库；命令里的路径换成你自己的文件即可。

---

## 0. 环境

| 项 | 要求 |
|---|---|
| Python | 3.11+（开发环境 3.12） |
| Blender | 5.x（仅 `validate` / 缩略图需要） |
| MMD Tools | Blender 扩展 `bl_ext.user_default.mmd_tools` |
| 素材 | 源/目标 `.pmx`，一个 `.vmd`（版权归原作者） |

```bash
git clone https://github.com/Fairy0019/mmd-retarget
cd mmd-retarget
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest -q                 # 95 passed
mmd-retarget --version    # mmd-retarget 0.1.0
```

如果 `mmd-retarget` 不在 PATH，用 `python -m mmd_retarget`。

---

## 1. 看输入

```bash
mmd-retarget inspect src.pmx
mmd-retarget inspect motion.vmd
```

重点确认：

- 模型骨骼数、morph 数、是否有 `左足ＩＫ/右足ＩＫ`；
- 动作的帧范围、骨骼数、morph 数；
- 动作骨名是否和模型一致（`センター` / `上半身` / `左腕`…）。

如果动作是给另一副骨架做的，骨名不一致是正常的——下一步的 profile 会做
语义映射。

## 2. 生成骨架档案

```bash
mmd-retarget skeleton src.pmx -o src.json
mmd-retarget skeleton dst.pmx -o dst.json
```

输出里检查：

```
mapped    : 89/97 semantics (91.8%)
limits    : 2
colliders : 19
missing   : spine3, leftEar, ...
```

- `missing` 是这个模型本身没有的骨，不一定是错误；
- `colliders` 是给 M1 间隙约束 / M3 碰撞用的胶囊初值；
- 模型不是 1.6 m 时，在 `configs/retarget.json` 改
  `foot_lock.assumed_height_m`。

## 3. VMD → canonical

```bash
mmd-retarget inspect motion.vmd -p src.json -o motion.json
```

输出：

```
joints    : 65 semantic / 74 extra bones
contacts  : 249
frames    : 5640 (188.0 s)
```

`motion.json` 是模型无关的动作表示。接触段用**足 IK 目标**检测；如果模型
没有 IK 骨，会退回腿 FK 并在 `contacts[*].source` 标记 `fk`。

## 4. 重定向

```bash
mmd-retarget retarget motion.json \
  -s src.json -t dst.json \
  -o out.vmd -c configs/retarget.json
```

输出里重点看：

```
scale     : 0.8871 (20.76 -> 18.42)
arm ik    : 2 sides, ... wrist error mean 0.000 / max 0.000 units
clearance : pushed N frames, mean ... mm / max ... mm
twist     : 1 bones restored, mean 2.9 deg
pelvis    : applied N chunks, max root shift ... mm, residual ...
foot lock : ... chunks ... frames (...%), skip swing / drift / reach
slide     : mean ... -> ... units/frame
smooth    : max step ... -> ... (limit ...); drift ...
```

判读：

- `wrist error` 应接近 0；大说明 IK 目标不可达或骨架缺骨；
- `clearance` 有 push 是正常的，`max` 接近 `max_push_m` 说明衣服/体型差很大；
- `pelvis residual > 0` 表示仍有脚够不到，工具不会硬拉；
- `foot lock` 覆盖率 10–30% 是正常范围（迈步不锁）；
- `slide` 是整段统计，未锁窗口仍保留源滑步。

## 5. 被动件物理（可选）

```bash
mmd-retarget physics motion.json -p dst.json \
  -o motion_phys.json --vmd final.vmd -c configs/physics.json
```

默认只开头发（`chains.skirt=false`）。裙摆骨链实测会把腿顶穿，**不要**
在没有 M2 对比的情况下打开：

```bash
# 实验：显式开启裙摆
mmd-retarget physics ... --skirt
```

物理结果烘焙成骨骼关键帧，输出确定、可回滚；全片约 2 分钟。

## 6. 穿模检测（Blender）

```bash
blender -b --python tools/blender_cli.py -- validate \
  --model dst.pmx --motion final.vmd \
  -o report.csv --json report.json \
  --step 20 --visibility \
  --thumbnails thumbs --contact-sheet sheet.html \
  --camera "机位_近景,摄像机"
```

参数：

| 参数 | 说明 |
|---|---|
| `--step` | 采样间隔；定位用 20，复核用 1 |
| `--visibility` | 相机射线可见性 |
| `--camera a,b` | 多机位；任一可见即 `yes` |
| `--thumbnails` | high 帧 320×320 缩略图（Cycles CPU） |
| `--contact-sheet` | HTML 网格，按 severity 排序 |
| `--parts-config` | 覆盖部位规则（换非日文命名模型） |
| `--save-blend` | 保存场景（marker/相机持久化） |

输出：

- `report.csv`：frame / part_a / part_b / depth_mm / visible / severity / suggestion；
- `report.json`：同内容，便于程序处理；
- `thumbs/`：high 帧缩略图；
- `sheet.html`：浏览器打开，点图看大图。

> Workbench 在无 GPU 服务器上会渲染空图；项目已改用 Cycles CPU，单张约 2 s。

## 7. 回归对比

```bash
blender -b --python tools/blender_cli.py -- validate \
  --model dst.pmx --motion new.vmd \
  -o new.csv --diff old.csv --max-new 5 --max-worse 10
```

超过门槛会打印 `regression: FAILED` 并返回 1，可直接接 CI。

---

## 排错

### `inspect` 说 “未解析尾部 N 字节”

VMD 的相机/灯光段可能和 count 不一致。解析器会原样保留并告警，不影响
骨骼/morph。要读相机轨需要单独实现（见 bug 005）。

### `mapped` 覆盖率低

- 模型用英文/罗马音骨名：在 `src/mmd_retarget/skeleton.py` 的
  `SEMANTIC_SPECS` 里加候选名；
- 或者先跑 `inspect` 看实际骨名，再改 `_SIDE` 表。

### 脚锁覆盖率很低

- 动作本身滑步大：放宽 `max_lock_drift_m` / `max_support_drift_m`；
- 模型腿短：检查 `pelvis residual`，必要时提高 `max_shift_m`；
- 没有 `足IK` 骨：`contacts.source=fk`，精度会下降。

### 手臂 IK 手腕误差大

- 目标缺 `leftUpperArm/leftLowerArm/leftHand` 语义；
- 目标手臂链不是两段（多节机械臂）——当前算法只支持两骨；
- 看 `reach clamp` 是否很多：源动作把手伸得比目标臂长。

### Blender 找不到 MMD Tools

```bash
blender -b --python-expr "import bpy; bpy.ops.preferences.addon_enable(module='bl_ext.user_default.mmd_tools')"
```

或在 Blender GUI 的 Preferences → Extensions 里启用。

### 缩略图是黑的/空的

确认用的是 `Cycles` 而不是 `Workbench`；服务器没有 GPU 时 Workbench 会因
SSBO 限制渲染空图。

---

## 验收清单

- [ ] 身体穿透 < 2 mm，或 high 帧能逐条解释（白名单/机位不可见）；
- [ ] 脚锁窗口内滑步 < 5 mm；
- [ ] 相邻帧末端速度没有明显突跳（看 `smooth` 的 max step）；
- [ ] 衣物在最终机位不可见穿透（`visible=yes` 的 high 为 0 或已解释）；
- [ ] 同一输入 + 同一配置输出一致（物理已烘焙）；
- [ ] 原始动作与修正动作分开保存，可回滚。
