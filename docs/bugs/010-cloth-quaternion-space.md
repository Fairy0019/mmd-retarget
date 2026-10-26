# 010 · C4-B 烘焙把 Q 骨转成 180°（四元数顺序 + 空间混用）

| 项 | 内容 |
|---|---|
| 日期 / 状态 / 严重度 | 2026-10-26 · 已修 · **高** |
| 发现方式 | 300 帧 C4-B 渲染：裙子消失；检查 Q 骨角度 179° |
| 修复提交 | 本轮 C4-B 提交 |
| 相关报告 | `docs/reports/34-c4b-300.md` |

## 现象

`skirt_cloth.py` 烘焙后的 .blend 里，几乎所有 `Q_*` 骨的局部旋转都在
**170–179°**；裙片被折到腰上/消失。5 帧冒烟只看“链路通”，没看角度。

## 根因（两层）

1. **四元数构造顺序**：代码里 `q` 是 `(x,y,z,w)`，却写成
   `Quaternion(q)`；Blender 的构造顺序是 `(w,x,y,z)`，于是每个骨都多转了
   180°。
2. **空间混用**：即使修正顺序，`rest_dir`（armature 空间）直接和
   `pq^-1 * desired`（父骨 pose 空间）做 `rotation_difference`，子骨仍会
   出现 70–170° 的假旋转。

## 修复

```python
# 1) 世界空间最短弧，保持 rest roll
R_delta = rest_dir_world.rotation_difference(desired)
R_pose_b = R_delta @ R_rest_b

# 2) pose = parent_pose * (parent_rest^-1 * bone_rest) * local
base = pq @ (parent_rest_q.inverted() @ R_rest_b)
local = base.inverted() @ R_pose_b

# 3) Blender 四元数是 (w,x,y,z)
pb.rotation_quaternion = Quaternion((local.w, local.x, local.y, local.z))
```

修后 Q_0_0 为 1.23°（合理），裙片重新出现。

## 波及面

| 位置 | 影响 |
|---|---|
| C4-B 裙摆烘焙 | 之前完全不可用（裙子消失） |
| 报告 33 的“5 帧冒烟通过” | 只证明链路，不证明旋转正确；结论需降级 |
| 其他用 `Quaternion((x,y,z,w))` 的代码 | 需要全局搜一遍 |

## 回归

Blender-only 工具，暂无单测；本轮用
`check_q.py` 人工断言 Q_0_0 角度 < 5°。建议以后给烘焙加“角度上限/rest
方向一致性”断言。

## 教训

- 5 帧冒烟必须包含**数值断言**，不能只看“没报错”；
- Blender API 的四元数顺序是高频坑；
- 空间口径（armature / parent pose / bone local）要在注释里写清楚。
