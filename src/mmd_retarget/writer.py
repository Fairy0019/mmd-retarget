# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""canonical motion → 目标骨架的 VMD。

M0 的职责是**无损回写**：同一份 profile 进来，关键帧旋转/位移与源保持一致。
M1 会在这个 writer 之前插入 rest-relative 适配、脚锁和 IK；writer 本身
不关心这些修正从哪来。

约定
----
- 语义骨写到 ``profile["map"][semantic]`` 对应的目标骨；
- 没有语义映射的 ``extra`` 骨，只在目标 profile 里存在同名骨时透传
  （同一模型 round-trip 成立；换模型时自动丢弃物理骨）；
- 根骨的 pos/rot 关键帧时刻可能不同，合并时在并集帧上采样；
- morph 只在目标模型确实有同名 morph 时写出。
"""
from __future__ import annotations

from .canonical import sample_keys
from .vmd import BoneFrame, MorphFrame, Vmd, encode_interpolation, LINEAR_INTERPOLATION

__all__ = ["canonical_to_vmd"]

_LINEAR64 = encode_interpolation(LINEAR_INTERPOLATION)


def _merge_channels(
    rot_keys: list[list[float]] | None,
    pos_keys: list[list[float]] | None,
    interp: dict[int, bytes] | None = None,
) -> list[tuple[int, tuple[float, float, float], tuple[float, float, float, float], bytes | None]]:
    """把旋转/位移两套稀疏关键帧合成 VMD 需要的 (frame, pos, rot, interp)。"""
    rot_keys = rot_keys or []
    pos_keys = pos_keys or []
    interp = interp or {}
    if not rot_keys and not pos_keys:
        return []

    if not rot_keys:
        return [
            (int(k[0]), (k[1], k[2], k[3]), (0.0, 0.0, 0.0, 1.0), interp.get(int(k[0])))
            for k in pos_keys
        ]
    if not pos_keys:
        return [
            (int(k[0]), (0.0, 0.0, 0.0), (k[1], k[2], k[3], k[4]), interp.get(int(k[0])))
            for k in rot_keys
        ]

    # 两套帧号完全一致时不重采样，保证字节/数值都不变。
    if [int(k[0]) for k in rot_keys] == [int(k[0]) for k in pos_keys]:
        return [
            (int(r[0]), (p[1], p[2], p[3]), (r[1], r[2], r[3], r[4]), interp.get(int(r[0])))
            for r, p in zip(rot_keys, pos_keys)
        ]

    frames = sorted({int(k[0]) for k in rot_keys} | {int(k[0]) for k in pos_keys})
    out = []
    for f in frames:
        pos = sample_keys(pos_keys, f, quat=False)
        rot = sample_keys(rot_keys, f, quat=True)
        out.append((f, pos, rot, interp.get(f)))
    return out


def _add(
    table: dict[
        tuple[str, int],
        tuple[
            tuple[float, float, float],
            tuple[float, float, float, float],
            bytes | None,
        ],
    ],
    bone: str,
    entries,
) -> None:
    for frame, pos, rot, itp in entries:
        table[(bone, frame)] = (pos, rot, itp)


def canonical_to_vmd(
    motion: dict,
    profile: dict,
    *,
    include_extra: bool = True,
    morph_map: dict[str, str] | None = None,
) -> Vmd:
    """按目标 profile 生成 :class:`Vmd`。"""
    mapping: dict[str, str] = profile.get("map", {})
    rest: dict[str, dict] = profile.get("rest", {})
    table: dict[
        tuple[str, int],
        tuple[
            tuple[float, float, float],
            tuple[float, float, float, float],
            bytes | None,
        ],
    ] = {}
    dropped: list[str] = []

    # 源 VMD 的 64 字节插值：按骨名 + 帧号索引，写回时原样使用。
    raw_interp = motion.get("interpolation", {})
    interp_map: dict[str, dict[int, bytes]] = {}
    for bone, keys in raw_interp.items():
        interp_map[bone] = {int(k[0]): bytes.fromhex(k[1]) for k in keys}

    # 语义骨
    for sem, keys in motion.get("joints", {}).items():
        bone = mapping.get(sem)
        if not bone:
            continue
        _add(
            table, bone,
            _merge_channels(keys, motion.get("translations", {}).get(sem),
                            interp_map.get(bone)),
        )

    # 根骨（pos/rot 分开存）
    root_bone = mapping.get("root")
    if root_bone:
        root = motion.get("root", {})
        _add(
            table,
            root_bone,
            _merge_channels(root.get("rot", []), root.get("pos", []),
                            interp_map.get(root_bone)),
        )

    # 无语义的骨：同模型透传，换模型丢弃
    if include_extra:
        for bone, keys in motion.get("extra", {}).items():
            if bone not in rest:
                dropped.append(bone)
                continue
            _add(
                table, bone,
                _merge_channels(keys, motion.get("extra_translations", {}).get(bone),
                                interp_map.get(bone)),
            )
    else:
        dropped.extend(motion.get("extra", {}))

    bone_frames = [
        BoneFrame(
            bone=bone,
            frame=frame,
            position=pos,
            rotation=rot,
            interpolation=itp or _LINEAR64,
        )
        for (bone, frame), (pos, rot, itp) in sorted(table.items())
    ]

    # morph
    target_morphs = set(profile.get("morphs", []))
    morph_frames: list[MorphFrame] = []
    morph_lookup = morph_map or {}
    for name, keys in motion.get("morphs", {}).items():
        target_name = morph_lookup.get(name, name)
        if target_morphs and target_name not in target_morphs:
            continue
        for k in keys:
            morph_frames.append(MorphFrame(target_name, int(k[0]), float(k[1])))
    morph_frames.sort(key=lambda m: (m.morph, m.frame))

    vmd = Vmd(
        model_name=profile.get("model", ""),
        bone_frames=bone_frames,
        morph_frames=morph_frames,
    )
    # 记录丢弃的骨，方便 CLI 报告（不参与序列化）
    vmd.dropped_bones = sorted(set(dropped))  # type: ignore[attr-defined]
    return vmd
