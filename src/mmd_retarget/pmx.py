# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""PMX (MikuMikuDance model) 读取器 —— M0 最小集。

只解析重定向需要的东西：

- 骨骼：名称、父级、rest 位置、tail、layer、flags、IK 限位；
- 顶点：位置 + 蒙皮权重（用于估计碰撞体半径）；
- 材质与 morph：名称与数量（用于报告与后续表情映射）；
- 网格面数：只统计，不保留索引。

不做：贴图解码、材质渲染参数、刚体、关节、显示枠。这些在 M1 之后按需再加。

格式参考 PMX 2.0 / 2.1。所有 ``count`` 字段在读取前都会做边界检查，
避免恶意文件用超大 count 触发 OOM。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field, replace
from pathlib import Path

__all__ = [
    "Pmx",
    "PmxBone",
    "PmxMaterial",
    "PmxMorph",
    "PmxError",
    "parse_pmx",
    "read_pmx",
]

_MAGIC = b"PMX "
_U32 = struct.Struct("<I")
_I32 = struct.Struct("<i")
_F32 = struct.Struct("<f")
_U16 = struct.Struct("<H")
_VEC2 = struct.Struct("<2f")
_VEC3 = struct.Struct("<3f")
_VEC4 = struct.Struct("<4f")


class PmxError(ValueError):
    """PMX 格式错误。``offset`` 指向出错位置。"""

    def __init__(self, message: str, offset: int | None = None) -> None:
        self.offset = offset
        if offset is not None:
            message = f"{message} (offset={offset})"
        super().__init__(message)


class _Reader:
    """带边界检查的小端读取器。"""

    __slots__ = ("data", "off")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.off = 0

    def need(self, n: int, what: str) -> None:
        if n < 0 or self.off + n > len(self.data):
            raise PmxError(f"truncated while reading {what}", self.off)

    def unpack(self, st: struct.Struct, what: str):
        self.need(st.size, what)
        values = st.unpack_from(self.data, self.off)
        self.off += st.size
        return values[0] if len(values) == 1 else values

    def u8(self, what: str = "u8") -> int:
        self.need(1, what)
        v = self.data[self.off]
        self.off += 1
        return v

    def i32(self, what: str = "i32") -> int:
        return self.unpack(_I32, what)


    def f32(self, what: str = "f32") -> float:
        return self.unpack(_F32, what)

    def bytes_(self, n: int, what: str) -> bytes:
        self.need(n, what)
        b = self.data[self.off : self.off + n]
        self.off += n
        return b

    def index(self, size: int, *, signed: bool, what: str = "index") -> int:
        if size == 1:
            self.need(1, what)
            v = self.data[self.off]
            self.off += 1
            return v - 256 if signed and v >= 128 else v
        if size == 2:
            self.need(2, what)
            v = struct.unpack_from("<H", self.data, self.off)[0]
            self.off += 2
            return v - 65536 if signed and v >= 32768 else v
        if size == 4:
            return self.unpack(_I32 if signed else _U32, what)
        raise PmxError(f"unsupported index size: {size}", self.off)

    def text(self, encoding: str, what: str) -> str:
        n = self.i32(f"{what} length")
        if n < 0:
            raise PmxError(f"negative {what} length: {n}", self.off)
        raw = self.bytes_(n, what)
        codec = "utf-16-le" if encoding == "utf-16-le" else "utf-8"
        return raw.decode(codec, errors="replace").rstrip("\x00")


