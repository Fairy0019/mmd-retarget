# 任务 4 · 跨模型矩阵

- 日期：2026-10-25
- 计划：`docs/plans/2026-10-26-server-next.md` 任务 4
- 状态：**⚠️ 阻塞（缺第二副人类 PMX）**
- 已完成：矩阵工具 + 0.85/1.0/1.15 缩放 profile 的合成验证。

---

## 1. 素材搜索

全盘搜索（排除 `.venv`）：

```
/root/mmd-vision/assets/model/薇斯纳.pmx      ← 唯一人类模型
/root/mmd-vision/assets/model/法杖.pmx
/root/mmd-vision/assets/model/武器.pmx
/root/mmd-vision/assets/model/魔法剑1.pmx
/root/mmd-vision/assets/model/魔法剑2.pmx
```

报告 16 提到的 “Lumine Tactical” 不在当前工作区，也没有下载地址。
四把武器只有 1 根骨、没有人体语义，不能用于重定向矩阵。

**结论：任务 4 的“第二副体型差异明显的 PMX”前提不成立。**

## 2. 新增工具

`tools/cross_model_matrix.py`：源 profile × 目标 profile × canonical →
一行 JSON 指标（比例、手腕误差、reach clamp、脚锁覆盖率、滑步 mm/帧、
骨盆补偿、residual）。

```bash
python tools/cross_model_matrix.py \
  --motion motion.json --source src.json --target dst.json \
  --label "A->B"
```

真实第二副 PMX 到位后：

```bash
mmd-retarget skeleton lumine.pmx -o lumine.json
python tools/cross_model_matrix.py \
  --motion motion.json --source vesna.json --target lumine.json \
  --label "Vesna->Lumine"
```

## 3. 合成缩放矩阵

没有第二副模型，先把 **profile 按比例缩放**（0.85 / 1.0 / 1.15）当作
“体型不同”的代理。它只能验证比例/IK/脚锁数学，不能验证真实骨骼差异。

| scale | 目标身高 | 手腕误差 mean | 手腕误差 max | reach clamp | 脚锁覆盖 | 滑步 mm/帧 | 骨盆 | residual |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.85 | 17.65 | 2.6e-9 | 7.4e-6 | 10 | 15.96% | 2.463 | 38 | 1 |
| 1.00 | 20.76 | 3.1e-9 | 8.7e-6 | 10 | 15.96% | 2.463 | 38 | 1 |
| 1.15 | 23.87 | 3.6e-9 | 1.0e-5 | 10 | 15.96% | 2.463 | 38 | 1 |

关键结论：

- 手腕目标在所有缩放下都被解到 1e-5 单位（亚毫米）；
- 脚锁窗口/覆盖率/骨盆补偿次数完全一致，说明逻辑是尺度不变的；
- 滑步换算成米后都是 **2.463 mm/帧**，没有随模型变大而漂移；
- `clearance_pushed` 随缩放变化（335 / 159 / 101），因为胶囊间隙的绝对值
  随模型变化，符合预期。

## 4. 为什么不能算通过

计划要求“两副模型结果可复现，不劣于薇斯纳基线”。当前只有：

- 一副真实人类模型；
- 三个合成缩放 profile（同一套骨骼/权重/网格）。

合成矩阵能证明**算法对尺度不敏感**，不能证明：

- 不同 rest/roll、不同骨长比例、不同裙/发拓扑；
- 真实网格穿透、可见性、缩略图；
- morph/材质命名差异。

因此任务 4 标记 **阻塞**，不伪装成通过。

## 5. 解锁条件

在私有素材目录放入第二副人类 PMX（最好身高差 ≥ 15%），然后：

```bash
MODEL=/private/models/B.pmx MOTION=恋爱循环.vmd \
OUT=/tmp/cross ./tools/ci_physics.sh
python tools/cross_model_matrix.py --motion motion.json \
  --source vesna.json --target b.json --label "Vesna->B"
```

验收：手腕误差、脚滑、身体穿透、pelvic 窗口四项与薇斯纳基线同级，
且能复现两次。
