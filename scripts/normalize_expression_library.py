#!/usr/bin/env python
"""
Normalize expression library:
- merge aliases (e.g. smile -> happy)
- deduplicate tags/images
- sort expressions by sample_count desc
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize PixelSmile expression library JSON.")
    parser.add_argument("--input", required=True, help="Input library JSON path.")
    parser.add_argument("--output", required=True, help="Output normalized JSON path.")
    parser.add_argument(
        "--aliases",
        default="",
        help="Alias map JSON path. Format: {\"smile\":\"happy\",\"joyful\":\"happy\"}",
    )
    return parser.parse_args()


def load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def canonical_name(name: str, alias_map: Dict[str, str]) -> str:
    key = (name or "").strip().lower()
    return alias_map.get(key, key)


def normalize_library(data: Dict, alias_map: Dict[str, str]) -> Dict:
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for expr in data.get("expressions", []):
        name = canonical_name(str(expr.get("name", "")), alias_map)
        if not name:
            continue
        item = dict(expr)
        item["name"] = name
        grouped[name].append(item)

    out_expr = []
    for name, items in grouped.items():
        sample_count = 0
        avg_intensity_acc = 0.0
        intensity_weight = 0
        strength_hint_acc = 0.0
        strength_weight = 0
        prompts = []
        tags = set()
        images = set()

        for item in items:
            sc = int(item.get("sample_count", 0))
            ai = float(item.get("avg_intensity", 0.0))
            sh = float(item.get("strength_hint", 1.0))
            sample_count += sc

            if sc > 0:
                avg_intensity_acc += ai * sc
                intensity_weight += sc
                strength_hint_acc += sh * sc
                strength_weight += sc
            else:
                avg_intensity_acc += ai
                intensity_weight += 1
                strength_hint_acc += sh
                strength_weight += 1

            p = str(item.get("prompt", "")).strip()
            if p:
                prompts.append(p)
            for t in item.get("tags", []):
                t = str(t).strip().lower()
                if t:
                    tags.add(t)
            for img in item.get("images", []):
                img = str(img).strip()
                if img:
                    images.add(img)

        prompt = prompts[0] if prompts else f"Edit the person to show a {name} expression"
        avg_intensity = round(avg_intensity_acc / max(1, intensity_weight), 3)
        strength_hint = round(strength_hint_acc / max(1, strength_weight), 3)
        out_expr.append(
            {
                "name": name,
                "prompt": prompt,
                "strength_hint": strength_hint,
                "sample_count": sample_count,
                "avg_intensity": avg_intensity,
                "tags": sorted(tags),
                "images": sorted(images),
            }
        )

    out_expr.sort(key=lambda x: (-int(x.get("sample_count", 0)), str(x.get("name", ""))))
    normalized = dict(data)
    normalized["expressions"] = out_expr
    return normalized


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    data = load_json(input_path)
    alias_map: Dict[str, str] = {}
    if args.aliases:
        alias_path = Path(args.aliases).expanduser().resolve()
        alias_raw = load_json(alias_path)
        alias_map = {
            str(k).strip().lower(): str(v).strip().lower()
            for k, v in alias_raw.items()
            if str(k).strip() and str(v).strip()
        }

    normalized = normalize_library(data, alias_map)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    print(f"Normalized library saved: {output_path}")
    print(f"Expressions: {len(normalized.get('expressions', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

