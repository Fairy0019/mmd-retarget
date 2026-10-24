# 阶段报告 19 · M4 发布 v0.1.0

- 日期：2026-10-24
- 版本：**v0.1.0**
- 测试：**95 passed**
- 结论：M0–M4 主链路打通；M3 的裙摆仍是实验特性，其余交付可用。

---

## 1. 发布内容

| 项 | 内容 |
|---|---|
| CLI | `skeleton / inspect / retarget / physics / validate` 五个子命令 |
| 入口 | `mmd-retarget` 控制台脚本 + `python -m mmd_retarget` |
| 配置 | `configs/retarget.json`、`physics.json`、`parts.json` |
| 文档 | `docs/QUICKSTART.md`（30 分钟）、README 重写 |
| 示例 | `tools/demo_pipeline.sh` 一条命令跑 profile→canonical→retarget→physics→validate |
| 版本 | `0.1.0`（pyproject / `__version__`） |
| 变更记录 | `CHANGELOG.md` |

### 1.1 安装验证

```text
$ mmd-retarget --version
mmd-retarget 0.1.0

$ mmd-retarget --help
{skeleton,inspect,retarget,physics,validate}
```

`uv pip install -e .` 安装成功，控制台脚本可用。

### 1.2 demo 实跑

```bash
MODEL=薇斯纳.pmx MOTION=恋爱循环.vmd \
OUT=/tmp/demo PHYSICS=0 VALIDATE=0 ./tools/demo_pipeline.sh
```

输出：`src.json` / `dst.json` / `motion.json` / `retargeted.vmd`（5.9 MB）。
脚本自动检测 `.venv/bin/python`，没有 `python` 命令也能跑。

## 2. M1 骨盆补偿（本轮新增）

报告 16 只给诊断数字；本轮把它做成默认 `apply`：

| 项 | 数值 |
|---|---|
| reach 窗口 | 53 |
| 自动补偿 | **38** |
| residual | 1 |
| skipped_reach | 15（原 53） |
| root 最大位移 | **48.0 mm** |
| root 限速 | 8 mm/帧 |
| 锁定 | 115 窗口 / 1,800 帧（16.0%） |
| 平均滑步 | 0.1541 → **0.0320** 单位/帧 |

关键口径：脚 IK 目标不含 root，移动 root 只动骨盆、不动脚。这是之前
不敢自动补偿的原因，报告 18 已写清。

## 3. M3 mesh radius 实验（负结果）

报告 17 说裙摆骨链会把腿顶穿。本轮试了一个中间方案：

- 从 `bone_vertex_bbox` 估计每个裙骨的“网格半径”；
- 碰撞时把该半径加到腿胶囊上，让骨点离腿更远。

300 帧前奏样本（step 5）：

| 配置 | high | max depth |
|---|---:|---:|
| 原始 | 10 | 69.5 mm |
| 裙骨链（无 mesh radius） | **1** | 35.7 mm |
| 裙骨链 + mesh radius | 4 | 66.8 mm |

mesh radius 反而更差。全片 282 帧样本里报告 17 已经证明骨链裙摆会把
high 从 47 推到 109；本实验不改变结论。

**决定**：`use_mesh_radius` 默认 `False`，代码保留供以后布料/权重方案
参考；`chains.skirt` 仍默认关闭。不要继续调骨链参数。

## 4. M4 验收对照

| 验收项 | 状态 |
|---|---|
| CLI 五个子命令 | ✅ |
| 文档、示例、配置模板 | ✅ |
| v0.1.0 | ✅ |
| 新用户按 README 30 分钟跑通 | 🟡 命令/模板齐全，但本地没有第二副可公开素材，未做“陌生人”实测 |

## 5. 仍然没做的

1. **裙摆 C4**：布料模拟或重新刷权重；骨链方案已判死刑；
2. **头发分组**：背后长发/肩前侧发仍用同一套参数；
3. **视觉验收**：没有渲染级“看起来对不对”的验收，只有数值和缩略图；
4. **根运动只认 センター**：用 `グルーブ`/`全ての親` 的动作会丢位移；
5. **插值曲线**：writer 统一线性，源贝塞尔没有保留；
6. **morph 映射**：靠日文同名，换模型需要映射表；
7. **跨模型素材**：报告 16 的 Lumine 模型不在当前工作区，无法复现。

## 6. 复现

```bash
.venv/bin/python -m pytest -q            # 95 passed
.venv/bin/mmd-retarget --version         # 0.1.0
MODEL=... MOTION=... ./tools/demo_pipeline.sh
```

## 7. 给接手人的一句话

**M0–M2 可以按 README 用；M3 只开头发；裙摆不要再调骨链参数，直接上
布料或重刷权重。**
