# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""在 Blender 里调用 mmd-retarget CLI。

Blender 会把 ``--`` 之后的参数原样放进 sys.argv；本脚本把它们切出来交给
argparse。用法::

    blender -b --python tools/blender_cli.py -- validate --model m.pmx --motion a.vmd -o report.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mmd_retarget.cli import main  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    raise SystemExit(main(argv))
