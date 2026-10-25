# 009 · `physics --skirt` 是空开关

| 项 | 内容 |
|---|---|
| 日期 / 状态 / 严重度 | 2026-10-25 · 已修 · **高** |
| 发现方式 | 任务 3 的 CI 负向测试：加 `--skirt` 后报告完全不变 |
| 修复提交 | 任务 3 提交 |
| 相关报告 | `docs/reports/28-task3-ci.md` |

## 现象

```bash
mmd-retarget physics motion.json -p profile.json -o out.json --skirt
```

输出里没有任何 `skirt:*` 链，验证结果与不加 `--skirt` 完全一致。
命令不报错，只是**什么都没发生**。

## 根因

`cli.py` 的 `cmd_physics` 只读了两个开关：

```python
if args.no_skirt: chains["skirt"] = False
if args.no_hair:  chains["hair"] = False
```

parser 里虽然有 `--skirt`，但从来没有被读取。默认 `chains.skirt=false`，
所以 `--skirt` 永远无法开启裙摆。

## 修复

```python
if args.skirt:    chains["skirt"] = True
if args.no_skirt: chains["skirt"] = False
```

`--no-skirt` 放后面，保证“同时传两个”时以关闭为准。

## 波及面排查

| 位置 | 是否受影响 | 说明 |
|---|---|---|
| `physics --skirt` | 是 | 之前全部是空操作 |
| `physics -c config.json` | 否 | 配置文件里的 `chains.skirt` 一直有效 |
| 报告 17 的裙摆数据 | **需复核** | 若当时用 `--skirt` 跑，则实际只跑了头发；从结论看更像用了配置 |
| C4-A 验收 | 是 | 本轮一开始也用 `--skirt`，发现无变化后才定位到这里 |

## 回归测试

`tests/test_cli.py::test_physics_skirt_flag_is_honored`

- 构造 `Q_*` 裙骨链；
- 调 CLI `physics --skirt`；
- 断言输出 `meta.physics.chains` 里存在 `skirt:*`。

## 教训

- **parser 里有的参数不等于代码里用了**；每个开关至少要有一个断言它生效的测试；
- “加了参数但结果没变”要先怀疑开关没接线，而不是参数没用；
- 负结果实验尤其危险：空开关会让“无效”看起来像“这个方案没用”。
