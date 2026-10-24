# 交接说明

> 状态：**v0.0.4 · M0/M1/M2 完成，M3 框架完成**（骨盆补偿仅诊断）。
> M1：比例、承重、分窗脚锁、锚定平滑、脊柱链、手臂两骨 IK、间隙约束、twist。
> M2：BVH 深度、severity、回归门槛、多机位/多点可见性、缩略图、contact sheet、
> 可配置部位规则。
> M3：骨链 PBD 已接入；**头发启用，裙摆默认关闭**（骨链会把腿顶穿，
> 待 C4 布料/权重，见报告 17）。

## 1. 环境

| 项 | 版本 / 位置 |
|---|---|
| Python | 3.12（本机 `.venv`，`uv venv --python 3.12`） |
| 依赖 | `numpy`、`pytest`（`pip install -e ".[dev]"`） |
| Blender | 5.2.2 LTS（M1 需要；`blender -b --python ...` 可用） |
| 素材 | `/root/mmd-vision/assets/`（私有，**不入库**） |

```bash
.venv/bin/python -m pytest -q          # 69 passed
.venv/bin/python tools/bench_vmd.py    # 140×5640, 约 3.4s
```

## 2. 已完成（M0 + M1 stage 1/2）

```
src/mmd_retarget/
├── vmd.py        VMD 读写，字节级 round-trip，插值解码
├── pmx.py        PMX 2.0/2.1 最小集，骨骼/权重/材质/morph
├── skeleton.py   语义映射 + profile（rest/limits/colliders/morphs）
├── canonical.py  VMD → canonical，接触段检测（源骨架 FK）
├── parts.py      部位规则（左右前缀/后缀、材质、pair）
├── validate.py   severity / CSV / diff / contact sheet
├── validate_blender.py  BVH 深度 + 多机位可见性 + 缩略图
├── writer.py     canonical → 目标 VMD
├── retarget.py   比例 / 脚锁 / 脊柱链 / 手臂 IK / 间隙 / twist
├── physics.py    骨链 PBD（头发启用，裙摆实验）
└── cli.py        inspect / skeleton / retarget / physics / validate
```

实测数据（详见 `docs/reports/01`–`03`）：

- `恋爱循环.vmd`：2.9 MB / 140 骨 / 25,973 帧 / 2,344 morph 帧，解析 0.086 s；
- `薇斯纳.pmx`：6.4 MB / 63,278 顶点 / 550 骨 / 67 morph，解析 0.35 s；
- 同骨架 round-trip：25,973 帧旋转误差 < 0.00001°、位移误差 0；
- 换骨架：66 个语义骨写出 23,266 帧，63 根目标没有的物理骨被丢弃；
- 接触段：249 段，覆盖 67.4% 的“脚-帧”；用足 IK 目标检测（报告 05）；
- 脚锁：承重判断后 217/493 窗口；锚定平滑后 107 窗口、1708 帧（15.1%），
  窗口内漂移 0、最大步长 0.126 ≤ 限速（报告 06/10）；
- 脊柱链：`上半身` 均分到 `上半身/1/2`，回放上半身中位偏差 7.2 mm（报告 07）；
- 时间平滑：锚定版窗口内漂移 0、最大步长 ≤ 限速（报告 10）；
- M2 穿模检测：282 帧 / 24 s / 1,051 条记录；手臂–躯干最大 31 mm（报告 11）；
- 手臂 IK：手腕目标误差 mean 3e-8 / max 4e-5 单位（报告 14）；
- 可见性：288/1,051 可见，37 条可见 high 全部是腿–裙（报告 12）；
- 缩略图/回归：43 张 high 缩略图；`--max-new/--max-worse` 可让 CI 失败（报告 13）；
- 骨盆补偿：53 个不可达窗口 -> 38 个自动补偿，root 最大 48 mm（报告 18）。

## 3. 下一步（M3 之后）

M1/M2 完成，M3 框架完成（见 `docs/reports/16`、`17`）。接下来：

1. **裙摆 C4**：布料模拟或重新刷权重；骨链已实测会顶穿腿，不要再调参数；
2. **头发分组**：背后长发 / 肩前侧发分开参数，降低 `hair-torso`；
3. **物理接 CI**：30 秒样本 + `validate --max-new` 回归门槛；
4. **骨盆补偿（stage 6）**：先统一“脚世界坐标 = root + IK 位移”的口径；
5. **跨模型矩阵**：再找 1–2 副体型差异明显的 PMX。

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
- 每个阶段提交一份 `docs/reports/NN-*.md`，写清实测数字与风险；
- 修完一个 bug，建议顺手补一份 `docs/bugs/NNN-*.md` 短复盘（现象 / 根因 /
  改法 / 波及面），几段话即可，不强制长篇。模板见 `docs/bugs/README.md`。

## 5. 验收口径（全项目）

- 身体：穿透 < 2 mm 或白名单；
- 脚部：接触段滑步 < 5 mm；
- 连续性：相邻帧末端速度无 > 50% 突跳；
- 衣物：最终机位不可见穿透；
- 所有模拟结果烘焙成关键帧后交付。
