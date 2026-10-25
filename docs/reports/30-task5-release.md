# 任务 5 · 发布收尾 v0.1.1

- 日期：2026-10-25
- 计划：`docs/plans/2026-10-26-server-next.md` 任务 5
- 结论：已打 tag `v0.1.1` 并创建 GitHub Release；测试 **102 passed**。

---

## 1. 发布内容

- CHANGELOG 补齐本轮验收/CI/两个 bug 修复；
- 发布说明：`docs/releases/v0.1.1.md`；
- tag：`v0.1.1`；
- GitHub Release：`v0.1.1`。

## 2. 验收汇总

| 任务 | 结果 |
|---|---|
| 1.1 头发分组 | ✅ high 0=0；≥5 mm 76<82 |
| 1.2 根合并 | ✅ 修 bug 008；位移 +2.0 保留 |
| 1.3 morph 映射 | ✅ 2,305 帧目标名 |
| 1.4 插值保留 | ✅ 25,973/25,973 字节一致 |
| 1.5 视觉验收 | ✅ 10 张 / 0 黑图；`--clay` |
| 2 C4-A | ❌ 无收益；转路线 B |
| 3 物理 CI | ✅ 裙摆回归 exit 1 |
| 4 跨模型 | ⚠️ 阻塞（缺第二副 PMX） |
| 5 发布 | ✅ v0.1.1 |

## 3. 已知问题

1. 裙摆 C4-A 失败，骨链物理默认关闭；
2. 真实跨模型矩阵未完成；
3. 带材质渲染时 `袜` 类材质在 Cycles 下隐形，几何验收需 `--clay`；
4. `physics --skirt` 空开关已修（bug 009），历史裙摆数据来源需复核。

## 4. 复现

```bash
.venv/bin/python -m pytest -q       # 102 passed
.venv/bin/mmd-retarget --version    # 0.1.1
```
