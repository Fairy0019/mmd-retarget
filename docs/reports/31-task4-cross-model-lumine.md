# 任务 4（解除阻塞）· 真实跨模型：薇斯纳 → Lumine Tactical

- 日期：2026-10-26
- 计划：`docs/plans/2026-10-26-server-next.md` 任务 4
- 素材：`YouKaiGhost/3d-modeling-assets`（私有），`Lumine Tactical.pmx`
- 结论：**通过**。跨模型管线跑通；`high` 285→206、可见 high 98→79、
  最大深度 83.4→74.1 mm；输出 VMD 两次运行字节一致。

---

## 1. 第二副模型

从私有素材仓库解压：

```
Lumine Tactical.pmx   3.98 MB
vertices              30,525（46,069 三角）
bones                 394（7 IK）
materials             17
morphs                81
height                18.4155（薇斯纳 20.7599，scale 0.8871）
```

`mmd-retarget skeleton`：

```
mapped    : 89/97 semantics (91.8%)
limits    : 5
colliders : 19
missing   : control, spine1, leftEar, leftToeD, leftBreast, rightEar, rightToeD, rightBreast
```

`spine` 链是 `spine / spine2 / spine3`（没有 `spine1`），链拆分按实际存在的
段处理。

## 2. 矩阵

```bash
python tools/cross_model_matrix.py \
  --motion motion2.json --source profile2.json --target lumine.json \
  --label "Vesna->Lumine"
```

| 指标 | 薇斯纳基线 | Lumine | 判读 |
|---|---:|---:|---|
| scale | 1.0000 | **0.8871** | 身高差 11.3% |
| 手腕误差 mean | 3.1e-9 | 2.3e-15 | 均为 0 |
| 手腕误差 max | 8.7e-6 | 4.2e-14 | 亚微米 |
| arm reach clamp | 10 | **0** | Lumine 手臂更短，目标更容易达到 |
| 脚锁窗口 | 115 / 493 | **117 / 493** | +2 |
| 脚锁覆盖率 | 15.96% | **16.11%** | 略高 |
| 滑步 mm/帧 | 2.463 | **2.563** | +4.1% |
| 骨盆补偿 | 38 | **31** | 少 7 次 |
| residual | 1 | 1 | 相同 |

## 3. 穿模对比（Lumine）

Lumine 的材质是英文名，默认部位规则抓不到裙/发；用
`configs/parts.lumine.json`（`Skirt/Hair/Wing`）后才有完整统计。

```bash
blender -b --python tools/blender_cli.py -- validate \
  --model "Lumine Tactical.pmx" --motion lumine_out.vmd \
  -o lumine_retarget.csv --step 20 --visibility \
  --parts-config configs/parts.lumine.json
```

| 指标 | 原始 VMD 直接套 | 重定向后 | 变化 |
|---|---:|---:|---:|
| records | 1,290 | 1,235 | -55 |
| high | **285** | **206** | **-79（-27.7%）** |
| 可见 high | 98 | **79** | -19 |
| max depth | 83.38 mm | **74.13 mm** | -9.25 mm |
| leg–skirt high | 269 | 192 | -77 |
| arm–torso high | 9 | 4 | -5 |
| hair–torso high | 7 | 9 | +2 |

- 主要收益来自腿–裙（-77 条 high），说明比例/脚锁让腿与裙的相对位置更合理；
- 手臂–躯干也减半；
- 头发 high 略增 2 条，属于被动件，等 M3 处理；
- 可见 high 仍有 79，主要是腿–裙，M3 裙摆未解决。

## 4. 可复现性

同一输入、同一配置跑两次：

```
c913862cd05970fbf7cbc2b3feeca60d36ea149e5dd63ed69e8638b78af28b2a  lumine_out.vmd
c913862cd05970fbf7cbc2b3feeca60d36ea149e5dd63ed69e8638b78af28b2a  lumine_out2.vmd
byte-identical
```

## 5. 判读与边界

**通过标准**：两副模型结果可复现，不劣于薇斯纳基线。

- 手腕误差、脚锁覆盖率、骨盆补偿都同级或更好；
- 滑步 2.563 vs 2.463 mm/帧，+4.1%，仍在同一量级；
- 穿模 high 相对原始 VMD 明显下降（285→206），但绝对 high 仍高，
  因为裙摆/头发是 M3 范围。

边界：

- 只验证了一对模型（薇斯纳 → Lumine）；Lumine 的骨骼名是日文标准名，
  命名差异更大的模型仍需要映射表；
- 英文材质需要 `configs/parts.lumine.json`，默认规则不通用；
- 可见性用默认/自动机位，不是最终舞蹈机位；
- 腿–裙 high 仍然存在，M3 路线 B（布料）未实现。

## 6. 复现命令

```bash
# 1) 目标 profile
mmd-retarget skeleton "Lumine Tactical.pmx" -o lumine.json
# 2) 重定向
mmd-retarget retarget motion2.json -s profile2.json -t lumine.json \
  -o lumine_out.vmd -c configs/retarget.json
# 3) 矩阵
python tools/cross_model_matrix.py --motion motion2.json \
  --source profile2.json --target lumine.json --label "Vesna->Lumine"
# 4) 检测
blender -b --python tools/blender_cli.py -- validate \
  --model "Lumine Tactical.pmx" --motion lumine_out.vmd \
  -o lumine_retarget.csv --step 20 --visibility \
  --parts-config configs/parts.lumine.json
```