@dataclass(slots=True, frozen=True)
class PmxBone:
    """一根 PMX 骨骼。

    ``head`` / ``tail`` 是模型空间的**绝对坐标**。PMX 的 tail 字段可能是
    “指向另一根骨”的索引，也可能是相对 head 的偏移，这里统一换算成绝对坐标。
    """

    index: int
    name: str
    name_en: str
    head: tuple[float, float, float]
    tail: tuple[float, float, float]
    parent: int
    layer: int
    flags: int
    tail_is_bone: bool = False
    inherit_parent: int | None = None
    inherit_ratio: float | None = None
    fixed_axis: tuple[float, float, float] | None = None
    local_axis_x: tuple[float, float, float] | None = None
    local_axis_z: tuple[float, float, float] | None = None
    ik_target: int | None = None
    ik_loop: int | None = None
    ik_limit_angle: float | None = None
    ik_links: tuple[tuple[int, bool, tuple[float, float, float], tuple[float, float, float]], ...] = ()
    tail_bone: int | None = None

    @property
    def length(self) -> float:
        dx = self.tail[0] - self.head[0]
        dy = self.tail[1] - self.head[1]
        dz = self.tail[2] - self.head[2]
        return (dx * dx + dy * dy + dz * dz) ** 0.5

    @property
    def is_ik(self) -> bool:
        return bool(self.flags & 0x0020)


@dataclass(slots=True, frozen=True)
class PmxMaterial:
    index: int
    name: str
    name_en: str
    face_count: int


@dataclass(slots=True, frozen=True)
class PmxMorph:
    index: int
    name: str
    name_en: str
    kind: int
    panel: int
    offset_count: int


@dataclass(slots=True)
class Pmx:
    path: str = ""
    version: float = 2.0
    encoding: str = "utf-16-le"
    name: str = ""
    name_en: str = ""
    comment: str = ""
    comment_en: str = ""
    vertex_count: int = 0
    triangle_count: int = 0
    texture_count: int = 0
    bones: list[PmxBone] = field(default_factory=list)
    materials: list[PmxMaterial] = field(default_factory=list)
    morphs: list[PmxMorph] = field(default_factory=list)
    #: 每根骨骼上「权重 ≥ 0.5」的顶点数与包围盒，用于估计碰撞体。
    bone_vertex_count: dict[int, int] = field(default_factory=dict)
    bone_vertex_bbox: dict[int, tuple[tuple[float, float, float], tuple[float, float, float]]] = field(
        default_factory=dict
    )

    @property
    def bone_names(self) -> list[str]:
        return [b.name for b in self.bones]

    def bone_by_name(self) -> dict[str, PmxBone]:
        return {b.name: b for b in self.bones}

    def summary(self) -> dict[str, object]:
        return {
            "model": self.name,
            "model_en": self.name_en,
            "version": self.version,
            "encoding": self.encoding,
            "vertices": self.vertex_count,
            "triangles": self.triangle_count,
            "bones": len(self.bones),
            "materials": len(self.materials),
            "morphs": len(self.morphs),
            "textures": self.texture_count,
            "ik_bones": sum(1 for b in self.bones if b.is_ik),
        }


def _read_header(r: _Reader) -> tuple[float, str, int, int, int, int, int, int, int]:
    magic = r.bytes_(4, "magic")
    if magic != _MAGIC:
        raise PmxError(f"bad PMX magic: {magic!r}", 0)
    version = r.f32("version")
    if not (1.9 <= version <= 2.2):
        raise PmxError(f"unsupported PMX version: {version}", 4)

    globals_count = r.u8("globals count")
    if globals_count < 8:
        raise PmxError(f"expected 8 globals, got {globals_count}", r.off - 1)
    encoding_byte = r.u8("text encoding")
    if encoding_byte not in (0, 1):
        raise PmxError(f"unknown text encoding: {encoding_byte}", r.off - 1)
    encoding = "utf-16-le" if encoding_byte == 0 else "utf-8"
    additional_uv = r.u8("additional uv")
    vertex_index_size = r.u8("vertex index size")
    texture_index_size = r.u8("texture index size")
    material_index_size = r.u8("material index size")
    bone_index_size = r.u8("bone index size")
    morph_index_size = r.u8("morph index size")
    rigidbody_index_size = r.u8("rigidbody index size")
    # 跳过未知的 extra globals（未来格式）。
    for _ in range(globals_count - 8):
        r.u8("extra global")

    for size, name in (
        (vertex_index_size, "vertex"),
        (texture_index_size, "texture"),
        (material_index_size, "material"),
        (bone_index_size, "bone"),
        (morph_index_size, "morph"),
        (rigidbody_index_size, "rigidbody"),
    ):
        if size not in (1, 2, 4):
            raise PmxError(f"invalid {name} index size: {size}", r.off)
    return (
        version,
        encoding,
        additional_uv,
        vertex_index_size,
        texture_index_size,
        material_index_size,
        bone_index_size,
        morph_index_size,
        rigidbody_index_size,
    )


