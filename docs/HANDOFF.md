# 交接说明

> 状态：**v0.0.2 · M0 数据层完成**。VMD/PMX 解析、skeleton profile、
> canonical motion、VMD 回写均已可用并有真实素材验证。
> 下一步是 **M1 身体重定向**（需要 Blender）。

## 1. 环境

| 项 | 版本 / 位置 |
|---|---|
| Python | 3.12（本机 `.venv`，`uv venv --python 3.12`） |
| 依赖 | `numpy`、`pytest`（`pip install -e ".[dev]"`） |
| Blender | 5.2.2 LTS（M1 需要；`blender -b --python ...` 可用） |
| 素材 | `/root/mmd-vision/assets/`（私有，**不入库**） |

```bash
.venv/bin/python -m pytest -q          # 56 passed
.venv/bin/python tools/bench_vmd.py    # 140×5640, 约 3.4s
```

## 2. 已完成（M0）

```
src/mmd_retarget/
├── vmd.py        VMD 读写，字节级 round-trip，插值解码
├── pmx.py        PMX 2.0/2.1 最小集，骨骼/权重/材质/morph
├── skeleton.py   语义映射 + profile（rest/limits/colliders/morphs）
├── canonical.py  VMD → canonical，接触段检测（源骨架 FK）
├── writer.py     canonical → 目标 VMD
└── cli.py        inspect / skeleton / retarget（physics/validate 仍 stub）
```

实测数据（详见 `docs/reports/01`–`03`）：

- `恋爱循环.vmd`：2.9 MB / 140 骨 / 25,973 帧 / 2,344 morph 帧，解析 0.086 s；
- `薇斯纳.pmx`：6.4 MB / 63,278 顶点 / 550 骨 / 67 morph，解析 0.35 s；
- 同骨架 round-trip：25,973 帧旋转误差 < 0.00001°、位移误差 0；
- 换骨架：66 个语义骨写出 23,266 帧，63 根目标没有的物理骨被丢弃；
- 接触段：355 段，覆盖 34.6% 的“脚-帧”，段内平均滑步 0.404 单位/帧。

## 3. 下一步（M1）

按优先级：

1. **Blender 场景层**：导入 PMX + VMD，导出每帧真实 pose matrix；
   确认 MMD 的局部旋转复合方式与 `canonical.detect_contacts` 的简化 FK
   差多少（这是当前最大的未验证假设）。
2. **rest-relative 重定向**：世界旋转增量法
   `ΔR = R_src(t) · R_src_rest⁻¹`，再转目标局部空间；
   处理源 `上半身` → 目标 `上半身/上半身1/上半身2` 的链长差异。
3. **脚锁**：用真实脚踝轨迹重做接触段；腿 IK + 骨盆补偿；滑步 < 5 mm。
4. **手臂 IK + 间隙**：手腕轨迹、极向量、胶囊约束（profile 里已有 19 个
   胶囊，但只是初值）。
5. **时间平滑**：对修正量做膨胀→平均→限速。

### 已知坑（务必先看）

- **根运动只认 センター**：用 `グルーブ` / `全ての親` 的动作会丢根位移；
- 接触检测是高度启发式，源动作本身在滑；M1 必须用 IK 重算，不能直接锁；
- PMX 的 `tail` 是显示提示，不是形变段；碰撞体端点要用父子 rest 偏移；
- PMX 没有 roll，profile 里的 `roll: 0.0` 是占位；
- 腿部蒙皮常在 D 骨上（左足D/ひざD），本体骨没有权重；
- writer 统一写线性插值，源 VMD 的非线性曲线没有保留；
- morph 靠日文同名匹配，跨模型需要映射表。

## 4. 约束

- **不要**把任何模型/动作/音乐素材提交进仓库（版权）；`.gitignore` 已
  忽略 `*.pmx` / `*.vmd` / `*.blend` 等；
- 依赖保持最小：标准库 + numpy；新增依赖需在提交说明里写理由；
- 许可证 GPL-3.0-or-later，新文件保留 SPDX 标识；
- 不要改 `docs/VISION.md` 的定位与非目标，除非先开 issue 讨论；
- 每个阶段提交一份 `docs/reports/NN-*.md`，写清实测数字与风险。

## 5. 验收口径（全项目）

- 身体：穿透 < 2 mm 或白名单；
- 脚部：接触段滑步 < 5 mm；
- 连续性：相邻帧末端速度无 > 50% 突跳；
- 衣物：最终机位不可见穿透；
- 所有模拟结果烘焙成关键帧后交付。
