# -*- coding: utf-8 -*-
import json

from mmd_retarget import __version__
from mmd_retarget.cli import build_parser, main
from mmd_retarget.vmd import BoneFrame, MorphFrame, Vmd, write_vmd


def test_version():
    assert __version__.count(".") == 2


def test_cli_parses_known_commands():
    p = build_parser()
    args = p.parse_args(["inspect", "motion.vmd"])
    assert args.command == "inspect"
    assert args.file == "motion.vmd"

    args = p.parse_args(["retarget", "motion.json", "-s", "a.json", "-t", "b.json", "-o", "x.vmd"])
    assert args.command == "retarget"
    assert args.out == "x.vmd"



def test_inspect_missing_file(capsys):
    assert main(["inspect", "nope.vmd"]) == 2
    assert "file not found" in capsys.readouterr().err


def test_inspect_vmd(tmp_path, capsys):
    motion = Vmd(
        model_name="テスト",
        bone_frames=[BoneFrame("センター", 0), BoneFrame("センター", 30)],
        morph_frames=[MorphFrame("まばたき", 30, 1.0)],
    )
    path = tmp_path / "m.vmd"
    write_vmd(motion, path)

    assert main(["inspect", str(path)]) == 0
    out = capsys.readouterr().out
    assert "テスト" in out
    assert "1 unique / 2 keyframes" in out
    assert "0 – 30" in out

    assert main(["inspect", str(path), "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["bones"] == 1
    assert info["morph_frames"] == 1
    assert info["model"] == "テスト"


def _profile_dict() -> dict:
    return {
        "model": "Test",
        "map": {"root": "センター", "spine": "上半身"},
        "rest": {
            "センター": {"head": [0, 0, 0], "parent": None},
            "上半身": {"head": [0, 5, 0], "parent": "センター"},
        },
        "morphs": ["まばたき"],
    }


def test_inspect_writes_canonical(tmp_path, capsys):
    import json

    from mmd_retarget.vmd import BoneFrame, MorphFrame, Vmd, write_vmd

    vmd_path = tmp_path / "m.vmd"
    write_vmd(
        Vmd(
            model_name="Test",
            bone_frames=[BoneFrame("センター", 0), BoneFrame("センター", 30, (0, 1, 0))],
            morph_frames=[MorphFrame("まばたき", 30, 1.0)],
        ),
        vmd_path,
    )
    profile_path = tmp_path / "p.json"
    profile_path.write_text(json.dumps(_profile_dict()), encoding="utf-8")
    out = tmp_path / "motion.json"

    assert main(["inspect", str(vmd_path), "-p", str(profile_path), "-o", str(out)]) == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["schema"] == 1
    assert body["frames"] == 31
    assert body["root"]["pos"][-1][1:] == [0.0, 1.0, 0.0]
    assert "spine" in body["joints"] or body["joints"] == {}
    assert "canonical" in capsys.readouterr().out


def test_inspect_out_requires_profile(tmp_path, capsys):
    from mmd_retarget.vmd import Vmd, write_vmd

    vmd_path = tmp_path / "m.vmd"
    write_vmd(Vmd(model_name="Test"), vmd_path)
    assert main(["inspect", str(vmd_path), "-o", str(tmp_path / "x.json")]) == 2
    assert "--profile" in capsys.readouterr().err


def test_retarget_pass_through(tmp_path, capsys):
    import json

    from mmd_retarget.canonical import build_canonical, save_canonical
    from mmd_retarget.vmd import BoneFrame, Vmd, parse_vmd

    profile = _profile_dict()
    src = Vmd(
        model_name="Test",
        bone_frames=[BoneFrame("センター", 0), BoneFrame("センター", 5, (0, 0.5, 0))],
    )
    canonical = build_canonical(src, profile, detect=False)
    motion_path = tmp_path / "motion.json"
    save_canonical(canonical, motion_path)
    profile_path = tmp_path / "p.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    out_path = tmp_path / "out.vmd"

    assert main(
        [
            "retarget",
            str(motion_path),
            "-s",
            str(profile_path),
            "-t",
            str(profile_path),
            "-o",
            str(out_path),
        ]
    ) == 0
    out = parse_vmd(out_path.read_bytes())
    assert out.model_name == "Test"
    assert len(out.bone_frames) == 2
    assert "stage 5" in capsys.readouterr().out
def test_physics_requires_inputs(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["physics"])
    assert exc.value.code == 2
