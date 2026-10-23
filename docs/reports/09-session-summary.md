# 阶段总结 · 接管期交付（M0 + M1 stage 1/2）

- 日期：2026-10-23
- 起点：v0.0.1，仓库只有设计文档 + CLI 骨架
- 终点：v0.0.2，M0 数据层完成，M1 完成 stage 2/4
- 测试：**69 passed**
- 提交：11 个（3 个原有 + 8 个本次）

---

## 1. 提交序列

| 提交 | 内容 |
|---|---|
| `158e299` | VMD 无损读写 + `inspect` |
| `38e4af5` | PMX 解析 + skeleton profile |
| `2e8f5c2` | canonical + writer |
| `7928253` | M0 文档与总结（报告 01–04） |
| `d3d8f02` | FK 对拍；接触检测改用足 IK（报告 05） |
| `8db22c1` | M1 stage 1：比例 + 分窗脚锁（报告 06） |
| `5b04eb5` | M1 stage 2：脊柱链拆分 + 回放验证（报告 07） |
| `2358a5a` | 时间平滑尝试回滚（报告 08） |

## 2. 实测数字

### 数据层

| 项 | 数值 |
|---|---|
| 真实 VMD 解析 | 2.9 MB / 140 骨 / 25,973 帧 / 0.086 s |
| VMD 压力测试 | 140×5640 = 789,600 帧 / 3.40 s（目标 < 10 s） |
| 真实 PMX 解析 | 6.4 MB / 63,278 顶点 / 550 骨 / 0.35 s |
| VMD round-trip | **字节完全一致** |
| PMX → profile | 89/97 语义；19 胶囊；2 个 IK 限位；176 KB |
| 同骨架回写 | 25,973 帧，旋转误差 **3e-6°**，位移误差 **0** |
| 换骨架回写 | 23,266 / 25,973 帧（丢的 63 根全是物理/显示骨） |

### 重定向

| 项 | 数值 |
|---|---|
| 非 IK 骨 FK vs Blender | 中位 **1.2 mm**，p95 2.6 cm |
| 足 IK 目标 vs Blender 脚踝 | **0.1–2.3 mm** |
| 接触段 | 249 段，覆盖 67.4% 的“脚-帧” |
| 脚锁 | 189/493 窗口，3,026 帧（26.8%），窗口内漂移 **~0** |
| 脊柱链回放 | 上半身位置中位 **7.2 mm**，最大 2.8 cm |
| 时间平滑 | 最大步长 2.74→0.13，但窗口漂移 0.97 → **回滚** |

## 3. 抓到的五个真问题

1. **PMX bone flags 位偏移**：`0x0100` 是“回転付与”不是“轴固定”。
   真实文件 46 根轴固定骨，错了会全盘错位。
2. **VMD 骨名 0xFD 填充**：只按 NUL 截断会把 `センター` 解码成
   `センター`。
3. **相机段 count=0 但仍有记录**：严格解析会把自阴影数读成 49676；
   现在原样存入 trailer 并告警。
4. **root 的 0 位移键被吞**：writer 把 -0.4 外推到首帧，角色整体下沉；
   修复为“有位移的骨保留全部位置键”。
5. **腿是 IK 驱动**：纯旋转 FK 推脚踝最大错 61 cm；改用 `足IK` 目标后
   误差 0.1–2.3 mm。这是全项目最重要的一次对拍。

外加一个**负结果**：全局限速平滑会把锁定窗口内部拖走 8.4 cm，已回滚，
原因和正确做法写在报告 08。

## 4. 已验证 vs 仍是假设

**已验证**

- VMD / PMX 2.0 格式与字节级往返；
- 非 IK 骨的 `parent_world * local` FK；
- 足 IK 目标 = 脚踝世界位置（mm 级）；
- 脚锁窗口内漂移为 0；
- 脊柱链拆分后末端朝向保持（mm 级）。

**仍是假设**

- 跨体型比例适配（本地只有一个人类模型，没做真实跨模型）；
- MMD 运行时 IK 与 Blender/MMD Tools 完全一致；
- 1.6 m 身高换算（阈值用）；
- 线插值 vs 源贝塞尔曲线（贡献了约 7 mm 偏差）；
- 视觉可接受性（没有渲染对比）。

## 5. 未完成（按优先级）

### M1 stage 3

1. 承重判断（骨盆投影 + 另一只脚状态），提高可锁覆盖率；
2. 骨盆补偿，解决 49 个“脚够不到”的窗口；
3. **锚定式平滑**：锁定窗口内不动，只在未锁定段过渡；对修正量做
   膨胀→平均→限速；
4. 手臂 IK + 极向量 + 胶囊间隙（profile 里 19 个胶囊只是初值）；
5. 贝塞尔控制点进 canonical；
6. 第二副体型差异明显的 PMX 做跨模型验收。

### M2

- Blender BVH 自相交 + 穿透深度；
- 最终机位可见性；
- severity / CSV / marker / 缩略图；
- 回归 diff。

### M3

- 裙/发/袖 PBD 骨链 + 胶囊碰撞 + 烘焙。

### M4

- `physics` / `validate` 子命令；
- 示例与 30 分钟跑通。

## 6. 继续工作的入口

```bash
cd /root/mmd-retarget
.venv/bin/python -m pytest -q                 # 69 passed
.venv/bin/python tools/bench_vmd.py           # 性能基准

PYTHONPATH=src .venv/bin/python -m mmd_retarget.cli \
  skeleton /root/mmd-vision/assets/model/薇斯纳.pmx -o /tmp/profile.json
PYTHONPATH=src .venv/bin/python -m mmd_retarget.cli \
  inspect /root/mmd-vision/assets/motion/恋爱循环.vmd -p /tmp/profile.json -o /tmp/motion.json
PYTHONPATH=src .venv/bin/python -m mmd_retarget.cli \
  retarget /tmp/motion.json -s /tmp/profile.json -t /tmp/profile.json -o /tmp/out.vmd

# Blender 回放对拍
blender -b --python tools/blender_dump_pose.py -- \
  /root/mmd-vision/assets/model/薇斯纳.pmx /tmp/out.vmd /tmp/dump.json
python tools/compare_fk.py /tmp/profile.json /tmp/motion.json /tmp/dump.json
```

## 7. 给接手人的三句话

1. **先看报告 05**：脚的轨迹必须用 `足IK`，不要用腿骨 FK。
2. **改脚锁前先读报告 08**：只优化“最大步长”会把脚锁抹平，必须同时
   检查“窗口内漂移”。
3. **不要把 `assets/` 里的模型/动作提交**：`.gitignore` 已挡住
   `*.pmx` / `*.vmd`，但新增素材类型时要补规则。
