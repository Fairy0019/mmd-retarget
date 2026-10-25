# 服务器下一步计划

- 日期：2026-10-26
- 基线：`25d3a5a` · v0.1.1 · 99 tests
- 原则：**先验收已写的，再开发新的**；每项都要有数字或截图，不接受“应该可以”。

## 任务总表

| # | 任务 | 预计 | 优先级 | 产出 |
|---|---|---|---:|---|
| 0 | 同步与基线检查 | 10 min | P0 | `pytest` / 版本输出 |
| 1 | 验收 v0.1.1 五项改动 | 半天 | P0 | 每项一段结论 + 数字 |
| 2 | 裙摆 C4-A 验收 | 1 天 | P1 | 权重版工程 + 对比数据 |
| 3 | 物理接 CI | 半天 | P2 | `tools/ci_physics.sh` / workflow |
| 4 | 跨模型矩阵 | 半天 | P2 | 两副模型的复现结果 |
| 5 | 发布收尾 | 30 min | P3 | tag `v0.1.1` + Release |

---

## 0. 同步与基线

```bash
cd /root/mmd-retarget
git pull
.venv/bin/python -m pytest -q          # 期望 99 passed
.venv/bin/mmd-retarget --version       # 期望 0.1.1
```

不通过就先修基线，不要往下做。

## 1. 验收 v0.1.1 的五项（未跑过）

### 1.1 头发分组

- 默认参数 vs 把 `hair_groups.side` 设成和 `back` 一样，各跑一次 282 帧验证；
- 比较 `hair-torso` 的 high 数、max depth；
- **通过**：分组版不高于对照组，侧发不插肩。

### 1.2 根运动合并

- 用 `グルーブ` / `全ての親` 的动作（没有就合成 300 帧样本）；
- 检查 canonical 的 `root.merged_bones`；
- 对比合并前后脚锁覆盖率、平均滑步；
- **通过**：位移不丢、滑步不反弹。

### 1.3 morph 映射

- 用第二副模型 + `--morph-map`；
- **通过**：输出 VMD 的表情名是目标名，数量 > 0。

### 1.4 插值保留

- 真实 VMD：`inspect` → 同骨架 `retarget` → 解析输出；
- 对比透传骨（头发/裙/物理骨）的 64 字节插值；
- **通过**：同帧同值的键字节一致；新生成键仍线性（预期）。

### 1.5 视觉验收工具

```bash
blender -b scene.blend --python tools/render_acceptance.py -- \
  --out ../renders/acc --frames 0:300:30 --camera 机位_近景
```

- **通过**：4–10 张图可直接用于人工判断（构图、曝光、无黑图）。

## 2. 裙摆 C4-A 验收

```bash
# 1) 干跑
blender -b scene.blend --python tools/skirt_reweight.py -- \
  --out scene_rw.blend --materials 裙,裙内 --dry-run

# 2) 改权重
blender -b scene.blend --python tools/skirt_reweight.py -- \
  --out scene_rw.blend --materials 裙,裙内

# 3) 物理 + 验证
mmd-retarget physics motion.json -p profile.json -o phys_skirt.json --vmd phys_skirt.vmd --skirt
blender -b scene_rw.blend --python tools/blender_validate.py -- \
  --motion phys_skirt.vmd --out skirt.csv --step 5 --start 0 --end 299 --visibility
```

- **通过**：`leg-skirt` 的 high 不高于原始；缩略图无明显接缝/穿出；
- 不达标 → 按 `docs/design/C4-skirt.md` 转路线 B（布料），不要回头调骨链参数。

## 3. 物理接 CI

- 固定 900 帧样本（`--step 5`）；
- `validate --diff baseline.csv --max-new 0 --max-worse 0`，超限退出码 1；
- 写 `tools/ci_physics.sh` 或 GitHub Actions；
- **通过**：改参数后 CI 能拦住回归。

## 4. 跨模型矩阵

- 把第二副 PMX（体型差异明显）放进私有素材目录；
- `skeleton → retarget → validate`，记录手腕误差、脚滑、身体穿透、pelvic 窗口；
- **通过**：两副模型结果可复现，不劣于薇斯纳基线。

## 5. 发布收尾

```bash
git tag -a v0.1.1 -m "v0.1.1: 头发分组/根合并/morph/插值/视觉验收/C4-A"
git push origin v0.1.1
gh release create v0.1.1 --notes-file CHANGELOG.md
```

## 6. 不要做

1. 不要再调 `skirt_shape_stiffness`、`collision_margin_units`、`use_mesh_radius`
   ——报告 17/19 已证明是负结果；
2. 不要把模型/动作/音乐提交进公开仓库；
3. Blender 验证前先把 `scene.frame_current = 0` 再 `import_vmd`
   ——MMD Tools 会按当前帧偏移，之前因此误判过物理“坏了”。

## 7. 交付要求

每个任务完成后：

1. 提交一份 `docs/reports/NN-*.md`，写数字、命令、结论；
2. 若发现真 bug，按 `docs/bugs/` 模板补一份复盘；
3. 更新 `docs/PLAN.md` 与 `CHANGELOG.md`；
4. 在下面表格里登记结果。

| 任务 | 状态 | 结论 / 数字 | 提交 |
|---|---|---|---|
| 0 基线 | ✅ | 99 passed / v0.1.1 / ba27c0f | 报告 21 |
| 1.1 头发分组 | ✅ | 388/240 条，high 0=0；≥5mm 76<82；侧发 pushes -3.3% | 报告 22 |
| 1.2 根合并 | ✅ | 位移 +2.0 保留；覆盖率 13.38→13.33%；滑步 0.0423→0.0405；修 bug 008 | 报告 23 |
| 1.3 morph 映射 | ✅ | blink 137 / smile 61 / angry 1 / wink 22；旧名 0；缺失名丢弃 | 报告 24 |
| 1.4 插值保留 | ✅ | 25,973/25,973 键 64 字节一致；新键线性 | 报告 25 |
| 1.5 视觉验收 | ⬜ | | |
| 2 C4-A | ⬜ | | |
| 3 CI | ⬜ | | |
| 4 跨模型 | ⬜ | | |
| 5 发布 | ⬜ | | |
