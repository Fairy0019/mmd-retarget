# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""VMD (Vocaloid Motion Data) 读写。

只依赖标准库。设计目标是**读进来是什么，写回去还是什么**：

- 骨骼帧 / morph 帧按原始顺序保存；
- 相机 / 灯光 / 自阴影 / IK 轨以定长记录原样保存（M0 不解码）；
- 无法识别的尾部字节保存在 :attr:`Vmd.trailer`，写回时原样追加。

已知格式要点
------------
- 文件头 30 字节，其中前 25 字节是 ``Vocaloid Motion Data 0002``；
- 模型名 20 字节，Shift-JIS（CP932），NUL 填充；
- 骨名 15 字节，Shift-JIS，NUL 填充；超过 15 字节的字符会被安全截断；
- 骨骼帧记录 111 字节：15s + I + 3f + 4f + 64s；
- morph 帧记录 23 字节：15s + I + f；
- 帧率固定 30fps（文件里没有帧率字段）。

插值曲线
--------
64 字节中**只有前 16 字节是权威数据**，布局为 4 通道 × 4 个控制点::

    [x1_X, x1_Y, x1_Z, x1_R,
     y1_X, y1_Y, y1_Z, y1_R,
     x2_X, x2_Y, x2_Z, x2_R,
     y2_X, y2_Y, y2_Z, y2_R]

后 48 字节是历史遗留的对角线冗余，MMD 不读取。为最大兼容性，本模块在
**新建**曲线时按 ``S[i:] + 0`` 的对角线方式填充；读入的原始 64 字节始终
原样保留，因此 round-trip 不会丢字节。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Vmd",
    "BoneFrame",
    "MorphFrame",
    "VmdError",
    "LINEAR_CURVE",
    "LINEAR_INTERPOLATION",
    "parse_vmd",
    "read_vmd",
    "build_vmd",
    "write_vmd",
    "decode_interpolation",
    "encode_interpolation",
    "sample_curve",
]

HEADER = b"Vocaloid Motion Data 0002"
HEADER_SIZE = 30
MODEL_NAME_SIZE = 20
BONE_NAME_SIZE = 15
FPS = 30

_BONE = struct.Struct("<15sI3f4f64s")
_MORPH = struct.Struct("<15sIf")
_U32 = struct.Struct("<I")
_CAMERA_SIZE = 61
_LIGHT_SIZE = 28
_SHADOW_SIZE = 9
_IK_HEAD = struct.Struct("<IBI")
_IK_LINK_SIZE = 21

#: 控制点 ``(x1, y1, x2, y2)``，取值 0–127，线性插值。
Curve = tuple[int, int, int, int]
Interpolation = tuple[Curve, Curve, Curve, Curve]

LINEAR_CURVE: Curve = (20, 20, 107, 107)
LINEAR_INTERPOLATION: Interpolation = (LINEAR_CURVE,) * 4

_CHANNELS = ("X", "Y", "Z", "Rotation")


class VmdError(ValueError):
    """VMD 文件格式错误。``offset`` 指出出错位置，便于定位损坏文件。"""

    def __init__(self, message: str, offset: int | None = None) -> None:
        self.offset = offset
        if offset is not None:
            message = f"{message} (offset={offset})"
        super().__init__(message)


def _decode_name(raw: bytes) -> str:
    """CP932 解码，截断到第一个 NUL 或尾部 0xFD 填充。

    遇到非法字节用 ``errors="replace"``，保证解析不会因为个别脏字节中断；
    原始字节仍保存在 ``*_raw`` 字段里，写回时优先使用。
    """
    raw = raw.split(b"\x00", 1)[0].rstrip(b"\xfd")
    return raw.decode("cp932", errors="replace")


def _encode_name(text: str, width: int) -> bytes:
    """CP932 编码并按 **字符边界** 截断到 ``width`` 字节。

    直接 ``text.encode()[:15]`` 可能把双字节字符切成两半，产生非法序列；
    这里逐字符累加，超长就停止。
    """
    out = bytearray()
    for ch in text:
        try:
            b = ch.encode("cp932")
        except UnicodeEncodeError:
            b = b"?"
        if len(out) + len(b) > width:
            break
        out += b
    return bytes(out).ljust(width, b"\x00")


@dataclass(slots=True, frozen=True)
class BoneFrame:
    """一根骨骼在某帧的关键帧。旋转为 ``(x, y, z, w)``。"""

    bone: str
    frame: int
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    interpolation: bytes = field(default=b"", repr=False)

    def __post_init__(self) -> None:
        if len(self.interpolation) == 0:
            object.__setattr__(self, "interpolation", encode_interpolation(LINEAR_INTERPOLATION))
        elif len(self.interpolation) != 64:
            raise VmdError(f"interpolation must be 64 bytes, got {len(self.interpolation)}")


