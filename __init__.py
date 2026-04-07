import json
from pathlib import Path
from typing import Any, Dict, List

import torch


def _resolve_library_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent / path


def _normalize_library(data: Dict[str, Any]) -> Dict[str, Any]:
    expressions = data.get("expressions", [])
    normalized: List[Dict[str, Any]] = []
    for item in expressions:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        prompt = str(item.get("prompt", "")).strip()
        if not name:
            continue
        if not prompt:
            prompt = f"Edit the person to show a {name} expression"
        normalized.append(
            {
                "name": name,
                "prompt": prompt,
                "strength_hint": float(item.get("strength_hint", 1.0)),
                "sample_count": int(item.get("sample_count", 0)),
                "avg_intensity": float(item.get("avg_intensity", 0.0)),
                "tags": item.get("tags", []),
                "images": item.get("images", []),
            }
        )
    return {
        "version": str(data.get("version", "1.0")),
        "neutral_prompt": str(
            data.get("neutral_prompt", "Edit the person to show a neutral expression")
        ),
        "expressions": normalized,
    }


def _format_prompt_with_strength(prompt: str, strength: float) -> str:
    if abs(strength - 1.0) < 1e-6:
        return prompt
    return f"{prompt}. Expression intensity: {strength:.2f}"


class PixelSmileConditioning:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "conditioning_target": (
                    "CONDITIONING",
                    {"tooltip": "Target expression conditioning (e.g. happy)."},
                ),
                "conditioning_neutral": (
                    "CONDITIONING",
                    {"tooltip": "Neutral expression conditioning."},
                ),
                "score": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": 0.0,
                        "max": 3.0,
                        "step": 0.05,
                        "tooltip": "Expression interpolation strength.",
                    },
                ),
                "method": (["score_one_all", "score_one"], {"default": "score_one_all"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("CONDITIONING",)
    FUNCTION = "apply_pixelsmile"
    CATEGORY = "conditioning/pixelsmile"
    DESCRIPTION = (
        "Interpolate target and neutral conditionings using PixelSmile logic for "
        "fine-grained expression control."
    )

    def apply_pixelsmile(self, conditioning_target, conditioning_neutral, score, method):
        out = []
        for i in range(len(conditioning_target)):
            tgt_tensor, tgt_kwargs = conditioning_target[i]
            neu_idx = min(i, len(conditioning_neutral) - 1)
            neu_tensor, neu_kwargs = conditioning_neutral[neu_idx]

            seq_tgt = tgt_tensor.shape[1]
            seq_neu = neu_tensor.shape[1]
            max_seq = max(seq_tgt, seq_neu)

            if seq_tgt < max_seq:
                tgt_tensor = torch.nn.functional.pad(
                    tgt_tensor, (0, 0, 0, max_seq - seq_tgt)
                )
            if seq_neu < max_seq:
                neu_tensor = torch.nn.functional.pad(
                    neu_tensor, (0, 0, 0, max_seq - seq_neu)
                )

            if method == "score_one_all":
                delta = tgt_tensor - neu_tensor
                result_tensor = neu_tensor + score * delta
            elif method == "score_one":
                if max_seq > 7:
                    prefix = tgt_tensor[:, :-7, :]
                    suffix_tgt = tgt_tensor[:, -7:, :]
                    suffix_neu = neu_tensor[:, -7:, :]
                    delta = suffix_tgt - suffix_neu
                    suffix = suffix_neu + score * delta
                    result_tensor = torch.cat([prefix, suffix], dim=1)
                else:
                    delta = tgt_tensor - neu_tensor
                    result_tensor = neu_tensor + score * delta
            else:
                delta = tgt_tensor - neu_tensor
                result_tensor = neu_tensor + score * delta

            result_kwargs = tgt_kwargs.copy()
            if "pooled_output" in result_kwargs and "pooled_output" in neu_kwargs:
                tgt_pooled = result_kwargs["pooled_output"]
                neu_pooled = neu_kwargs["pooled_output"]
                if tgt_pooled is not None and neu_pooled is not None:
                    delta_pooled = tgt_pooled - neu_pooled
                    result_kwargs["pooled_output"] = neu_pooled + score * delta_pooled

            if "attention_mask" in result_kwargs:
                attn_mask = result_kwargs["attention_mask"]
                if attn_mask is not None and attn_mask.shape[-1] < max_seq:
                    pad_amount = max_seq - attn_mask.shape[-1]
                    result_kwargs["attention_mask"] = torch.nn.functional.pad(
                        attn_mask, (0, pad_amount), value=0
                    )

            out.append([result_tensor, result_kwargs])
        return (out,)


class PixelSmileExpressionLibraryLoad:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "library_path": (
                    "STRING",
                    {
                        "default": "expression_library/library.json",
                        "multiline": False,
                        "tooltip": "Path to expression library JSON.",
                    },
                ),
            }
        }

    RETURN_TYPES = ("PIXELSMILE_EXPR_LIBRARY", "STRING")
    RETURN_NAMES = ("LIBRARY", "SUMMARY")
    FUNCTION = "load_library"
    CATEGORY = "conditioning/pixelsmile"
    DESCRIPTION = "Load a local expression library JSON."

    def load_library(self, library_path: str):
        full_path = _resolve_library_path(library_path)
        if not full_path.exists():
            raise FileNotFoundError(f"Expression library not found: {full_path}")
        with full_path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        normalized = _normalize_library(data)
        summary = (
            f"Loaded {len(normalized['expressions'])} expressions from {full_path.name} "
            f"(version {normalized['version']})"
        )
        return (normalized, summary)


