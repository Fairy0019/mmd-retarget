# 任务 1.4 · VMD 插值保留验收

- 日期：2026-10-25
- 计划：`docs/plans/2026-10-26-server-next.md` 任务 1.4
- 对象：恋爱循环 5,640 帧 / 140 骨 / 25,973 键
- 结论：**通过**。同骨架回写后 25,973 个键的 64 字节插值**逐字节一致**；
  新生成键仍为线性。

---

## 1. 方法

源模型（初音ミク PMX）不在工作区，因此构造一个“同骨架” profile：

- `rest` 覆盖 VMD 里全部 140 根骨（head/tail 用占位值，仅影响姿势，不影响插值）；
- `map` 只保留 `root: センター`，其余骨作为 extra 原样透传；
- 关闭脚锁 / 手臂 IK / twist / 平滑，避免生成新键。

```bash
mmd-retarget inspect 恋爱循环.vmd -p profile_miku_synth.json -o motion_interp.json
mmd-retarget retarget motion_interp.json \
  -s profile_miku_synth.json -t profile_miku_synth.json \
  -o out_interp.vmd -c noop_retarget.json
```

然后按 `(骨名, 帧号)` 对比源 VMD 与输出 VMD 的 `BoneFrame.interpolation`。

## 2. 结果

| 指标 | 数值 |
|---|---:|
| 源键数 | 25,973 |
| 输出键数 | 25,973 |
| 键集合一致 | ✅ |
| 插值字节完全一致 | **25,973 / 25,973** |
| 新增键 | 0 |
| 最大旋转误差 | 3.4e-6° |
| 最大位移误差 | 0 |

canonical 里 `interpolation` 覆盖 140 根骨 / 25,973 个键（非默认曲线的键
才存，源文件所有键的 64 字节都与我们的“标准线性”填充不同，因此全存）。

## 3. 新键仍为线性

新增回归测试：

```
tests/test_writer.py::test_new_frames_use_linear_interpolation
```

构造一个 0/5/10 帧的关节序列，只在 0/10 提供自定义 64 字节曲线：

- frame 0、10 → 自定义曲线原样写回；
- frame 5（新键）→ 线性曲线。

这覆盖了重定向 IK/物理产生新键时的预期行为：**旧键保曲线，新键线性**。

## 4. 一个测试设置问题

第一次跑时输出少了 987 个 `センター` 键。原因不是插值，而是合成 profile
的 `map` 为空，writer 找不到 `root` 目标骨，直接跳过了根骨。

真实 profile 一定包含 `root`，所以不是产品 bug；但它暴露了一个健壮性缺口：
**canonical 有 root 数据、目标 profile 没有 root 映射时，writer 会静默丢根**。
建议后续在 writer/CLI 加一条告警（当前未改，避免超出任务范围）。

## 5. 边界

- 只验证同骨架回写；换骨架时语义骨旋转会变，插值仍按“同帧同骨”复用，
  但帧号集合可能不同，未做跨骨架字节对比；
- 物理/IK 生成的新键固定线性，不会从源曲线插值；
- 源相机/灯光轨不参与。

## 6. 结论

任务 1.4 **通过**。