@dataclass(slots=True, frozen=True)
class MorphFrame:
    """表情 morph 的一个关键帧。"""

    morph: str
    frame: int
    weight: float


@dataclass(slots=True)
class Vmd:
    """一个 VMD 文件的内存表示。

    ``camera`` / ``light`` / ``shadow`` / ``ik`` 保存原始记录，每条记录不含
    数量字段。这样即使将来出现新字段，读写也不会破坏文件。
    """

    model_name: str = ""
    bone_frames: list[BoneFrame] = field(default_factory=list)
    morph_frames: list[MorphFrame] = field(default_factory=list)
    camera: list[bytes] = field(default_factory=list)
    light: list[bytes] = field(default_factory=list)
    shadow: list[bytes] = field(default_factory=list)
    ik: list[bytes] = field(default_factory=list)
    trailer: bytes = b""
    header_raw: bytes = b""
    model_name_raw: bytes = b""
    #: 解码名 → 原始 15 字节骨名/morph 名。用于保留第三方文件里的 0xFD 填充。
    bone_names_raw: dict[str, bytes] = field(default_factory=dict)
    morph_names_raw: dict[str, bytes] = field(default_factory=dict)
    #: 相机及之后的 section 是否解析成功。False 表示 ``trailer`` 从
    #: “camera count” 开始，写回时不能再追加四个数量字段。
    sections_parsed: bool = True

    # ---- 便捷视图 -------------------------------------------------
    @property
    def bones(self) -> list[str]:
        """按首次出现顺序返回骨骼名（去重）。"""
        seen: dict[str, None] = {}
        for f in self.bone_frames:
            seen.setdefault(f.bone, None)
        return list(seen)

    @property
    def morphs(self) -> list[str]:
        seen: dict[str, None] = {}
        for f in self.morph_frames:
            seen.setdefault(f.morph, None)
        return list(seen)

    @property
    def frame_range(self) -> tuple[int, int]:
        frames = [f.frame for f in self.bone_frames]
        frames += [f.frame for f in self.morph_frames]
        return (min(frames), max(frames)) if frames else (0, 0)

    def bones_by_name(self) -> dict[str, list[BoneFrame]]:
        out: dict[str, list[BoneFrame]] = {}
        for f in self.bone_frames:
            out.setdefault(f.bone, []).append(f)
        return out

    def morphs_by_name(self) -> dict[str, list[MorphFrame]]:
        out: dict[str, list[MorphFrame]] = {}
        for f in self.morph_frames:
            out.setdefault(f.morph, []).append(f)
        return out

    def summary(self) -> dict[str, object]:
        lo, hi = self.frame_range
        return {
            "model": self.model_name,
            "bones": len(self.bones),
            "bone_frames": len(self.bone_frames),
            "morphs": len(self.morphs),
            "morph_frames": len(self.morph_frames),
            "camera_frames": len(self.camera),
            "light_frames": len(self.light),
            "shadow_frames": len(self.shadow),
            "ik_frames": len(self.ik),
            "frame_start": lo,
            "frame_end": hi,
            "duration_sec": round((hi - lo) / FPS, 3) if self.bone_frames else 0.0,
            "trailer_bytes": len(self.trailer),
        }


# ---------------------------------------------------------------------------
# 插值
# ---------------------------------------------------------------------------


def decode_interpolation(raw: bytes) -> Interpolation:
    """把 64 字节插值块解成 4 条曲线。"""
    if len(raw) != 64:
        raise VmdError(f"interpolation must be 64 bytes, got {len(raw)}")
    # 前 16 字节按通道转置存放；后 48 字节是冗余，不参与解码。
    return tuple(  # type: ignore[return-value]
        (raw[c], raw[4 + c], raw[8 + c], raw[12 + c]) for c in range(4)
    )


def encode_interpolation(curves: Interpolation) -> bytes:
    """把 4 条曲线编码成 64 字节。

    前 16 字节是权威数据；其余按对角线冗余填充（MMD 不读取）。
    """
    flat = bytes(
        [curve[0] for curve in curves]
        + [curve[1] for curve in curves]
        + [curve[2] for curve in curves]
        + [curve[3] for curve in curves]
    )  # 16 bytes，列优先
    if len(flat) != 16:
        raise VmdError("interpolation needs 4 curves of 4 values")
    out = bytearray(flat)
    for shift in (1, 2, 3):
        out += flat[shift:] + bytes(shift)
    return bytes(out)