class PixelSmileExpressionPromptFromLibrary:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "library": ("PIXELSMILE_EXPR_LIBRARY",),
                "expression_name": (
                    "STRING",
                    {
                        "default": "happy",
                        "multiline": False,
                        "tooltip": "Expression name from library.",
                    },
                ),
                "strength": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": 0.0,
                        "max": 3.0,
                        "step": 0.05,
                        "tooltip": "Prompt-side expression intensity hint.",
                    },
                ),
                "fallback_to_neutral": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("TARGET_PROMPT", "NEUTRAL_PROMPT", "EXPRESSION_META_JSON")
    FUNCTION = "build_prompts"
    CATEGORY = "conditioning/pixelsmile"
    DESCRIPTION = "Build target and neutral prompts from an expression library."

    def build_prompts(
        self,
        library: Dict[str, Any],
        expression_name: str,
        strength: float,
        fallback_to_neutral: bool,
    ):
        expressions = library.get("expressions", [])
        by_name = {
            str(item.get("name", "")).strip().lower(): item for item in expressions
        }
        key = expression_name.strip().lower()
        neutral_prompt = library.get(
            "neutral_prompt", "Edit the person to show a neutral expression"
        )

        picked = by_name.get(key)
        if picked is None and fallback_to_neutral:
            target_prompt = neutral_prompt
            meta = {
                "status": "fallback_neutral",
                "expression_name": expression_name,
                "neutral_prompt": neutral_prompt,
            }
            return (
                _format_prompt_with_strength(target_prompt, strength),
                neutral_prompt,
                json.dumps(meta, ensure_ascii=False),
            )

        if picked is None:
            raise ValueError(
                f"Expression '{expression_name}' not found in library and fallback is disabled."
            )

        target_prompt = str(picked.get("prompt", "")).strip()
        if not target_prompt:
            target_prompt = f"Edit the person to show a {expression_name} expression"
        target_prompt = _format_prompt_with_strength(target_prompt, strength)
        return (
            target_prompt,
            neutral_prompt,
            json.dumps(picked, ensure_ascii=False),
        )


class PixelSmileExpressionNames:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "library": ("PIXELSMILE_EXPR_LIBRARY",),
            }
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("EXPRESSION_NAMES_CSV", "COUNT")
    FUNCTION = "list_names"
    CATEGORY = "conditioning/pixelsmile"
    DESCRIPTION = "List expression names from the loaded library."

    def list_names(self, library: Dict[str, Any]):
        names = [str(item.get("name", "")).strip() for item in library.get("expressions", [])]
        names = [name for name in names if name]
        return (",".join(names), len(names))


class PixelSmileExpressionPromptByIndex:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "library": ("PIXELSMILE_EXPR_LIBRARY",),
                "expression_index": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 9999,
                        "step": 1,
                        "tooltip": "Expression index in library order.",
                    },
                ),
                "strength": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": 0.0,
                        "max": 3.0,
                        "step": 0.05,
                    },
                ),
                "fallback_to_neutral": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("TARGET_PROMPT", "NEUTRAL_PROMPT", "EXPRESSION_NAME", "EXPRESSION_COUNT")
    FUNCTION = "build_prompts_by_index"
    CATEGORY = "conditioning/pixelsmile"
    DESCRIPTION = "Build prompts by expression index to avoid typo in expression names."

    def build_prompts_by_index(
        self, library: Dict[str, Any], expression_index: int, strength: float, fallback_to_neutral: bool
    ):
        expressions = library.get("expressions", [])
        count = len(expressions)
        neutral_prompt = library.get(
            "neutral_prompt", "Edit the person to show a neutral expression"
        )
        if count == 0:
            if fallback_to_neutral:
                return (
                    _format_prompt_with_strength(neutral_prompt, strength),
                    neutral_prompt,
                    "neutral",
                    0,
                )
            raise ValueError("Expression library is empty.")

        idx = max(0, min(int(expression_index), count - 1))
        picked = expressions[idx]
        expression_name = str(picked.get("name", f"expr_{idx}"))
        target_prompt = str(picked.get("prompt", "")).strip()
        if not target_prompt:
            target_prompt = f"Edit the person to show a {expression_name} expression"
        return (
            _format_prompt_with_strength(target_prompt, strength),
            neutral_prompt,
            expression_name,
            count,
        )


NODE_CLASS_MAPPINGS = {
    "PixelSmileConditioning": PixelSmileConditioning,
    "PixelSmileExpressionLibraryLoad": PixelSmileExpressionLibraryLoad,
    "PixelSmileExpressionPromptFromLibrary": PixelSmileExpressionPromptFromLibrary,
    "PixelSmileExpressionNames": PixelSmileExpressionNames,
    "PixelSmileExpressionPromptByIndex": PixelSmileExpressionPromptByIndex,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PixelSmileConditioning": "PixelSmile Conditioning Interpolation",
    "PixelSmileExpressionLibraryLoad": "PixelSmile Expression Library Load",
    "PixelSmileExpressionPromptFromLibrary": "PixelSmile Expression Prompt From Library",
    "PixelSmileExpressionNames": "PixelSmile Expression Names",
    "PixelSmileExpressionPromptByIndex": "PixelSmile Expression Prompt By Index",
}

