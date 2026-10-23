# -*- coding: utf-8 -*-
from mmd_retarget import __version__
from mmd_retarget.cli import build_parser, main


def test_version():
    assert __version__.count(".") == 2


def test_cli_parses_known_commands():
    p = build_parser()
    args = p.parse_args(["inspect", "motion.vmd"])
    assert args.command == "inspect"
    assert args.file == "motion.vmd"


def test_cli_stub_runs(capsys):
    assert main(["inspect", "motion.vmd"]) == 0
    out = capsys.readouterr().out
    assert "not implemented" in out
