# Changelog

## 0.1.2 — 2026-10-26

- 新增 `tools/skirt_cloth.py`：裙摆布料代理 → Q 骨烘焙（C4-B）
- 避开 `bake_all` 连带烘焙 447 刚体 5640 帧 cache 的坑
- 5 帧冒烟通过；300 帧/视觉验收待做（报告 33）

## 0.1.1 — 2026-10-25

补齐报告 19 的缺口，并完成服务器侧验收：

- 头发分组（side/back 独立参数）；验收 high 0=0、≥5 mm 76<82
- 根运动合并 `グルーブ` / `全ての親`；修 bug 008（纯 グルーブ 丢根）
- morph 映射（`--morph-map`）；验收 2,305 帧目标名
- VMD 非线性插值保留；验收 25,973/25,973 键字节一致
- `tools/render_acceptance.py` 视觉验收 + `--clay`；10 张 / 0 黑图
- `tools/skirt_reweight.py` + `docs/design/C4-skirt.md`（C4-A，实测无收益）
- `tools/ci_physics.sh` 物理回归；900 帧基线 + diff 门槛
- `tools/cross_model_matrix.py`；薇斯纳→Lumine 真实跨模型验证（high 285→206）
- 修 bug 009（`physics --skirt` 空开关）
- 测试：**102 passed**

## 0.1.0 — 2026-10-24

首个可发布版本：M0–M4 主链路打通。

- M0：VMD/PMX 无损读写、skeleton profile、canonical motion、VMD writer
- M1：比例缩放、承重/脚锁、骨盆补偿、脊柱链、手臂两骨 IK + 间隙、twist、锚定平滑
- M2：Blender BVH 穿透检测、severity、CSV/JSON、多机位/多点可见性、
  缩略图、HTML contact sheet、回归 diff + CI 门槛
- M3：头发骨链 PBD 启用；裙摆骨链为实验特性（默认关闭，见报告 17）
- M4：CLI 五个子命令、`configs/` 模板、`docs/QUICKSTART.md`、
  `tools/demo_pipeline.sh`、`python -m mmd_retarget`
- 测试：95 passed

## 0.0.4 — 2026-10-24

- 新增 `physics` 子命令与骨链 PBD（头发启用，裙摆负结果）
- 报告 17

## 0.0.3 — 2026-10-24

- M1 stage 5：手臂间隙约束、twist 恢复、骨盆诊断
- M2 stage 4：部位规则配置、多点可见性、多机位、contact sheet
- 跨模型（薇斯纳 → Lumine）首次跑通
- Bug 复盘库（7 份）

## 0.0.2 — 2026-10-23

- M0 数据层完成；报告 01–04

## 0.0.1 — 2026-10-23

- 设计文档 + CLI 骨架
