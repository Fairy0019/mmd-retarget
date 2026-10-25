# 008 · root 合并要求 センター 先有位移，导致 グルーブ-only 动作丢根运动

| 项 | 内容 |
|---|---|
| 日期 / 状态 / 严重度 | 2026-10-25 · 已修 · **高** |
| 发现方式 | 任务 1.2 验收：纯 `グルーブ` 样本的 `root.merged_bones` 为空 |
| 修复提交 | 任务 1.2 提交 |
| 相关报告 | `docs/reports/23-task1-2-root-merge.md` |

## 现象

动作的位移只打在 `グルーブ`（或 `全ての親`）上、`センター` 没有位移键时，
`canonical.root.pos` 是空的，`merged_bones` 也不存在。重定向后角色原地踏步。

## 根因

`_merge_extra_roots()` 开头：

```python
if not root.get("pos"):
    return root
```

这是为了“没有根位移就不折腾”，但 `root.pos` 为空恰好意味着**只有
非 センター 的根位移**，正是最需要合并的情况。逻辑写反了。

## 修复

不再提前 return；没有基础位移时用全零序列作为基底：

```python
base_pos = root.get("pos") or [[float(f), 0.0, 0.0, 0.0] for f in range(frames)]
...
x, y, z = sample_keys(base_pos, frame, quat=False)
```

## 为什么这么修

- 合并是“求和”，零是合法基底；
- 保持原有的“有 センター 位移时叠加”的行为不变；
- 不引入新的配置分支，避免调用方漏传。

## 波及面排查

| 位置 | 是否受影响 | 说明 |
|---|---|---|
| `build_canonical` root | 是 | 修复后纯 グルーブ 动作能保留位移 |
| 接触检测 / 脚锁 | 间接 | root 改变髋位置，可能影响 reach/骨盆补偿 |
| writer | 否 | root 仍写 センター |
| 多根旋转 | 否 | 仍只合并**位移**；`グルーブ` 的旋转留在 extra |

## 回归测试

`tests/test_canonical.py::test_root_merges_groove_without_center_translation`

- センター 只有旋转、没有位移；
- グルーブ 从 0 到 (0,0,2)；
- 断言 `merged_bones == ["グルーブ"]` 且 root 末帧 z=2。

## 教训

- **“空”有两种含义**：没有数据 / 数据在别处。合并逻辑要把后者当正常输入；
- 纯 `グルーブ` 动作在 MMD 里很常见，默认测试不能只造 センター 位移。
