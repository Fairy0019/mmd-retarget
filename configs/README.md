# 配置模板

| 文件 | 用途 |
|---|---|
| `retarget.json` | 比例、脚锁、骨盆补偿、手臂 IK/间隙、twist、平滑 |
| `physics.json` | 头发/裙摆 PBD 参数；默认 `skirt: false`（骨链会把腿顶穿） |
| `parts.json` | M2 部位划分规则；换非日文命名的模型时覆盖 |
| `parts.lumine.json` | 英文材质名的示例（Lumine：Skirt/Hair） |

`retarget` / `physics` 用 `-c configs/xxx.json`；`validate` 用
`--parts-config configs/parts.json`。文件只需要写想覆盖的字段，其余走默认值。

### 换模型时最常改的项

- `foot_lock.assumed_height_m`：模型不是 1.6 m 时改这里，否则毫米阈值会漂；
- `foot_lock.max_lock_drift_m`：脚滑得厉害的动作可放宽到 0.06–0.08；
- `arm_ik.clearance_m`：衣服很厚时增大到 0.02–0.03；
- `physics.chains.skirt`：默认关；开了要自己看 M2 报告，骨链不是布料。
