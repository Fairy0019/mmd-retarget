# 阶段总结 · M0 数据层完成

- 日期：2026-10-23
- 版本：v0.0.2
- 范围：STEPS ①–④ + ⑨（VMD / PMX / profile / canonical / writer）
- 状态：**M0 全部验收项通过**（除“可视化对比”需要 Blender，留到 M1 首日）

---

## 1. 交付清单

| 步骤 | 文件 | 状态 |
|---|---|---|
| ① VMD 读写 | `src/mmd_retarget/vmd.py` | ✅ 字节级 round-trip |
| ② PMX 解析 | `src/mmd_retarget/pmx.py` | ✅ 真实 6.4 MB 模型 |
| ③ 骨架档案 | `src/mmd_retarget/skeleton.py` | ✅ 89/97 语义 + 19 胶囊 |
| ④ canonical | `src/mmd_retarget/canonical.py` | ✅ 语义化 + 接触段 |
| ⑨ writer | `src/mmd_retarget/writer.py` | ✅ 同模型数值一致 |
| CLI | `inspect / skeleton / retarget` | ✅ 可用 |
| 测试 | `tests/` 56 个 | ✅ 全绿 |
| 报告 | `docs/reports/01`–`04` | ✅ |

## 2. 关键数字

| 指标 | 目标 | 实测 | 余量 |
|---|---|---|---|
| VMD 5640×140 解析 | < 10 s | **3.40 s** | 2.9× |
| 真实 VMD 2.9 MB 解析 | — | 0.086 s | — |
| 真实 PMX 6.4 MB 解析 | — | 0.35 s | — |
| 同骨架 round-trip 旋转 | < 0.1° | **0.000003°** | 3 万倍 |
| 同骨架 round-trip 位移 | < 0.1 mm | **0** | — |
| 语义映射 | > 95% | 91.8%（缺的 8 个模型本身没有） | 见 §4 |
| 换骨架关键帧保留 | — | 23,266 / 25,973（89.6%） | 丢的全是物理骨 |

真实素材：

- 动作：`恋爱循环.vmd`，140 骨、25,973 关键帧、2,344 morph 帧、188 秒；
- 模型：`薇斯纳.pmx`，63,278 顶点、77,167 三角形、550 骨、38 材质、67 morph。

## 3. 过程中抓到的四个真 bug

### 3.1 PMX bone flags 位偏移

第一版按网上文档把 `0x0100` 当“轴固定”。真实文件在 `左目`
（flags `0x011A`）处暴露：正确含义是“回転付与”，只占 6 字节；按 12 字节
读会错位，550 根骨全废。以 MMD Tools 源码为准修正后通过。

**教训**：格式文档必须用真实文件交叉验证；解析器的第一个不合理长度
必须立即报错。

### 3.2 VMD 骨名 0xFD 填充

第三方 VMD 用 `0xFD` 而不是 `0x00` 填充骨名。只按 NUL 截断会把
`センター` 解成 `センター`。修复：解码时 rstrip `0xFD`，同时保留
原始 15 字节，写回时优先使用，从而做到字节级 round-trip。

### 3.3 相机段 count=0 但后面仍有记录

样本文件 morph 段之后 `camera_count = 0`，却紧跟一条合法的 61 字节相机
记录，再之后才是 `light_count = 0`。严格解析会把自阴影数量读成 49676。

处理：`strict=False` 把从相机段开始的 69 字节整体存为 trailer，写回原样；
CLI 明确警告“有 69 字节未解析”。**没有假装它不存在。**

### 3.4 root 的 0 位移关键帧被吞掉

canonical 第一版只记录非零位移。`センター` 第 0 帧的 (0,0,0) 被丢掉，
writer 采样时把后面的 -0.4 外推到首帧，角色整体下沉 0.4 单位。

修复：先扫描“有位移的骨”，对这些骨保留全部位置键（含 0）。round-trip
测试专门加了“逐帧位移误差 = 0”来盯这类问题。

## 4. 诚实的缺口

这些不是“以后再说”，而是 M1 开始前必须知道的：

1. **没有源模型 profile**。本地只有目标模型 `薇斯纳.pmx`，没有初音ミク的
   PMX，所以“同骨架 round-trip”用的是人工构造的占位 rest，只能证明
   数据层无损，不能证明 FK 正确。
2. **FK 没有和 Blender 对过**。接触段依赖简化的 `parent_world * local`
   复合，忽略了 roll 和 rest 朝向。M1 第一件事就是在 Blender 里导入
   PMX+VMD，对比脚踝世界坐标，量化误差。
3. **没有可视化对比**。“曲线重合”验收项需要 Blender 画曲线/渲染，M0
   只做了数值对比。
4. **换骨架的 89.6% 保留率不是缺陷**：丢掉的 63 根骨是头发/裙/袖/显示骨。
   但这也意味着 M0 的输出“衣服不动”，必须等 M3。
5. **接触段是初值**。249 段、平均滑步 0.154 单位/帧，说明源动作在“贴地”
   阶段仍在移动。M1 的脚锁要把这些段钉住，而不是照单全收。
6. **根运动只认 センター**。用 `グルーブ` 的动作会丢位移，M1 必须支持
   多根骨。
7. **插值曲线丢失**。关键帧数值一致，曲线形状统一变成线性。
8. **morph 精确同名匹配**。样本 31/31 命中，换模型需要映射表。

## 5. 设计上做对的三个决定

1. **解析层不依赖 Blender**。VMD/PMX/ canonical 都能在纯 Python 下单测，
   这是 56 个测试能在 0.1 秒内跑完的原因。
2. **原样保留未知字节**。VMD 的 header/0xFD/trailer、PMX 的未来字段，
   全部原样写回。这让我们面对第三方脏文件时不会“越修越坏”。
3. **extra 骨透传**。canonical 不强行把物理骨塞进语义层；同模型能完整
   回写，换模型自动丢弃。边界清晰。

## 6. M1 的具体起手式

```bash
# 1) 用 Blender 导入并导出真实 pose matrix
blender -b --python scripts/m1_dump_pose.py -- \
  /root/mmd-vision/assets/model/薇斯纳.pmx \
  /root/mmd-vision/assets/motion/恋爱循环.vmd

# 2) 对比 canonical FK 与 Blender 的脚踝世界坐标
python tools/compare_fk.py pose_dump.npz motion.json

# 3) 若误差 > 2cm，先修 FK，再做 rest-relative retarget
```

M1 的验收顺序建议：

1. 静止 T/A pose 下，目标末端与“按比例缩放的期望位置”误差 < 1 cm；
2. 脚锁后接触段滑步 < 5 mm；
3. 30 秒样本身体穿透 < 2 mm 或白名单；
4. 末端速度无 > 50% 突跳。

## 7. 复现

```bash
.venv/bin/python -m pytest -q
.venv/bin/python tools/bench_vmd.py
PYTHONPATH=src .venv/bin/python -m mmd_retarget.cli \
  skeleton /root/mmd-vision/assets/model/薇斯纳.pmx -o /tmp/profile.json
PYTHONPATH=src .venv/bin/python -m mmd_retarget.cli \
  inspect /root/mmd-vision/assets/motion/恋爱循环.vmd \
  -p /tmp/profile.json -o /tmp/motion.json
PYTHONPATH=src .venv/bin/python -m mmd_retarget.cli \
  retarget /tmp/motion.json -s /tmp/profile.json -t /tmp/profile.json -o /tmp/out.vmd
```