def sample_curve(curve: Curve, t: float) -> float:
    """在 ``t ∈ [0, 1]`` 处采样一条三次贝塞尔曲线。

    ``curve = (x1, y1, x2, y2)``，控制点为 ``(0,0) (x1,y1) (x2,y2) (1,1)``。
    先用二分法由 x 求参数 u，再算 y。曲线退化时回退到线性。
    """
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    x1, y1, x2, y2 = (v / 127.0 for v in curve)

    def bezier(u: float, p1: float, p2: float) -> float:
        v = 1.0 - u
        return 3.0 * v * v * u * p1 + 3.0 * v * u * u * p2 + u * u * u

    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) * 0.5
        if bezier(mid, x1, x2) < t:
            lo = mid
        else:
            hi = mid
    return bezier((lo + hi) * 0.5, y1, y2)


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------


def _need(data: bytes, off: int, n: int, what: str) -> None:
    if off + n > len(data):
        raise VmdError(
            f"truncated while reading {what}: need {n} bytes at {off}, "
            f"file has {len(data)}",
            off,
        )


def parse_vmd(data: bytes, *, strict: bool = True) -> Vmd:
    """解析 VMD 字节流。

    ``strict=False`` 时，遇到无法解释的尾部数据不会报错，而是放进
    ``Vmd.trailer``。真实文件里存在「count 写 0 却仍跟一帧相机数据」的
    情况，默认模式对这类文件会抛 :class:`VmdError`，需要显式放宽。
    """
    if len(data) < HEADER_SIZE + MODEL_NAME_SIZE + 4:
        raise VmdError("file too small to be a VMD", 0)

    header_raw = data[:HEADER_SIZE]
    if not header_raw.startswith(HEADER[:25]):
        raise VmdError(
            f"bad VMD header: {header_raw[:25]!r}", 0
        )

    off = HEADER_SIZE
    model_name_raw = data[off : off + MODEL_NAME_SIZE]
    model_name = _decode_name(model_name_raw)
    off += MODEL_NAME_SIZE

    (n_bone,) = _U32.unpack_from(data, off)
    off += 4

    bone_frames: list[BoneFrame] = []
    append_bone = bone_frames.append
    bone_names_raw: dict[str, bytes] = {}
    _need(data, off, n_bone * _BONE.size, "bone frames")
    name_cache: dict[bytes, str] = {}
    for _ in range(n_bone):
        raw_name, frame, px, py, pz, qx, qy, qz, qw, interp = _BONE.unpack_from(data, off)
        off += _BONE.size
        name = name_cache.get(raw_name)
        if name is None:
            name = _decode_name(raw_name)
            name_cache[raw_name] = name
            bone_names_raw.setdefault(name, raw_name)
        append_bone(
            BoneFrame(
                bone=name,
                frame=frame,
                position=(px, py, pz),
                rotation=(qx, qy, qz, qw),
                interpolation=interp,
            )
        )

    _need(data, off, 4, "morph count")
    (n_morph,) = _U32.unpack_from(data, off)
    off += 4

    morph_frames: list[MorphFrame] = []
    append_morph = morph_frames.append
    morph_names_raw: dict[str, bytes] = {}
    _need(data, off, n_morph * _MORPH.size, "morph frames")
    morph_cache: dict[bytes, str] = {}
    for _ in range(n_morph):
        raw_name, frame, weight = _MORPH.unpack_from(data, off)
        off += _MORPH.size
        name = morph_cache.get(raw_name)
        if name is None:
            name = _decode_name(raw_name)
            morph_cache[raw_name] = name
            morph_names_raw.setdefault(name, raw_name)
        append_morph(MorphFrame(name, frame, weight))

    vmd = Vmd(
        model_name=model_name,
        bone_frames=bone_frames,
        morph_frames=morph_frames,
        header_raw=header_raw,
        model_name_raw=model_name_raw,
        bone_names_raw=bone_names_raw,
        morph_names_raw=morph_names_raw,
    )

    # 后续 section 都是「count + 定长记录」，任何一步对不上就把剩余字节
    # 当作 trailer 保留，而不是丢数据。
    try:
        off = _read_sections(data, off, vmd)
    except VmdError:
        if strict:
            raise
        vmd.trailer = data[off:]
        vmd.sections_parsed = False
        return vmd

    if off != len(data):
        vmd.trailer = data[off:]
        if strict and vmd.trailer:
            # 允许有尾部数据（部分工具会追加私有块），只记录不报错。
            pass
    return vmd


