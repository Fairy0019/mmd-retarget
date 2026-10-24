# 状态总览 · M1 stage 4/5 + M2 stage 3/4

- 日期：2026-10-24
- 版本：v0.0.2
- 测试：**78 passed**
- 远端：`main`，工作区干净

---

## 1. 能力矩阵

### M1 身体重定向

| 能力 | 状态 | 说明 |
|---|---|---|
| 比例缩放 | ✅ | 身高比缩放 root/IK 位移 |
| 脊柱链拆分 | ✅ | `上半身` 均分到 `上半身/1/2` |
| 手臂两骨 IK | ✅ | 手腕目标误差 max 4e-5 单位 |
| 接触检测 | ✅ | 足 IK 目标，误差 0.1–2.3 mm |
| 承重判断 | ✅ | 骨盆投影，跳过 156 个摆动窗口 |
| 分窗脚锁 | ✅ | 20 帧窗口，锚定到均值 |
| 锚定式平滑 | ✅ | 锁定帧不动；步长 2.744→0.126 |
| 间隙约束 | ❌ | 手臂仍可能插进躯干 |
| 骨盆补偿 | ❌ | 53 个 reach 窗口被跳过 |
| twist roll 恢复 | ❌ | 腕捩/手捩被清成 identity |
| 跨模型验收 | ❌ | 本地只有一个人类模型 |

### M2 检测与报告

| 能力 | 状态 | 说明 |
|---|---|---|
| BVH 相交 | ✅ | 8 个部位对 |
| 穿透深度 | ✅ | 顶点到表面最近距离（近似） |
| severity | ✅ | 2 / 10 / 30 mm |
| CSV / JSON | ✅ | |
| 回归 diff | ✅ | new/fixed/worse/better |
| 回归门槛 | ✅ | `--max-new/--max-worse` 退出码 1 |
| 相机可见性 | ✅ | 单点射线 |
| high 帧缩略图 | ✅ | Cycles CPU 320×320 |
| timeline marker | ✅ | headless 需手动保存 .blend |
| contact sheet | ❌ | |
| 多机位 | ❌ | |
| 部位规则配置化 | ❌ | 目前硬编码日文关键字 |
| 多点可见性 | ❌ | 只测最深顶点 |

## 2. 关键数字

| 项 | 数值 |
|---|---|
| 真实 VMD 解析 | 2.9 MB / 140 骨 / 0.086 s |
| 压力测试 | 789,600 帧 / 3.40 s |
| 真实 PMX 解析 | 6.4 MB / 63k 顶点 / 550 骨 / 0.35 s |
| 同骨架回写 | 25,973 帧，旋转 3e-6°，位移 0 |
| 脚锁覆盖率 | 15.1%（1,708 帧），窗口内漂移 0 |
| 全片最大步长 | 0.126 单位/帧（限速 0.130） |
| 手臂 IK 手腕误差 | mean 3e-8 / max 4e-5 单位 |
| 脊柱链回放 | 上半身中位 7.2 mm，最大 2.8 cm |
| M2 采样 | 282 帧 / 24 s / 1,051 条 |
| M2 可见性 | 288 可见，37 可见 high（全为腿–裙） |
| M2 缩略图 | 43 张 / 4.4 MB；全量 126 s |

## 3. 常用命令

```bash
# 数据层
python -m mmd_retarget.cli inspect model.pmx
python -m mmd_retarget.cli skeleton model.pmx -o profile.json
python -m mmd_retarget.cli inspect motion.vmd -p profile.json -o motion.json

# 重定向（M1）
python -m mmd_retarget.cli retarget motion.json \
  -s src_profile.json -t dst_profile.json -o out.vmd

# 检测（M2，需要 Blender）
blender -b --python tools/blender_cli.py -- validate \
  --model model.pmx --motion out.vmd \
  -o report.csv --json report.json --step 20 \
  --visibility --thumbnails thumbs/
```

## 4. 下一步优先级

1. **间隙约束**：手臂/手–躯干胶囊或 BVH，推动手腕目标并重解 IK；
2. **骨盆补偿**：53 个不可达窗口，移动 root 而不是跳过；
3. **twist roll**：把绕骨轴分量从源捩骨恢复；
4. **contact sheet + 多机位缩略图**；
5. **跨模型验收**：需要第二副体型差异明显的 PMX；
6. **部位规则配置化**；
7. **全帧检测接 CI**（先 30 秒样本，`--step 1`）。

## 5. 诚实的边界

- 重定向只在“薇斯纳 → 薇斯纳”上验证过；比例逻辑是合成测试。
- 脚锁只覆盖 15.1% 的脚-帧；其余是迈步或不可达。
- 手臂 IK 保证手腕位置，不保证手/前臂不穿躯干。
- M2 深度是近似值，腿–裙仍可能误报；可见性只测单点。
- 没有渲染级审美验收，只有数值和缩略图。
