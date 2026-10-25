# 任务 1.3 · morph 映射验收

- 日期：2026-10-25
- 计划：`docs/plans/2026-10-26-server-next.md` 任务 1.3
- 对象：恋爱循环 → 薇斯纳 profile（morph 名人为改写）
- 结论：**通过**。输出 VMD 使用目标名，映射后的表情帧数 > 0，旧名/缺失名被正确丢弃。

> 说明：工作区没有第二副带表情的人类模型（只有薇斯纳 + 四把武器），
> 因此用“同一骨架 + 改写 morph 名”的合成目标 profile 验证映射链路，
> 而不是假装跑了第二副模型。

---

## 1. 方法

源 canonical：`motion2.json`，31 个 morph。

目标 profile：复制薇斯纳 profile，做三件事：

1. 改名：`まばたき→blink`、`笑い→smile`、`怒り→angry`、`ウィンク→wink`；
2. 从目标 `morphs` 列表里删掉 `にこり`（模拟目标模型没有这个表情）；
3. 其余保持。

映射表：

```json
{"まばたき":"blink","笑い":"smile","怒り":"angry","ウィンク":"wink"}
```

```bash
mmd-retarget retarget motion2.json \
  -s profile2.json -t profile_synth.json \
  -o out_morph.vmd --morph-map morph_map.json \
  -c configs/retarget.json
```

## 2. 结果

输出 VMD 解析：

| 目标 morph | 帧数 |
|---|---:|
| blink | 137 |
| smile | 61 |
| angry | 1 |
| wink | 22 |
| まばたき（旧名） | 0 |
| にこり（目标缺失） | 0 |

- 输出共 20 个 morph 名 / 2,305 帧；
- 旧名一个都没漏；
- `にこり` 被丢弃（目标 `morphs` 里没有，且没有映射）；
- 源 31 个 morph 中有 11 个没有进入输出，原因是目标 profile 里没有**精确同名**
  （例如 `base`、`ｳｨﾝｸ２右` 等变体）。这是预期行为：精确匹配不上的必须
  由映射表覆盖，不能静默猜。

## 3. 判读

- **通过标准**：输出 VMD 的表情名是目标名，数量 > 0。满足；
- 映射只作用于 morph 名，不影响 morph 的帧号/权重；
- 目标模型没有的 morph 会被丢弃，不会写出无效名。

## 4. 边界

- 没有真实第二副人类模型，无法验证 MMD 里“表情是否真的动”；
- 映射表是人工 JSON，没有自动模糊匹配；31→20 的缺口需要人来补；
- `physics --vmd` 也支持 `--morph-map`，本轮未单独跑（走同一个 writer 函数）。

## 5. 结论

任务 1.3 **通过**。真实跨模型验收仍需第二副 PMX（任务 4）。
