#!/usr/bin/env python
"""
Build a local PixelSmile expression library by asking an Ollama vision model
to label expression images.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
DEFAULT_INTENSITY_BY_NAME = {
    "neutral": 0.15,
    "happy": 0.65,
    "sad": 0.55,
    "angry": 0.70,
    "surprised": 0.75,
    "fear": 0.75,
    "disgust": 0.70,
}

OLLAMA_PROMPT = """You are labeling a face expression reference image.
Return STRICT JSON only, no markdown, no explanation.
Schema:
{
  "expression_name": "one_or_two_words_snake_case",
  "description": "short plain English phrase",
  "intensity": 0.0,
  "tags": ["tag1","tag2","tag3"]
}
Rules:
- expression_name should be stable across similar images (happy, sad, angry, neutral, surprised, etc.)
- intensity must be a number in [0.0, 1.0]
- tags should be 3-8 short tags
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build expression library JSON from local images with Ollama vision."
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing expression images.",
    )
    parser.add_argument(
        "--output",
        default="expression_library/library.json",
        help="Output JSON path.",
    )
    parser.add_argument(
        "--model",
        default="llava:7b",
        help="Ollama model name. Must support image input.",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://127.0.0.1:11434/api/generate",
        help="Ollama generate API URL.",
    )
    parser.add_argument(
        "--neutral-prompt",
        default="Edit the person to show a neutral expression",
        help="Neutral prompt written into library.json.",
    )
    parser.add_argument(
        "--label-source",
        choices=["ollama", "filename"],
        default="ollama",
        help="Label source: ollama vision model or filename heuristic.",
    )
    parser.add_argument(
        "--filename-pattern",
        choices=["prefix", "parent_dir"],
        default="prefix",
        help="Used when --label-source=filename.",
    )
    return parser.parse_args()


def collect_images(input_dir: Path) -> List[Path]:
    images: List[Path] = []
    for path in input_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            images.append(path)
    images.sort()
    return images


def encode_image_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def extract_json(text: str) -> Dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"Failed to parse JSON from Ollama response: {text[:300]}")
    return json.loads(match.group(0))


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _sanitize_expression_name(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip().lower())
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "unknown"


def label_image_from_filename(image_path: Path, filename_pattern: str) -> Tuple[str, Dict]:
    if filename_pattern == "parent_dir":
        candidate = image_path.parent.name
    else:
        stem = image_path.stem
        match = re.match(r"([a-zA-Z]+)", stem)
        candidate = match.group(1) if match else stem

    expression_name = _sanitize_expression_name(candidate)
    intensity = DEFAULT_INTENSITY_BY_NAME.get(expression_name, 0.6)
    result = {
        "expression_name": expression_name,
        "description": expression_name.replace("_", " "),
        "intensity": intensity,
        "tags": [expression_name],
        "source_model": "filename-heuristic",
    }
    return expression_name, result


def label_image_with_ollama(
    image_path: Path, model: str, ollama_url: str
) -> Tuple[str, Dict]:
    payload = {
        "model": model,
        "prompt": OLLAMA_PROMPT,
        "images": [encode_image_b64(image_path)],
        "stream": False,
        "format": "json",
    }
    req = Request(
        ollama_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Ollama HTTP error {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot connect to Ollama ({ollama_url}): {exc}") from exc

    response_text = str(body.get("response", "")).strip()
    if not response_text:
        raise RuntimeError(f"Ollama returned empty response for image: {image_path}")
    parsed = extract_json(response_text)

    expression_name = str(parsed.get("expression_name", "")).strip().lower()
    expression_name = _sanitize_expression_name(expression_name)
    description = str(parsed.get("description", "")).strip()
    if not description:
        description = expression_name.replace("_", " ")
    intensity = clamp(float(parsed.get("intensity", 0.5)), 0.0, 1.0)
    tags = parsed.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(tag).strip().lower() for tag in tags if str(tag).strip()]

    result = {
        "expression_name": expression_name,
        "description": description,
        "intensity": intensity,
        "tags": tags,
        "source_model": model,
    }
    return expression_name, result


def build_library(
    input_dir: Path,
    images: List[Path],
    neutral_prompt: str,
    model: str,
    ollama_url: str,
    label_source: str,
    filename_pattern: str,
) -> Dict:
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    rel_base = input_dir.resolve()

    for idx, image in enumerate(images, start=1):
        print(f"[{idx}/{len(images)}] labeling: {image.name}")
        if label_source == "filename":
            expression_name, item = label_image_from_filename(
                image_path=image,
                filename_pattern=filename_pattern,
            )
        else:
            expression_name, item = label_image_with_ollama(
                image,
                model=model,
                ollama_url=ollama_url,
            )
        item["image"] = image.resolve().relative_to(rel_base).as_posix()
        grouped[expression_name].append(item)

    expressions = []
    for name, items in sorted(grouped.items(), key=lambda x: x[0]):
        avg_intensity = sum(x["intensity"] for x in items) / len(items)
        tags = sorted({tag for x in items for tag in x.get("tags", [])})
        prompt = f"Edit the person to show a {name.replace('_', ' ')} expression"
        expressions.append(
            {
                "name": name,
                "prompt": prompt,
                "strength_hint": round(avg_intensity * 2.0, 3),
                "sample_count": len(items),
                "avg_intensity": round(avg_intensity, 3),
                "tags": tags,
                "images": [x["image"] for x in items],
            }
        )

    return {
        "version": "1.0",
        "neutral_prompt": neutral_prompt,
        "source": {
            "generator": "scripts/build_expression_library.py",
            "model": model if label_source == "ollama" else "filename-heuristic",
            "label_source": label_source,
            "image_count": len(images),
        },
        "expressions": expressions,
    }


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not input_dir.exists():
        print(f"Input directory not found: {input_dir}", file=sys.stderr)
        return 2

    images = collect_images(input_dir)
    if not images:
        print(f"No images found under: {input_dir}", file=sys.stderr)
        return 2

    try:
        library = build_library(
            input_dir=input_dir,
            images=images,
            neutral_prompt=args.neutral_prompt,
            model=args.model,
            ollama_url=args.ollama_url,
            label_source=args.label_source,
            filename_pattern=args.filename_pattern,
        )
    except Exception as exc:
        print(f"Failed to build expression library: {exc}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Library saved: {output_path}")
    print(f"Expressions: {len(library['expressions'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