def _read_sections(data: bytes, off: int, vmd: Vmd) -> int:
    _need(data, off, 4, "camera count")
    (n_cam,) = _U32.unpack_from(data, off)
    off += 4
    _need(data, off, n_cam * _CAMERA_SIZE, "camera frames")
    vmd.camera = [data[off + i * _CAMERA_SIZE : off + (i + 1) * _CAMERA_SIZE] for i in range(n_cam)]
    off += n_cam * _CAMERA_SIZE

    _need(data, off, 4, "light count")
    (n_light,) = _U32.unpack_from(data, off)
    off += 4
    _need(data, off, n_light * _LIGHT_SIZE, "light frames")
    vmd.light = [data[off + i * _LIGHT_SIZE : off + (i + 1) * _LIGHT_SIZE] for i in range(n_light)]
    off += n_light * _LIGHT_SIZE

    _need(data, off, 4, "shadow count")
    (n_shadow,) = _U32.unpack_from(data, off)
    off += 4
    _need(data, off, n_shadow * _SHADOW_SIZE, "shadow frames")
    vmd.shadow = [
        data[off + i * _SHADOW_SIZE : off + (i + 1) * _SHADOW_SIZE] for i in range(n_shadow)
    ]
    off += n_shadow * _SHADOW_SIZE

    _need(data, off, 4, "ik count")
    (n_ik,) = _U32.unpack_from(data, off)
    off += 4
    ik: list[bytes] = []
    for _ in range(n_ik):
        _need(data, off, _IK_HEAD.size, "ik frame")
        start = off
        _frame, _show, n_link = _IK_HEAD.unpack_from(data, off)
        off += _IK_HEAD.size
        _need(data, off, n_link * _IK_LINK_SIZE, "ik links")
        off += n_link * _IK_LINK_SIZE
        ik.append(data[start:off])
    vmd.ik = ik
    return off


def read_vmd(path: str | Path, *, strict: bool = True) -> Vmd:
    """从磁盘读取 VMD。"""
    return parse_vmd(Path(path).read_bytes(), strict=strict)


# ---------------------------------------------------------------------------
# 写出
# ---------------------------------------------------------------------------


def build_vmd(motion: Vmd) -> bytes:
    """把 :class:`Vmd` 序列化成字节流。

    未修改的 header / 模型名会优先写回原始字节，保证脏文件也能无损往返。
    """
    default_header = HEADER.ljust(HEADER_SIZE, b"\x00")
    header = motion.header_raw if motion.header_raw else default_header
    if len(header) != HEADER_SIZE:
        header = header[:HEADER_SIZE].ljust(HEADER_SIZE, b"\x00")

    if motion.model_name_raw and _decode_name(motion.model_name_raw) == motion.model_name:
        name = motion.model_name_raw
    else:
        name = _encode_name(motion.model_name, MODEL_NAME_SIZE)

    parts: list[bytes] = [header, name, _U32.pack(len(motion.bone_frames))]

    pack_bone = _BONE.pack
    for f in motion.bone_frames:
        raw = motion.bone_names_raw.get(f.bone)
        name = raw if raw and _decode_name(raw) == f.bone else _encode_name(f.bone, BONE_NAME_SIZE)
        parts.append(
            pack_bone(
                name,
                f.frame,
                *f.position,
                *f.rotation,
                f.interpolation,
            )
        )

    parts.append(_U32.pack(len(motion.morph_frames)))
    pack_morph = _MORPH.pack
    for m in motion.morph_frames:
        raw = motion.morph_names_raw.get(m.morph)
        name = raw if raw and _decode_name(raw) == m.morph else _encode_name(m.morph, BONE_NAME_SIZE)
        parts.append(pack_morph(name, m.frame, m.weight))

    if motion.sections_parsed:
        for records, size in (
            (motion.camera, _CAMERA_SIZE),
            (motion.light, _LIGHT_SIZE),
            (motion.shadow, _SHADOW_SIZE),
        ):
            parts.append(_U32.pack(len(records)))
            for r in records:
                if len(r) != size:
                    raise VmdError(f"expected {size}-byte record, got {len(r)}")
                parts.append(r)

        parts.append(_U32.pack(len(motion.ik)))
        for r in motion.ik:
            parts.append(r)

    parts.append(motion.trailer)
    return b"".join(parts)


def write_vmd(motion: Vmd, path: str | Path) -> None:
    """写入 VMD 文件（原子替换，避免写一半留下坏文件）。"""
    path = Path(path)
    data = build_vmd(motion)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