def parse_pmx(data: bytes, *, path: str = "") -> Pmx:
    r = _Reader(data)
    (
        version,
        encoding,
        extra_uv,
        v_idx,
        t_idx,
        m_idx,
        b_idx,
        mo_idx,
        rb_idx,
    ) = _read_header(r)

    pmx = Pmx(path=path, version=version, encoding=encoding)
    pmx.name = r.text(encoding, "model name")
    pmx.name_en = r.text(encoding, "model name en")
    pmx.comment = r.text(encoding, "comment")
    pmx.comment_en = r.text(encoding, "comment en")

    # ---- 顶点 ----------------------------------------------------------
    n_vertex = r.i32("vertex count")
    if n_vertex < 0:
        raise PmxError("negative vertex count", r.off - 4)
    pmx.vertex_count = n_vertex
    counts: dict[int, int] = {}
    bboxes: dict[int, list[float]] = {}

    for _ in range(n_vertex):
        x, y, z = r.unpack(_VEC3, "vertex position")
        r.unpack(_VEC3, "vertex normal")
        r.unpack(_VEC2, "vertex uv")
        if extra_uv:
            r.bytes_(16 * extra_uv, "additional uv")
        weight_type = r.u8("weight type")

        if weight_type == 0:  # BDEF1
            bones = [(r.index(b_idx, signed=True, what="bdef1 bone"), 1.0)]
        elif weight_type == 1:  # BDEF2
            b0 = r.index(b_idx, signed=True, what="bdef2 bone0")
            b1 = r.index(b_idx, signed=True, what="bdef2 bone1")
            w0 = r.f32("bdef2 weight")
            bones = [(b0, w0), (b1, 1.0 - w0)]
        elif weight_type == 2:  # BDEF4
            idxs = [r.index(b_idx, signed=True, what="bdef4 bone") for _ in range(4)]
            ws = [r.f32("bdef4 weight") for _ in range(4)]
            bones = list(zip(idxs, ws))
        elif weight_type == 3:  # SDEF
            b0 = r.index(b_idx, signed=True, what="sdef bone0")
            b1 = r.index(b_idx, signed=True, what="sdef bone1")
            w0 = r.f32("sdef weight")
            r.bytes_(36, "sdef c/r0/r1")
            bones = [(b0, w0), (b1, 1.0 - w0)]
        elif weight_type == 4:  # QDEF
            idxs = [r.index(b_idx, signed=True, what="qdef bone") for _ in range(4)]
            ws = [r.f32("qdef weight") for _ in range(4)]
            bones = list(zip(idxs, ws))
        else:
            raise PmxError(f"unknown weight type: {weight_type}", r.off - 1)

        r.f32("edge scale")
        for bone_index, weight in bones:
            if bone_index < 0 or weight < 0.5:
                continue
            counts[bone_index] = counts.get(bone_index, 0) + 1
            box = bboxes.get(bone_index)
            if box is None:
                bboxes[bone_index] = [x, y, z, x, y, z]
            else:
                box[0] = min(box[0], x)
                box[1] = min(box[1], y)
                box[2] = min(box[2], z)
                box[3] = max(box[3], x)
                box[4] = max(box[4], y)
                box[5] = max(box[5], z)

    pmx.bone_vertex_count = counts
    pmx.bone_vertex_bbox = {
        k: ((v[0], v[1], v[2]), (v[3], v[4], v[5])) for k, v in bboxes.items()
    }

    # ---- 面 ------------------------------------------------------------
    n_face_index = r.i32("face index count")
    if n_face_index < 0:
        raise PmxError("negative face count", r.off - 4)
    if n_face_index % 3:
        raise PmxError(f"face index count not divisible by 3: {n_face_index}", r.off - 4)
    pmx.triangle_count = n_face_index // 3
    r.bytes_(n_face_index * v_idx, "face indices")

    # ---- 贴图 ----------------------------------------------------------
    n_texture = r.i32("texture count")
    if n_texture < 0:
        raise PmxError("negative texture count", r.off - 4)
    pmx.texture_count = n_texture
    for _ in range(n_texture):
        r.text(encoding, "texture path")

    # ---- 材质 ----------------------------------------------------------
    n_material = r.i32("material count")
    if n_material < 0:
        raise PmxError("negative material count", r.off - 4)
    for i in range(n_material):
        name = r.text(encoding, "material name")
        name_en = r.text(encoding, "material name en")
        r.bytes_(16 + 12 + 4 + 12 + 1 + 16 + 4, "material colors")
        r.index(t_idx, signed=True, what="material texture")
        r.index(t_idx, signed=True, what="material sphere")
        sphere_mode = r.u8("sphere mode")
        toon_flag = r.u8("toon flag")
        if toon_flag == 0:
            r.u8("toon index")
        else:
            r.index(t_idx, signed=True, what="toon index")
        r.text(encoding, "material memo")
        face_count = r.i32("material face count")
        _ = sphere_mode
        pmx.materials.append(PmxMaterial(i, name, name_en, face_count))

    # ---- 骨骼 ----------------------------------------------------------
    n_bone = r.i32("bone count")
    if n_bone < 0:
        raise PmxError("negative bone count", r.off - 4)
    for i in range(n_bone):
        name = r.text(encoding, "bone name")
        name_en = r.text(encoding, "bone name en")
        hx, hy, hz = r.unpack(_VEC3, "bone position")
        parent = r.index(b_idx, signed=True, what="bone parent")
        layer = r.i32("bone layer")
        flags = r.unpack(_U16, "bone flags")

        tail_is_bone = bool(flags & 0x0001)
        tail_bone: int | None = None
        if tail_is_bone:
            tail_bone = r.index(b_idx, signed=True, what="bone tail index")
            tail = (0.0, 0.0, 0.0)  # 稍后按索引解析
        else:
            tx, ty, tz = r.unpack(_VEC3, "bone tail offset")
            tail = (hx + tx, hy + ty, hz + tz)

        inherit_parent: int | None = None
        inherit_ratio: float | None = None
        # PMX: 0x0100 回転付与, 0x0200 移動付与
        if flags & (0x0100 | 0x0200):
            inherit_parent = r.index(b_idx, signed=True, what="inherit parent")
            inherit_ratio = r.f32("inherit ratio")

        fixed_axis = None
        if flags & 0x0400:  # 軸固定
            fixed_axis = r.unpack(_VEC3, "fixed axis")

        local_axis_x = local_axis_z = None
        if flags & 0x0800:  # ローカル軸
            local_axis_x = r.unpack(_VEC3, "local axis x")
            local_axis_z = r.unpack(_VEC3, "local axis z")

        if flags & 0x2000:  # 外部親
            r.i32("external parent key")

        ik_target = ik_loop = ik_limit_angle = None
        ik_links: tuple[tuple[int, bool, tuple[float, float, float], tuple[float, float, float]], ...] = ()
        if flags & 0x0020:
            ik_target = r.index(b_idx, signed=True, what="ik target")
            ik_loop = r.i32("ik loop")
            ik_limit_angle = r.f32("ik limit angle")
            n_link = r.i32("ik link count")
            if n_link < 0:
                raise PmxError("negative ik link count", r.off - 4)
            links = []
            for _ in range(n_link):
                link_bone = r.index(b_idx, signed=True, what="ik link bone")
                has_limit = r.u8("ik link limit flag")
                if has_limit:
                    lo = r.unpack(_VEC3, "ik link min")
                    hi = r.unpack(_VEC3, "ik link max")
                else:
                    lo = hi = (-3.141592653589793, -3.141592653589793, -3.141592653589793)
                links.append((link_bone, bool(has_limit), lo, hi))
            ik_links = tuple(links)

        pmx.bones.append(
            PmxBone(
                index=i,
                name=name,
                name_en=name_en,
                head=(hx, hy, hz),
                tail=tail,
                parent=parent,
                layer=layer,
                flags=flags,
                tail_is_bone=tail_is_bone,
                inherit_parent=inherit_parent,
                inherit_ratio=inherit_ratio,
                fixed_axis=fixed_axis,
                local_axis_x=local_axis_x,
                local_axis_z=local_axis_z,
                ik_target=ik_target,
                ik_loop=ik_loop,
                ik_limit_angle=ik_limit_angle,
                ik_links=ik_links,
                tail_bone=tail_bone,
            )
        )

    # tail 指向另一根骨时，用那根骨的 head 作为绝对坐标。
    resolved: list[PmxBone] = []
    for bone in pmx.bones:
        if bone.tail_bone is not None:
            if 0 <= bone.tail_bone < len(pmx.bones):
                resolved.append(replace(bone, tail=pmx.bones[bone.tail_bone].head))
            else:
                resolved.append(replace(bone, tail=bone.head))
        else:
            resolved.append(bone)
    pmx.bones = resolved

    # ---- morph ---------------------------------------------------------
    n_morph = r.i32("morph count")
    if n_morph < 0:
        raise PmxError("negative morph count", r.off - 4)
    for i in range(n_morph):
        name = r.text(encoding, "morph name")
        name_en = r.text(encoding, "morph name en")
        panel = r.u8("morph panel")
        kind = r.u8("morph type")
        n_offset = r.i32("morph offset count")
        if n_offset < 0:
            raise PmxError("negative morph offset count", r.off - 4)
        _skip_morph_offsets(r, kind, n_offset, v_idx, m_idx, mo_idx, b_idx, rb_idx)
        pmx.morphs.append(PmxMorph(i, name, name_en, kind, panel, n_offset))

    return pmx


