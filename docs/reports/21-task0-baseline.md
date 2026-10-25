# 任务 0 · 同步与基线检查

- 日期：2026-10-25
- 计划：`docs/plans/2026-10-26-server-next.md` 任务 0
- 基线：`ba27c0f`（v0.1.1）
- 结论：**基线通过，可以开始任务 1。**

---

## 1. 同步

```text
git pull --ff-only origin main
HEAD = ba27c0f  docs: 新增服务器下一步计划（验收/C4/CI/跨模型/发布）
工作区干净，无未提交/未跟踪文件
```

新增的两个提交：

- `25d3a5a` feat: 补齐 v0.1.1 缺口（头发分组/根合并/morph/插值/视觉验收/C4-A）
- `ba27c0f` docs: 新增服务器下一步计划

## 2. 基线命令

```text
$ .venv/bin/python -m pytest -q
99 passed in 0.43s

$ .venv/bin/mmd-retarget --version
mmd-retarget 0.1.1
```

## 3. 环境

| 项 | 版本 |
|---|---|
| Python | 3.12.15（venv） |
| pytest | 9.1.1 |
| Blender | 5.2.2 LTS |
| MMD Tools | `bl_ext.user_default.mmd_tools` |
| 素材 | `/root/mmd-vision/assets/`（私有，不入库） |

## 4. 素材边界

`git ls-files` 中没有 `.pmx/.vmd/.blend/.png`；模型/动作只在私有目录。
后续所有验收输出写到 `/tmp/opencode/` 或私有 `renders/`，不提交。

## 5. 结论

- 代码、测试、版本与计划一致；
- 没有需要先修的基线问题；
- 开始任务 1.1（头发分组验收）。
