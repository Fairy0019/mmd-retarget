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


def test_cli_stub_runs(capsys):
    assert main(["retarget", "motion.json", "-s", "a", "-t", "b", "-o", "c.vmd"]) == 0
    out = capsys.readouterr().out
    assert "not implemented" in out


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