def _skip_morph_offsets(
    r: _Reader,
    kind: int,
    count: int,
    v_idx: int,
    m_idx: int,
    morph_idx: int,
    bone_idx: int,
    rb_idx: int,
) -> None:
    """按 morph 类型跳过 offset 数据（不保留，只要游标正确）。"""
    if kind == 0:  # group
        r.bytes_(count * (morph_idx + 4), "group morph offsets")
    elif kind == 1:  # vertex
        r.bytes_(count * (v_idx + 12), "vertex morph offsets")
    elif kind == 2:  # bone
        r.bytes_(count * (bone_idx + 12 + 16), "bone morph offsets")
    elif kind in (3, 4, 5, 6, 7):  # uv
        r.bytes_(count * (v_idx + 16), "uv morph offsets")
    elif kind == 8:  # material
        r.bytes_(
            count * (m_idx + 1 + 16 + 12 + 4 + 12 + 16 + 4 + 16 + 16 + 16),
            "material morph offsets",
        )
    elif kind == 9:  # flip
        r.bytes_(count * (morph_idx + 4), "flip morph offsets")
    elif kind == 10:  # impulse
        r.bytes_(count * (rb_idx + 1 + 12 + 12), "impulse morph offsets")
    else:
        raise PmxError(f"unknown morph type: {kind}", r.off)


def read_pmx(path: str | Path) -> Pmx:
    path = Path(path)
    return parse_pmx(path.read_bytes(), path=str(path))
