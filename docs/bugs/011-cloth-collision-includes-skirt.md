# 011 · 布料碰撞代理包含裙子自身

| 项 | 内容 |
|---|---|
| 日期 / 状态 / 严重度 | 2026-10-26 · 已修 · **高** |
| 发现方式 | C4-B 300 帧首轮：裙片被顶回腰部/塌成一团 |
| 修复提交 | 本轮 C4-B 提交 |
| 相关报告 | `docs/reports/34-c4b-300.md` |

## 现象

`skirt_cloth.py` 跑完 300 帧后，裙摆不是下垂，而是缩在腰部；M2 的
leg–skirt 记录从 45 掉到 2（不是修好，是裙子没了）。

## 根因

`_collision_proxy(body, ratio)` 直接复制整个身体网格做碰撞体，
**连裙片一起复制**。布料在和自己的一份静态拷贝碰撞，被顶回腰部。

## 修复

碰撞代理里按材质索引删除裙片面：

```python
doomed = [f for f in bm.faces if f.material_index in exclude_materials]
bmesh.ops.delete(bm, geom=doomed, context="FACES")
```

调用：`_collision_proxy(body, args.proxy_ratio, mat_idx)`。

## 波及面

- 只影响 C4-B；
- C4-A / M3 骨链不使用这个代理；
- 修复后裙摆能正常下垂，但 300 帧仍有漂移/褶皱（见报告 34）。

## 回归

人工：对比修复前后渲染 + leg–skirt 记录数；修复前 2 条（裙子没了），
修复后 99 条（裙子在了，但有穿模）。

## 教训

- 碰撞体要排除被模拟的物体本身；
- “穿模记录变少”不一定是变好，可能是物体消失了；
- 视觉验收必须先于数字结论。
