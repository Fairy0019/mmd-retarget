# mmd-retarget

**MMD 动作重定向 / 碰撞修正 / 被动件物理 / 穿模验收工具。**

把「为 A 体型编排的 VMD，套到 B 体型上」这件事，从**逐帧手调**变成
**可复现的管线 + 可读的报告**。

> 状态：**M1 进行中**（v0.0.2）。M0 数据层已完成；M1 已完成比例缩放、
> 承重判断、分窗脚锁、锚定平滑与脊柱链拆分（stage 3/4）。
> 手臂 IK、间隙约束与骨盆补偿尚未接入。
> 进度见 [docs/PLAN.md](docs/PLAN.md)，实测报告见 `docs/reports/`。

---

## 为什么做这个

MMD 生态里换模型套动作的流程通常是：

1. 用 VmdSizing 之类工具做**比例缩放**；
2. 发现手臂插进胸口、头发穿过翅膀、裙摆穿大腿；
3. 逐帧手动挪骨头。

第 3 步不可扩展，而且**问题出在第 1 步**：VMD 只有关节角，没有“手要到哪”
的意图；直接复制局部四元数，会同时引入**比例误差、rest/roll 误差、FK 语义误差**。
再加一层手动偏移只是打补丁——阈值处会弹跳，边缘处仍会穿。

现有工具基本停在「比例缩放 + 骨架映射」，**没有一个同时做**：

- rest pose / bone roll 适配；
- 脚锁（防滑步）+ 手臂 IK + 间隙约束；
- 裙 / 发 / 袖 / 披风的被动件物理；
- 穿透深度 + 可见性 + 时间轴标注 + 回归。

`mmd-retarget` 想补的就是这块。

## 它做什么

```
VMD + 源骨架档案 + 目标骨架档案
   → canonical motion（语义关节 + 根轨迹 + 接触段 + 表情）
   → 重定向（脚锁 / 手臂 IK / 间隙约束 / 时间平滑）
   → 被动件物理（裙 / 发 / 袖，烘焙成骨骼动画）
   → 检测与标注（穿透深度 / 可见性 / severity / 回归）
   → 目标模型的 VMD
```

## 它不做什么

- ❌ 自动编舞、自动审美判断（机器只做确定性的事）
- ❌ 视频渲染 / 后期
- ❌ 分发任何模型、动作、音乐素材

## 文档

| 文档 | 内容 |
|---|---|
| [docs/VISION.md](docs/VISION.md) | 构想：问题、原则、分层设计 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 模块、数据模型、算法要点 |
| [docs/PLAN.md](docs/PLAN.md) | 里程碑 M0–M4 与验收标准 |
| [docs/STEPS.md](docs/STEPS.md) | 开发步骤拆解（12 步、依赖、验收） |

## 快速开始（M0，不需要 Blender）

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"       # 或 pip install numpy pytest

# 1) 看模型 / 动作
python -m mmd_retarget.cli inspect model.pmx
python -m mmd_retarget.cli inspect motion.vmd

# 2) 生成目标骨架档案
python -m mmd_retarget.cli skeleton model.pmx -o profile.json

# 3) VMD → canonical motion（接触段需要 profile）
python -m mmd_retarget.cli inspect motion.vmd -p profile.json -o motion.json

# 4) canonical → VMD（M0 为 pass-through，M1 才做比例/rest/IK）
python -m mmd_retarget.cli retarget motion.json -s src.json -t dst.json -o out.vmd
```

> `retarget` 目前做比例缩放 + 分窗脚锁；rest-relative 旋转、手臂 IK、
> 间隙约束与时间平滑尚未接入，输出仍不是最终可用结果。

## 技术栈

- **Python 3.11**（Blender 内置解释器）
- **Blender bpy / mathutils**：骨骼、网格、BVH、IK
- **numpy**：数值计算
- 性能瓶颈（VMD/PMX 解析、IK、BVH）如需要再下沉到 **C++ + pybind11**

## 许可证

**GPL-3.0-or-later**。与 MMD Tools 生态一致；若未来引入其解析代码，无需换证。

## 素材声明

本仓库**不包含**任何第三方模型、动作、音乐或贴图。
所有示例与验收数据均由使用者自备，版权归原作者所有。
