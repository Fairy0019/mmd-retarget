# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""部位规则：把“哪些材质/骨骼算哪个部位”从硬编码变成可配置。

默认规则针对日文 MMD 模型（裙/髮/翼/腕/足…）。换模型时用
``--parts-config rules.json`` 覆盖，不必改代码。

配置结构::

    {
      "material": {"skirt": ["裙"], "hair": ["髮", "前髪"], "wings": ["翼"]},
      "exclude_material": ["裙内"],
      "side_prefix": {"left": "左", "right": "右"},
      "limb_groups": {
        "Arm": ["肩", "腕", "ひじ", "手首", "手捩"],
        "Leg": ["足", "ひざ", "つま先"]
      },
      "torso": ["上半身", "下半身", "腰", "首", "頭", "センター", "グルーブ", "全ての親"],
      "pairs": [["leftArm", "torso"], ...],
      "outside_is_bad": [["leftLeg", "skirt"]]
    }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_RULES",
    "load_rules",
    "classify_material",
    "classify_bone",
    "part_pairs",
    "outside_is_bad",
]


DEFAULT_RULES: dict[str, Any] = {
    "material": {
        "skirt": ["裙"],
        "hair": ["髮", "前髪"],
        "wings": ["翼"],
    },
    # 内衬不算外层裙面：腿在内衬里面是正常的。
    "exclude_material": ["裙内"],
    "side_prefix": {"left": "左", "right": "右"},
    # 本项目的 MMD 模型用 .L/.R 后缀，两种命名都要支持。
    "side_suffix": {"left": ".L", "right": ".R"},
    "limb_groups": {
        "Arm": ["肩", "腕", "ひじ", "手首", "手捩"],
        "Leg": ["足", "ひざ", "つま先"],
    },
    "torso": ["上半身", "下半身", "腰", "首", "頭", "センター", "グルーブ", "全ての親"],
    "pairs": [
        ["leftArm", "torso"],
        ["rightArm", "torso"],
        ["leftArm", "skirt"],
        ["rightArm", "skirt"],
        ["leftLeg", "skirt"],
        ["rightLeg", "skirt"],
        ["hair", "torso"],
        ["wings", "torso"],
    ],
    "outside_is_bad": [["leftLeg", "skirt"], ["rightLeg", "skirt"]],
}


def _merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            out[k] = _merge(base.get(k), v)
        return out
    return override if override is not None else base


def load_rules(path: str | Path | None = None) -> dict[str, Any]:
    """读入规则文件并与默认值合并（文件只需写想覆盖的字段）。"""
    if path is None:
        return json.loads(json.dumps(DEFAULT_RULES))
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return _merge(DEFAULT_RULES, data)


def classify_material(name: str, rules: dict) -> str | None:
    for key in rules.get("exclude_material", []):
        if key in name:
            return None
    for part, keywords in rules.get("material", {}).items():
        if any(k in name for k in keywords):
            return part
    return None


def classify_bone(name: str, rules: dict) -> str | None:
    prefixes = rules.get("side_prefix", {})
    suffixes = rules.get("side_suffix", {})
    for side in set(prefixes) | set(suffixes):
        hit = False
        prefix = prefixes.get(side)
        suffix = suffixes.get(side)
        if prefix and name.startswith(prefix):
            hit = True
        if suffix and name.endswith(suffix):
            hit = True
        if not hit:
            continue
        for group, keywords in rules.get("limb_groups", {}).items():
            if any(k in name for k in keywords):
                return f"{side}{group}"
    if any(k in name for k in rules.get("torso", [])):
        return "torso"
    return None


def part_pairs(rules: dict) -> list[tuple[str, str]]:
    return [tuple(p) for p in rules.get("pairs", [])]


def outside_is_bad(rules: dict) -> set[tuple[str, str]]:
    return {tuple(p) for p in rules.get("outside_is_bad", [])}
