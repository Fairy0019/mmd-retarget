# 交接说明（给服务器上的 agent）

> 状态：v0.0.1 设计阶段。仓库里只有文档 + CLI 骨架，核心算法未实现。
> 接手后从 **M0-① VMD parser** 开始，见 GitHub Issue。

## 1. 环境

| 项 | 版本 / 位置 |
|---|---|
| Python | 3.12.10（`python --version` 可用） |
| 虚拟环境 | 仓库根目录 `.venv`（已 gitignore） |
| 依赖 | `numpy`、`pytest` |
| Blender | 5.0.1（M1 之后的 bpy 步骤需要） |

```bash
python -m venv .venv
.venv/Scripts/activate      # Windows
# source .venv/bin/activate # Linux
pip install -e ".[dev]" || pip install numpy pytest
pytest -q
```

当前测试：`3 passed`。

## 2. 代码结构

```
src/mmd_retarget/
├── __init__.py     # 版本号
└── cli.py          # 5 个子命令骨架（skeleton/inspect/retarget/physics/validate）
tests/test_cli.py   # 冒烟测试
docs/               # VISION / ARCHITECTURE / PLAN / STEPS
```

## 3. 下一步（M0-①）

实现 `src/mmd_retarget/vmd.py`：

- 读：header（30 字节）、模型名（20 字节）、骨骼帧、morph 帧、相机/灯光轨（可跳过）；
- 写：与读对称，保持字节兼容；
- 骨名：Shift-JIS，15 字节定长，`\0` 填充；
- 帧率固定 30fps；
- 插值：64 字节（贝塞尔控制点）；

**验收**

1. round-trip：读入→写出→再读入，未修改的骨骼旋转误差 < 0.1°、位移 < 0.1mm；
2. 日文骨名不丢失、不串码；
3. 5640 帧 × 140 骨解析 < 10 秒；
4. `pytest` 全绿，新增测试覆盖：空轨迹、单帧、超长骨名、morph。

## 4. 约束

- **不要**把任何模型/动作/音乐素材提交进仓库（版权）；
- 依赖保持最小：标准库 + numpy；新增依赖需在 PR 说明理由；
- 许可证 GPL-3.0-or-later，新增文件头保留 SPDX 标识（可选但推荐）；
- 不要改 `docs/VISION.md` 的定位与非目标，除非先开 issue 讨论。

## 5. 验收口径（全项目）

- 身体：穿透 < 2mm 或白名单；
- 衣物：最终机位不可见穿透；
- 连续性：相邻帧末端速度无 > 50% 突跳；
- 所有模拟结果烘焙成关键帧后交付。

## 6. 已知参考

- MMD Tools（GPL-3.0）的 VMD 读写实现可作为格式参考；
- 私有仓库 `Fairy0019/mmd-vision` 有验收用例与 v2 基线数据（不公开）。
