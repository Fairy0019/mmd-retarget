# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""PMX 读取器测试。

fixture 由本文件独立拼字节，不复用被测代码的写出逻辑。
"""
from __future__ import annotations

import struct

import pytest

from mmd_retarget.pmx import PmxError, parse_pmx

ENC = "utf-16-le"
V_IDX = 2  # 顶点索引 2 字节
T_IDX = 1  # 贴图索引 1 字节
M_IDX = 1  # 材质索引 1 字节
B_IDX = 2  # 骨骼索引 2 字节
MO_IDX = 1  # morph 索引 1 字节
RB_IDX = 1  # 刚体索引 1 字节


def text(s: str, encoding: int = 0) -> bytes:
    codec = "utf-16-le" if encoding == 0 else "utf-8"
    raw = s.encode(codec)
    return struct.pack("<i", len(raw)) + raw


def idx(value: int, size: int = 2) -> bytes:
    if size == 1:
        return struct.pack("<b", value)
    if size == 2:
        return struct.pack("<h", value)
    return struct.pack("<i", value)


def header(
    *,
    version: float = 2.0,
    encoding: int = 0,
    extra_uv: int = 0,
    v_idx: int = V_IDX,
    t_idx: int = T_IDX,
    m_idx: int = M_IDX,
    b_idx: int = B_IDX,
    mo_idx: int = MO_IDX,
    rb_idx: int = RB_IDX,
) -> bytes:
    out = b"PMX " + struct.pack("<f", version)
    out += bytes([8, encoding, extra_uv, v_idx, t_idx, m_idx, b_idx, mo_idx, rb_idx])
    return out


def vertex(
    pos: tuple[float, float, float],
    weights: list[tuple[int, float]],
    *,
    extra_uv: int = 0,
) -> bytes:
    out = struct.pack("<3f", *pos)
    out += struct.pack("<3f", 0.0, 1.0, 0.0)  # normal
    out += struct.pack("<2f", 0.0, 0.0)  # uv
    out += b"\x00" * (16 * extra_uv)
    if len(weights) == 1:
        out += bytes([0]) + idx(weights[0][0])
    elif len(weights) == 2:
        out += bytes([1]) + idx(weights[0][0]) + idx(weights[1][0])
        out += struct.pack("<f", weights[0][1])
    else:
        out += bytes([2])
        for b, _ in weights:
            out += idx(b)
        for _, w in weights:
            out += struct.pack("<f", w)
    out += struct.pack("<f", 1.0)  # edge scale
    return out


def material(name: str, *, toon_flag: int = 0, texture: int = -1, encoding: int = 0) -> bytes:
    out = text(name, encoding) + text("", encoding)
    out += struct.pack("<4f", 1, 1, 1, 1)
    out += struct.pack("<3f", 0, 0, 0)
    out += struct.pack("<f", 1.0)
    out += struct.pack("<3f", 0, 0, 0)
    out += bytes([0])  # flags
    out += struct.pack("<4f", 0, 0, 0, 1)
    out += struct.pack("<f", 0.5)
    out += idx(texture, T_IDX)
    out += idx(-1, T_IDX)
    out += bytes([0])  # sphere mode
    out += bytes([toon_flag])
    out += idx(0, T_IDX) if toon_flag else bytes([0])
    out += text("", encoding)
    out += struct.pack("<i", 0)
    return out


def bone(
    name: str,
    head: tuple[float, float, float],
    parent: int,
    flags: int,
    *,
    tail: tuple[float, float, float] | int = (0.0, 1.0, 0.0),
    inherit: tuple[int, float] | None = None,
    fixed: tuple[float, float, float] | None = None,
    local: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None,
    external: int | None = None,
    ik: tuple[int, int, float, list[tuple[int, bool, tuple[float, ...], tuple[float, ...]]]] | None = None,
    encoding: int = 0,
) -> bytes:
    out = text(name, encoding) + text("", encoding)
    out += struct.pack("<3f", *head)
    out += idx(parent, B_IDX)
    out += struct.pack("<i", 0)  # layer
    out += struct.pack("<H", flags)
    if flags & 0x0001:
        out += idx(tail if isinstance(tail, int) else -1, B_IDX)
    else:
        out += struct.pack("<3f", *(tail if isinstance(tail, tuple) else (0, 0, 0)))
    if flags & (0x0100 | 0x0200):
        assert inherit is not None
        out += idx(inherit[0], B_IDX) + struct.pack("<f", inherit[1])
    if flags & 0x0400:
        out += struct.pack("<3f", *(fixed or (0, 0, 1)))
    if flags & 0x0800:
        assert local is not None
        out += struct.pack("<3f", *local[0]) + struct.pack("<3f", *local[1])
    if flags & 0x2000:
        out += struct.pack("<i", external if external is not None else 0)
    if flags & 0x0020:
        assert ik is not None
        target, loop, limit, links = ik
        out += idx(target, B_IDX) + struct.pack("<if", loop, limit) + struct.pack("<i", len(links))
        for link_bone, has_limit, lo, hi in links:
            out += idx(link_bone, B_IDX) + bytes([int(has_limit)])
            if has_limit:
                out += struct.pack("<3f", *lo) + struct.pack("<3f", *hi)
    return out


def morph(name: str, kind: int, offsets: list[bytes], encoding: int = 0) -> bytes:
    out = text(name, encoding) + text("", encoding)
    out += bytes([0, kind])
    out += struct.pack("<i", len(offsets))
    return out + b"".join(offsets)


def make_model(
    *,
    encoding: int = 0,
    extra_uv: int = 0,
    bones: list[bytes],
    vertices: list[bytes],
    materials: list[bytes],
    morphs: list[bytes],
    faces: int = 3,
) -> bytes:
    out = header(encoding=encoding, extra_uv=extra_uv)
    out += text("テスト", encoding) + text("Test", encoding)
    out += text("comment", encoding) + text("", encoding)
    out += struct.pack("<i", len(vertices)) + b"".join(vertices)
    out += struct.pack("<i", faces) + b"\x00\x00" * faces
    out += struct.pack("<i", 1) + text("tex.png", encoding)
    out += struct.pack("<i", len(materials)) + b"".join(materials)
    out += struct.pack("<i", len(bones)) + b"".join(bones)
    out += struct.pack("<i", len(morphs)) + b"".join(morphs)
    return out


def base_bones(encoding: int = 0) -> list[bytes]:
    return [
        bone("センター", (0.0, 10.0, 0.0), -1, 0x001E, tail=(0.0, 1.0, 0.0), encoding=encoding),
        bone("左足", (1.0, 5.0, 0.0), 0, 0x001E, tail=(0.0, 4.0, 0.0), encoding=encoding),
        bone(
            "左ひざ",
            (1.0, 1.0, 0.0),
            1,
            0x001E | 0x0100 | 0x0400 | 0x0800,
            inherit=(1, 0.5),
            fixed=(0.0, 0.0, 1.0),
            local=((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            external=7,
            encoding=encoding,
        ),
        bone(
            "左足ＩＫ",
            (1.0, 1.0, 0.0),
            0,
            0x0020 | 0x0001,
            tail=-1,
            ik=(2, 40, 0.03, [(2, True, (-3.14, 0.0, 0.0), (-0.01, 0.0, 0.0))]),
            encoding=encoding,
        ),
    ]


def base_vertices() -> list[bytes]:
    return [
        vertex((0.0, 10.0, 0.0), [(0, 1.0)]),
        vertex((1.0, 5.0, 0.0), [(1, 0.75), (0, 0.25)]),
        vertex((1.0, 1.0, 0.0), [(2, 0.6), (1, 0.4)]),
    ]


def test_minimal_model():
    data = make_model(
        bones=base_bones(),
        vertices=base_vertices(),
        materials=[material("肌")],
        morphs=[],
    )
    m = parse_pmx(data)
    assert m.name == "テスト"
    assert m.version == 2.0
    assert m.vertex_count == 3
    assert m.triangle_count == 1
    assert [b.name for b in m.bones] == ["センター", "左足", "左ひざ", "左足ＩＫ"]
    assert len(m.materials) == 1 and m.materials[0].name == "肌"
    assert m.texture_count == 1


def test_bone_fields_and_tail_resolution():
    m = parse_pmx(
        make_model(bones=base_bones(), vertices=base_vertices(), materials=[], morphs=[])
    )
    center, leg, knee, ik = m.bones
    assert center.head == pytest.approx((0.0, 10.0, 0.0))
    assert center.tail == pytest.approx((0.0, 11.0, 0.0))
    assert leg.parent == 0
    # 骨索引 tail：左足ＩＫ 的 tail = -1 → 退化为 head
    assert ik.tail == pytest.approx(ik.head)
    # 付与 + 轴固定 + 局部轴
    assert knee.inherit_parent == 1
    assert knee.inherit_ratio == pytest.approx(0.5)
    assert knee.fixed_axis == pytest.approx((0.0, 0.0, 1.0))
    assert knee.local_axis_x == pytest.approx((1.0, 0.0, 0.0))
    assert knee.local_axis_z == pytest.approx((0.0, 0.0, 1.0))
    # IK
    assert ik.ik_target == 2
    assert ik.ik_loop == 40
    assert ik.ik_limit_angle == pytest.approx(0.03)
    assert ik.ik_links[0][0] == 2
    assert ik.ik_links[0][1] is True
    assert ik.ik_links[0][2] == pytest.approx((-3.14, 0.0, 0.0))


def test_vertex_weights_and_bbox():
    m = parse_pmx(
        make_model(bones=base_bones(), vertices=base_vertices(), materials=[], morphs=[])
    )
    # 权重 >= 0.5 才计入
    assert m.bone_vertex_count[0] == 1  # 顶点 0 只有骨骼 0
    assert m.bone_vertex_count[1] == 1  # 顶点 1 的 0.75
    assert m.bone_vertex_count[2] == 1  # 顶点 2 的 0.5
    lo, hi = m.bone_vertex_bbox[1]
    assert lo == pytest.approx((1.0, 5.0, 0.0))
    assert hi == pytest.approx((1.0, 5.0, 0.0))


def test_utf8_encoding():
    data = make_model(
        encoding=1,
        bones=base_bones(encoding=1),
        vertices=base_vertices(),
        materials=[material("肌", encoding=1)],
        morphs=[],
    )
    m = parse_pmx(data)
    assert m.encoding == "utf-8"
    assert m.name == "テスト"
    assert m.materials[0].name == "肌"


def test_extra_uv_is_skipped():
    data = make_model(
        extra_uv=2,
        bones=base_bones(),
        vertices=[vertex((0, 0, 0), [(0, 1.0)], extra_uv=2)],
        materials=[],
        morphs=[],
    )
    assert parse_pmx(data).vertex_count == 1


def test_all_morph_offset_types_are_skipped():
    """每种 morph offset 的字节数都必须正确，否则后续名字会解析错。"""
    offsets = {
        0: idx(1, MO_IDX) + struct.pack("<f", 0.5),
        1: idx(0) + struct.pack("<3f", 0, 0, 0),
        2: idx(1, B_IDX) + struct.pack("<3f", 0, 0, 0) + struct.pack("<4f", 0, 0, 0, 1),
        3: idx(0) + struct.pack("<4f", 0, 0, 0, 0),
        4: idx(0) + struct.pack("<4f", 0, 0, 0, 0),
        5: idx(0) + struct.pack("<4f", 0, 0, 0, 0),
        6: idx(0) + struct.pack("<4f", 0, 0, 0, 0),
        7: idx(0) + struct.pack("<4f", 0, 0, 0, 0),
        8: idx(0, M_IDX) + bytes([0]) + b"\x00" * 112,
        9: idx(0, MO_IDX) + struct.pack("<f", 1.0),
        10: idx(0, RB_IDX) + bytes([0]) + b"\x00" * 24,
    }
    kinds = sorted(offsets)
    morphs = [morph(f"m{k}", k, [offsets[k]]) for k in kinds]
    m = parse_pmx(
        make_model(bones=base_bones(), vertices=base_vertices(), materials=[], morphs=morphs)
    )
    assert [x.name for x in m.morphs] == [f"m{k}" for k in kinds]
    assert [x.kind for x in m.morphs] == kinds


def test_material_toon_flag_and_face_count():
    m = parse_pmx(
        make_model(
            bones=base_bones(),
            vertices=base_vertices(),
            materials=[material("a", toon_flag=0), material("b", toon_flag=1)],
            morphs=[],
        )
    )
    assert [x.name for x in m.materials] == ["a", "b"]


def test_bad_magic():
    with pytest.raises(PmxError, match="bad PMX magic"):
        parse_pmx(b"NOPE" + b"\x00" * 100)


def test_truncated_raises_with_offset():
    data = make_model(
        bones=base_bones(), vertices=base_vertices(), materials=[], morphs=[]
    )
    with pytest.raises(PmxError) as ei:
        parse_pmx(data[:-20])
    assert ei.value.offset is not None
