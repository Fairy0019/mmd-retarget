# 任务 3 · 物理接 CI

- 日期：2026-10-25
- 计划：`docs/plans/2026-10-26-server-next.md` 任务 3
- 脚本：`tools/ci_physics.sh`
- 结论：**通过**。固定 900 帧样本，基线 diff 0/0；把裙摆物理打开后
  CI 以退出码 1 拦住回归。

---

## 1. 脚本

```bash
MODEL=... MOTION=... ./tools/ci_physics.sh                 # 首次建基线
MODEL=... MOTION=... ./tools/ci_physics.sh                 # 回归检查
UPDATE_BASELINE=1 MODEL=... MOTION=... ./tools/ci_physics.sh
```

流程：

1. 生成 src/dst profile；
2. `inspect` → canonical；
3. `retarget`（configs/retarget.json）；
4. `physics`（默认头发，configs/physics.json）；
5. `validate --step 5 --start 0 --end 899`（180 帧）；
6. 有基线时加 `--diff baseline.csv --max-new 0 --max-worse 0`，超限退出 1。

单次约 **2 分钟**（物理 47 s + 验证 15 s + 其它）。

## 2. 基线

首次运行：

```
records  : 662
severity : high 19 / medium 352 / low 291
max depth: 69.47 mm
```

同配置再跑一次：

```
diff : new 0, fixed 0, worse 0, better 0
regression: OK
exit 0
```

证明物理与验证都是确定性的。

## 3. 负向测试：裙摆物理

用 `PHYSICS_EXTRA=--skirt` 跑同一基线：

```
records  : 862
severity : high 58 / medium 514 / low 290
max depth: 100.93 mm
diff     : new 217, fixed 17, worse 84, better 39
exit 1
```

CI 正确拦住回归。顺带再次确认：**裙摆骨链会把腿顶穿**，与报告 17/27
一致；不要启用。

## 4. 修掉的 bug

第一次负向测试加 `--skirt` 时结果完全没变，定位到：
`cmd_physics` 从来没读 `args.skirt`，开关是空的。

复盘见 [`docs/bugs/009-physics-skirt-flag-noop.md`](../bugs/009-physics-skirt-flag-noop.md)；
新增 CLI 回归测试 `test_physics_skirt_flag_is_honored`。

> 这会影响报告 17 的裙摆数据来源判断：若当时用 `--skirt` 跑的，实际只跑了
> 头发。报告 17 的“裙摆负结果”方向仍然成立（本轮用配置/修好的开关复现了
> 更严重的回归），但具体数字需要按配置重跑才能引用。

## 5. 边界

- CI 不跑 `--visibility`（依赖相机/场景，且更慢）；
- 只覆盖前 900 帧；全片回归需要 `END=5639`（约 10 分钟）；
- 基线是“当前代码”的快照，不是绝对标准；更新基线要显式
  `UPDATE_BASELINE=1`；
- 还没接 GitHub Actions（runner 没装 Blender/MMD Tools），目前是脚本级 CI。

## 6. 结论

任务 3 **通过**。下一步任务 4（跨模型矩阵）。
