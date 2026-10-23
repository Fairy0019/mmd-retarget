# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""VMD 读写的单元测试。

测试用的 VMD 由本文件里的 ``pack_*`` 函数**独立**构造（直接 struct.pack），
不复用被测模块的 writer，避免「写错也读错」的自洽测试。
"""
from __future__ import annotations

import struct

import pytest

from mmd_retarget.vmd import (
    LINEAR_CURVE,
    LINEAR_INTERPOLATION,
    BoneFrame,
    MorphFrame,
    Vmd,
    VmdError,
    build_vmd,
    decode_interpolation,
    encode_interpolation,
    parse_vmd,
    read_vmd,
    sample_curve,
    write_vmd,
)

# 默认线性插值的 64 字节（20/107 是 MMD 的 0–127 刻度）。
LINEAR64 = bytes.fromhex(
    "14141414141414146b6b6b6b6b6b6b6b"
    "141414141414146b6b6b6b6b6b6b6b01"
    "1414141414146b6b6b6b6b6b6b6b0100"
    "14141414146b6b6b6b6b6b6b6b010000"
)


def pack_name(text: str, width: int = 15) -> bytes:
    raw = text.encode("cp932")
    assert len(raw) <= width
    return raw.ljust(width, b"\x00")


def pack_bone(
    name: str,
    frame: int = 0,
    pos: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rot: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0),
    interp: bytes = LINEAR64,
) -> bytes:
    return struct.pack("<15sI3f4f64s", pack_name(name), frame, *pos, *rot, interp)


def pack_morph(name: str, frame: int, weight: float) -> bytes:
    return struct.pack("<15sIf", pack_name(name), frame, weight)


def pack_camera(frame: int = 0) -> bytes:
    return struct.pack("<I", frame) + b"\x00" * 57


def pack_light(frame: int = 0) -> bytes:
    return struct.pack("<I", frame) + b"\x00" * 24


def pack_shadow(frame: int = 0) -> bytes:
    return struct.pack("<I", frame) + b"\x00" * 5


def pack_ik(frame: int, links: list[tuple[str, bool]]) -> bytes:
    out = struct.pack("<IBI", frame, 1, len(links))
    for name, enabled in links:
        out += struct.pack("<20sB", pack_name(name, 20), int(enabled))
    return out


def make_vmd(
    *,
    model: str = "テストモデル",
    bones: list[bytes] | None = None,
    morphs: list[bytes] | None = None,
    cameras: list[bytes] | None = None,
    lights: list[bytes] | None = None,
    shadows: list[bytes] | None = None,
    iks: list[bytes] | None = None,
    trailer: bytes = b"",
) -> bytes:
    bones = bones or []
    morphs = morphs or []
    cameras = cameras or []
    lights = lights or []
    shadows = shadows or []
    iks = iks or []
    out = b"Vocaloid Motion Data 0002".ljust(30, b"\x00")
    out += pack_name(model, 20)
    out += struct.pack("<I", len(bones)) + b"".join(bones)
    out += struct.pack("<I", len(morphs)) + b"".join(morphs)
    out += struct.pack("<I", len(cameras)) + b"".join(cameras)
    out += struct.pack("<I", len(lights)) + b"".join(lights)
    out += struct.pack("<I", len(shadows)) + b"".join(shadows)
    out += struct.pack("<I", len(iks)) + b"".join(iks)
    return out + trailer


# ---------------------------------------------------------------------------


def test_empty_motion_roundtrip():
    raw = make_vmd(model="空")
    v = parse_vmd(raw)
    assert v.bone_frames == []
    assert v.morph_frames == []
    assert v.model_name == "空"
    assert build_vmd(v) == raw


def test_single_bone_frame():
    raw = make_vmd(
        bones=[pack_bone("センター", 12, (1.5, -2.0, 3.25), (0.1, 0.2, 0.3, 0.9))]
    )
    v = parse_vmd(raw)
    assert len(v.bone_frames) == 1
    f = v.bone_frames[0]
    assert (f.bone, f.frame) == ("センター", 12)
    assert f.position == pytest.approx((1.5, -2.0, 3.25))
    assert f.rotation == pytest.approx((0.1, 0.2, 0.3, 0.9))
    assert build_vmd(v) == raw


def test_japanese_bone_names_are_not_lost():
    names = ["センター", "上半身", "左腕", "右ひじ", "左足首", "右足ＩＫ"]
    raw = make_vmd(
        bones=[pack_bone(n, i) for i, n in enumerate(names)],
        morphs=[pack_morph("まばたき", 3, 1.0), pack_morph("あ", 4, 0.5)],
    )
    v = parse_vmd(raw)
    assert [f.bone for f in v.bone_frames] == names
    assert [m.morph for m in v.morph_frames] == ["まばたき", "あ"]
    assert build_vmd(v) == raw


def test_utf8_unencodable_name_falls_back_without_crash():
    # 😀 无法用 CP932 表示，写回时应变成 "?" 而不是抛异常。
    v = Vmd(model_name="ok", bone_frames=[BoneFrame("😀", 0)])
    data = build_vmd(v)
    back = parse_vmd(data)
    assert back.bone_frames[0].bone == "?"


def test_long_name_is_truncated_on_character_boundary():
    # 8 个全角字符 = 16 字节，超过 15；只能保留 7 个（14 字节）。
    name = "一二三四五六七八"
    v = Vmd(bone_frames=[BoneFrame(name, 0)])
    raw = build_vmd(v)
    # 字节 54..69 是骨名。截断后必须是合法 CP932 且以 NUL 结尾。
    field = raw[54:69]
    assert field[:14].decode("cp932") == "一二三四五六七"
    assert field[14] == 0
    assert parse_vmd(raw).bone_frames[0].bone == "一二三四五六七"


def test_morph_frames_roundtrip():
    raw = make_vmd(morphs=[pack_morph("まばたき", 0, 0.0), pack_morph("まばたき", 10, 1.0)])
    v = parse_vmd(raw)
    assert [(m.frame, m.weight) for m in v.morph_frames] == [(0, 0.0), (10, 1.0)]
    assert build_vmd(v) == raw


def test_camera_light_shadow_ik_are_preserved():
    raw = make_vmd(
        bones=[pack_bone("センター")],
        cameras=[pack_camera(0), pack_camera(30)],
        lights=[pack_light(2)],
        shadows=[pack_shadow(4)],
        iks=[pack_ik(10, [("左足ＩＫ", True), ("右足ＩＫ", False)])],
    )
    v = parse_vmd(raw)
    assert len(v.camera) == 2
    assert len(v.light) == 1
    assert len(v.shadow) == 1
    assert len(v.ik) == 1
    assert build_vmd(v) == raw


def test_unknown_trailer_is_preserved():
    raw = make_vmd(bones=[pack_bone("センター")], trailer=b"PRIVATE\x00BLOCK")
    v = parse_vmd(raw)
    assert v.trailer == b"PRIVATE\x00BLOCK"
    assert build_vmd(v) == raw


def test_zero_count_with_one_camera_like_record_is_salvaged():
    """真实文件里出现过 count=0 却仍跟一条相机记录的情况。

    strict 模式必须报错（提示文件异常），非 strict 模式必须原样保留。
    """
    base = make_vmd(bones=[pack_bone("センター")])
    # 把 0x7FFFFFFF 写进「相机记录」的第 4–8 字节，让它被误读成
    # 自阴影数量时必然越界，从而触发 salvage 分支。
    record = bytearray(pack_camera(0))
    struct.pack_into("<I", record, 4, 0x7FFFFFFF)
    body = base[:-16] + struct.pack("<I", 0) + bytes(record) + struct.pack("<I", 0)

    with pytest.raises(VmdError):
        parse_vmd(body)

    v = parse_vmd(body, strict=False)
    assert v.sections_parsed is False
    assert v.trailer == body[len(base) - 16 :]
    assert build_vmd(v) == body


def test_truncated_file_raises_with_offset():
    raw = make_vmd(bones=[pack_bone("センター", 1)])
    with pytest.raises(VmdError) as ei:
        parse_vmd(raw[:-10])
    assert ei.value.offset is not None


def test_bad_header_raises():
    with pytest.raises(VmdError, match="bad VMD header"):
        parse_vmd(b"NOT A VMD" + b"\x00" * 100)


def test_interpolation_decode_linear():
    assert decode_interpolation(LINEAR64) == LINEAR_INTERPOLATION


def test_interpolation_encode_is_stable_for_linear():
    # 前 16 字节必须与 MMD 的权威布局一致。
    encoded = encode_interpolation(LINEAR_INTERPOLATION)
    assert len(encoded) == 64
    assert encoded[:16] == LINEAR64[:16]
    assert decode_interpolation(encoded) == LINEAR_INTERPOLATION


def test_interpolation_encode_decode_nonlinear():
    curves = ((20, 30, 100, 110), (5, 6, 120, 121), (1, 2, 125, 126), (127, 0, 0, 127))
    assert decode_interpolation(encode_interpolation(curves)) == curves


def test_sample_linear_curve_is_identity():
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert sample_curve(LINEAR_CURVE, t) == pytest.approx(t, abs=1e-6)


def test_sample_curve_is_monotonic():
    curve = (10, 90, 120, 20)  # ease-in-out
    values = [sample_curve(curve, i / 20) for i in range(21)]
    assert all(b >= a - 1e-9 for a, b in zip(values, values[1:]))
    assert values[0] == 0.0 and values[-1] == 1.0


def test_file_roundtrip(tmp_path):
    raw = make_vmd(bones=[pack_bone("センター", 5)], morphs=[pack_morph("あ", 5, 0.5)])
    src = tmp_path / "in.vmd"
    dst = tmp_path / "out.vmd"
    src.write_bytes(raw)
    v = read_vmd(src)
    write_vmd(v, dst)
    assert dst.read_bytes() == raw


def test_summary():
    raw = make_vmd(bones=[pack_bone("センター", 0), pack_bone("センター", 150)])
    s = parse_vmd(raw).summary()
    assert s["bones"] == 1
    assert s["bone_frames"] == 2
    assert s["frame_end"] == 150
    assert s["duration_sec"] == 5.0


def test_fd_padded_names_roundtrip_byte_exact():
    """第三方文件用 0xFD 填充骨名；解码后写回必须还原原始填充。"""
    fd_name = "センター".encode("cp932").ljust(15, b"\xfd")
    record = struct.pack(
        "<15sI3f4f64s", fd_name, 0, 0, 0, 0, 0, 0, 0, 1, LINEAR64
    )
    raw = make_vmd(bones=[record])
    v = parse_vmd(raw)
    assert v.bone_frames[0].bone == "センター"
    assert build_vmd(v) == raw
