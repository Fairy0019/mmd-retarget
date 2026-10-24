# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""允许 ``python -m mmd_retarget`` 直接调用 CLI。"""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
