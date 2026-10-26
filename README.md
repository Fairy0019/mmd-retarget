# mmd-retarget

**MMD 动作重定向 / 碰撞修正 / 被动件物理 / 穿模验收工具。**

把「为 A 体型编排的 VMD，套到 B 体型上」这件事，从**逐帧手调**变成
**可复现的管线 + 可读的报告**。

> 状态：**v0.1.2**。M0–M2 完成，M3 头发物理可用、裙摆 C4-B 布料工具已实现
> （5 帧冒烟通过，待 300 帧/视觉验收），M4 集成/文档完成。测试 **102 passed**。
>
> - **M1**：比例缩放、承重/脚锁、骨盆补偿、脊柱链、手臂 IK + 间隙、twist、锚定平滑；
> - **M2**：BVH 穿透检测、severity、CSV/JSON、多机位/多点可见性、缩略图、
>   contact sheet、回归 diff + CI 门槛；
> - **M3**：头发骨链 PBD（侧发/后发分组）；裙摆提供两条路线：
>   C4-A 权重转移工具（验收未通过）+ C4-B 布料代理工具（5 帧冒烟通过）。

---

## 管线

```
VMD + 源骨架档案 + 目标骨架档案
   → canonical motion（语义关节 + 根轨迹 + 接触段 + 表情）
   → 重定向（比例 / 脚锁 / 骨盆补偿 / 手臂 IK / 间隙 / twist / 平滑）
   → 被动件物理（头发；裙摆实验）
   → 检测与标注（BVH 深度 / 可见性 / severity / 回归）
   → 目标模型的 VMD + CSV/JSON/contact sheet
```

## 为什么做这个

MMD 生态里换模型套动作的流程通常是：

1. 用 VmdSizing 之类工具做**比例缩放**；
2. 发现手臂插进胸口、头发穿过翅膀、裙摆穿大腿；
3. 逐帧手动挪骨头。

第 3 步不可扩展，而且**问题出在第 1 步**：VMD 只有关节角，没有“手要到哪”
的意图；直接复制局部四元数，会同时引入比例、rest/roll、FK 语义误差。
现有工具基本停在「比例缩放 + 骨架映射」，没有一个同时做脚锁、手臂 IK、
间隙、被动件物理和穿模验收。

## 快速开始

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 1) 看模型 / 动作
python -m mmd_retarget inspect model.pmx
python -m mmd_retarget inspect motion.vmd

# 2) 生成源/目标骨架档案
python -m mmd_retarget skeleton src_model.pmx -o src.json
python -m mmd_retarget skeleton dst_model.pmx -o dst.json

# 3) VMD → canonical
python -m mmd_retarget inspect motion.vmd -p src.json -o motion.json

# 4) 重定向
python -m mmd_retarget retarget motion.json \
  -s src.json -t dst.json -o out.vmd -c configs/retarget.json

# 5) 头发物理（可选）
python -m mmd_retarget physics motion.json -p dst.json \
  -o motion_phys.json --vmd final.vmd -c configs/physics.json

# 6) 穿模检测（需要 Blender + MMD Tools）
blender -b --python tools/blender_cli.py -- validate \
  --model dst_model.pmx --motion final.vmd \
  -o report.csv --json report.json --step 20 \
  --visibility --thumbnails thumbs --contact-sheet sheet.html
```

完整版见 [docs/QUICKSTART.md](docs/QUICKSTART.md)。

## 它不做什么

- ❌ 自动编舞、自动审美判断（机器只做确定性的事）
- ❌ 视频渲染 / 后期
- ❌ 分发任何模型、动作、音乐素材

## 文档

| 文档 | 内容 |
|---|---|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | 30 分钟跑通：命令、配置、排错 |
| [docs/VISION.md](docs/VISION.md) | 问题、原则、分层设计 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 模块、数据模型、算法 |
| [docs/PLAN.md](docs/PLAN.md) | 里程碑与验收标准 |
| [docs/STEPS.md](docs/STEPS.md) | 开发步骤拆解 |
| [docs/bugs/](docs/bugs/README.md) | Bug 复盘库：根因、波及面、回归 |
| [docs/design/C4-skirt.md](docs/design/C4-skirt.md) | 裙摆 C4 方案（权重转移 / 布料代理） |
| [docs/plans/](docs/plans/2026-10-26-server-next.md) | **服务器下一步计划**（验收、C4、CI、跨模型、发布） |
| [docs/reports/](docs/reports/README.md) | 阶段报告与实测数字 |
| [configs/](configs/README.md) | retarget / physics / parts 配置模板 |

## 实测

| 项 | 数值 |
|---|---|
| VMD 2.9 MB / 140 骨 / 25,973 帧 | 解析 0.086 s，字节级 round-trip |
| VMD 压力测试 789,600 帧 | 3.40 s（目标 < 10 s） |
| PMX 6.4 MB / 63k 顶点 / 550 骨 | 0.35 s |
| 同骨架回写 | 旋转误差 3e-6°，位移 0 |
| 手臂 IK 手腕误差 | mean 3e-8 / max 4e-5 单位 |
| 脚锁 | 115 窗口 / 1,800 帧（16.0%），窗口内漂移 0 |
| 骨盆补偿 | 53 个不可达窗口 → 38 个自动补偿，root 最大 48 mm |
| M2 采样 | 282 帧 / 24 s / 1,051 条记录 |
| 可见性 | 288/1,051 可见；37 条可见 high 全为腿–裙 |

## 技术栈

- **Python 3.11+**；纯 Python 层不依赖 Blender
- **Blender bpy / mathutils**：网格、BVH、可视性、缩略图
- **numpy**：数值计算
- 性能瓶颈可按需下沉到 C++ + pybind11

## 许可证

**GPL-3.0-or-later**。与 MMD Tools 生态一致。

## 素材声明

本仓库**不包含**任何第三方模型、动作、音乐或贴图。
所有示例与验收数据均由使用者自备，版权归原作者所有。
