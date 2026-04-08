from __future__ import annotations

import copy
import io
import json
import random
import re
import shutil
import traceback
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import gradio as gr
from PIL import Image

from comfy_client import ComfyClient, get_first_output_image, load_json

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "ui_config.json"
PRESET_PATH_DEFAULT = ROOT / "config" / "ui_presets.json"
LOGO_FAVICON = ROOT / "logo.png"
LOGO_UI = ROOT / "logo1.png"
ALBUM_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"缺少配置文件: {CONFIG_PATH}")
    return load_json(CONFIG_PATH)


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def _sanitize_name(raw: str, fallback: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff_-]+", "_", (raw or "").strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s or fallback


def _default_album_name() -> str:
    return datetime.now().strftime("%Y%m%d")


def _album_root(cfg: Dict[str, Any]) -> Path:
    root = _resolve_path(str(cfg.get("album_dir", "album")))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_library(cfg: Dict[str, Any]) -> Dict[str, Any]:
    lib_path = _resolve_path(str(cfg["expression_library_path"]))
    data = load_json(lib_path)
    expressions = [e for e in data.get("expressions", []) if e.get("name")]
    if not expressions:
        raise ValueError(f"表情库为空: {lib_path}")
    data["expressions"] = expressions
    return data


def _save_library(cfg: Dict[str, Any], data: Dict[str, Any]) -> Path:
    lib_path = _resolve_path(str(cfg["expression_library_path"]))
    lib_path.parent.mkdir(parents=True, exist_ok=True)
    with lib_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return lib_path


def _expression_choices(lib: Dict[str, Any]) -> List[str]:
    return [str(x["name"]) for x in lib["expressions"]]


def _find_prompt(lib: Dict[str, Any], name: str, strength: float) -> str:
    picked = next((x for x in lib["expressions"] if str(x.get("name")) == name), None)
    if not picked:
        return lib.get("neutral_prompt", "Edit the person to show a neutral expression")
    prompt = str(picked.get("prompt") or f"Edit the person to show a {name} expression")
    if abs(strength - 1.0) < 1e-6:
        return prompt
    return f"{prompt}. Expression intensity: {strength:.2f}"


def _set_input(prompt: Dict[str, Any], node_id: str, key: str, value: Any) -> None:
    nid = str(node_id)
    if nid not in prompt:
        raise KeyError(f"API 工作流中不存在节点ID: {nid}")
    prompt[nid]["inputs"][key] = value


def _build_prompt(
    api_workflow: Dict[str, Any],
    cfg: Dict[str, Any],
    image_name: str,
    target_prompt: str,
    neutral_prompt: str,
    score: float,
    method: str,
    width: int,
    height: int,
    seed: int,
) -> Dict[str, Any]:
    p = copy.deepcopy(api_workflow)
    ids = cfg["node_ids"]

    _set_input(p, ids["load_image"], "image", image_name)
    _set_input(p, ids["target_text_encode"], "prompt", target_prompt)
    _set_input(p, ids["neutral_text_encode"], "prompt", neutral_prompt)
    _set_input(p, ids["pixelsmile"], "score", float(score))
    _set_input(p, ids["pixelsmile"], "method", method)
    _set_input(p, ids["image_scale"], "width", int(width))
    _set_input(p, ids["image_scale"], "height", int(height))
    _set_input(p, ids["latent"], "width", int(width))
    _set_input(p, ids["latent"], "height", int(height))
    _set_input(p, ids["ksampler"], "seed", int(seed))
    return p


def _preset_file(cfg: Dict[str, Any]) -> Path:
    raw = str(cfg.get("preset_file", PRESET_PATH_DEFAULT.as_posix()))
    return _resolve_path(raw)


def _load_presets(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    path = _preset_file(cfg)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, dict)}


def _save_presets(cfg: Dict[str, Any], presets: Dict[str, Dict[str, Any]]) -> Path:
    path = _preset_file(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)
    return path


def _preset_choices(cfg: Dict[str, Any]) -> List[str]:
    return sorted(_load_presets(cfg).keys())


def _save_to_album(
    img: Image.Image,
    cfg: Dict[str, Any],
    album_name: str,
    expression_name: str,
    seed: int,
    index: int | None = None,
) -> Path:
    root = _album_root(cfg)
    album = _sanitize_name(album_name, _default_album_name())
    expr = _sanitize_name(expression_name, "expression")
    expr_dir = root / album / expr
    expr_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{index:02d}_" if index is not None else ""
    out = expr_dir / f"{prefix}{expr}_seed{seed}_{ts}.png"
    img.save(out)
    return out


def _list_albums(cfg: Dict[str, Any]) -> List[str]:
    root = _album_root(cfg)
    items = [p.name for p in root.iterdir() if p.is_dir()]
    items.sort(reverse=True)
    return items


def _scan_album_images(album_dir: Path) -> List[Path]:
    files = []
    for p in album_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in ALBUM_IMAGE_EXTS:
            files.append(p)
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return files


def _favorites_file(album_dir: Path) -> Path:
    return album_dir / ".favorites.json"


def _load_favorites(album_dir: Path) -> set[str]:
    fp = _favorites_file(album_dir)
    if not fp.exists():
        return set()
    try:
        with fp.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {str(x) for x in data}
    except Exception:
        return set()
    return set()


def _save_favorites(album_dir: Path, favs: set[str]) -> None:
    fp = _favorites_file(album_dir)
    with fp.open("w", encoding="utf-8") as f:
        json.dump(sorted(favs), f, ensure_ascii=False, indent=2)


def _build_gallery_for_album(
    album_name: str,
    keyword: str,
    page: int,
    only_favorites: bool = False,
    page_size: int = 24,
):
    cfg = _load_config()
    root = _album_root(cfg)
    album_name = _sanitize_name(album_name, "")
    if not album_name:
        return [], "请先选择相册。", 1, []
    album_dir = root / album_name
    if not album_dir.exists():
        return [], f"相册不存在: {album_name}", 1, []

    files = _scan_album_images(album_dir)
    favs = _load_favorites(album_dir)
    kw = (keyword or "").strip().lower()
    if kw:
        files = [p for p in files if kw in p.name.lower() or kw in str(p.parent).lower()]
    if only_favorites:
        files = [p for p in files if p.relative_to(album_dir).as_posix() in favs]

    total = len(files)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, int(page)), total_pages)
    start = (page - 1) * page_size
    end = start + page_size
    page_files = files[start:end]

    gallery = []
    rel_paths = []
    for p in page_files:
        rel = p.relative_to(album_dir).as_posix()
        cap = f"★ {rel}" if rel in favs else rel
        gallery.append((str(p), cap))
        rel_paths.append(str(p))

    info = f"相册: {album_name} | 图片: {total} | 页码: {page}/{total_pages}"
    return gallery, info, page, rel_paths


def _refresh_album_list():
    cfg = _load_config()
    albums = _list_albums(cfg)
    val = albums[0] if albums else None
    return gr.Dropdown(choices=albums, value=val), f"已刷新相册列表，共 {len(albums)} 个。"


def _load_album(album_name: str, keyword: str, only_favorites: bool):
    gallery, info, page, paths = _build_gallery_for_album(album_name, keyword, page=1, only_favorites=only_favorites)
    return gallery, info, page, paths, None, ""


def _album_prev(album_name: str, keyword: str, page: int, only_favorites: bool):
    gallery, info, page2, paths = _build_gallery_for_album(
        album_name, keyword, page=max(1, int(page) - 1), only_favorites=only_favorites
    )
    return gallery, info, page2, paths


def _album_next(album_name: str, keyword: str, page: int, only_favorites: bool):
    gallery, info, page2, paths = _build_gallery_for_album(
        album_name, keyword, page=int(page) + 1, only_favorites=only_favorites
    )
    return gallery, info, page2, paths


def _on_gallery_select(evt: gr.SelectData, current_paths: List[str]):
    idx = evt.index
    if isinstance(idx, (tuple, list)):
        idx = idx[0]
    if idx is None or idx < 0 or idx >= len(current_paths):
        return None, ""
    path = current_paths[idx]
    try:
        img = Image.open(path).convert("RGB")
        return img, path
    except Exception:
        return None, path


def _rename_selected(
    selected_path: str, new_name: str, album_name: str, keyword: str, page: int, only_favorites: bool
):
    if not selected_path:
        gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
        return gallery, info + "\n未选择图片。", page2, paths, None, ""

    src = Path(selected_path)
    if not src.exists():
        gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
        return gallery, info + "\n文件不存在。", page2, paths, None, ""

    stem = _sanitize_name(new_name, "")
    if not stem:
        gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
        return gallery, info + "\n请输入新的文件名。", page2, paths, None, ""

    dst = src.with_name(stem + src.suffix.lower())
    src.rename(dst)

    gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
    return gallery, info + f"\n已重命名: {dst.name}", page2, paths, None, ""


def _delete_selected(selected_path: str, album_name: str, keyword: str, page: int, only_favorites: bool):
    if not selected_path:
        gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
        return gallery, info + "\n未选择图片。", page2, paths, None, ""

    src = Path(selected_path)
    cfg = _load_config()
    album_dir = _album_root(cfg) / _sanitize_name(album_name, "")
    favs = _load_favorites(album_dir) if album_dir.exists() else set()
    if src.exists():
        rel = src.relative_to(album_dir).as_posix() if album_dir.exists() else ""
        if rel in favs:
            favs.remove(rel)
            _save_favorites(album_dir, favs)
        src.unlink()

    gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
    return gallery, info + "\n已删除图片。", page2, paths, None, ""


def _toggle_favorite(selected_path: str, album_name: str, keyword: str, page: int, only_favorites: bool):
    if not selected_path:
        gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
        return gallery, info + "\n未选择图片。", page2, paths
    cfg = _load_config()
    album_dir = _album_root(cfg) / _sanitize_name(album_name, "")
    if not album_dir.exists():
        gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
        return gallery, info + "\n相册不存在。", page2, paths
    src = Path(selected_path)
    rel = src.relative_to(album_dir).as_posix()
    favs = _load_favorites(album_dir)
    if rel in favs:
        favs.remove(rel)
        msg = "已取消收藏。"
    else:
        favs.add(rel)
        msg = "已收藏。"
    _save_favorites(album_dir, favs)
    gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
    return gallery, info + f"\n{msg}", page2, paths


def _move_selected(
    selected_path: str,
    target_album_name: str,
    album_name: str,
    keyword: str,
    page: int,
    only_favorites: bool,
):
    if not selected_path:
        gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
        return gallery, info + "\n未选择图片。", page2, paths, gr.Dropdown(), None, ""
    cfg = _load_config()
    src_album = _sanitize_name(album_name, "")
    dst_album = _sanitize_name(target_album_name, "")
    if not dst_album:
        gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
        return gallery, info + "\n请输入目标相册名称。", page2, paths, gr.Dropdown(), None, ""
    root = _album_root(cfg)
    src_album_dir = root / src_album
    src = Path(selected_path)
    if not src.exists():
        gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
        return gallery, info + "\n文件不存在。", page2, paths, gr.Dropdown(), None, ""
    rel_parent = src.parent.relative_to(src_album_dir)
    dst_dir = root / dst_album / rel_parent
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists():
        dst = dst_dir / f"{src.stem}_{datetime.now().strftime('%H%M%S')}{src.suffix.lower()}"
    shutil.move(str(src), str(dst))

    # update favorites source and target
    src_favs = _load_favorites(src_album_dir) if src_album_dir.exists() else set()
    src_rel = src.relative_to(src_album_dir).as_posix()
    was_starred = src_rel in src_favs
    if was_starred:
        src_favs.remove(src_rel)
        _save_favorites(src_album_dir, src_favs)
        dst_album_dir = root / dst_album
        dst_favs = _load_favorites(dst_album_dir)
        dst_rel = dst.relative_to(dst_album_dir).as_posix()
        dst_favs.add(dst_rel)
        _save_favorites(dst_album_dir, dst_favs)

    albums = _list_albums(cfg)
    gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
    return gallery, info + f"\n已移动到相册 {dst_album}: {dst.name}", page2, paths, gr.Dropdown(choices=albums, value=album_name), None, ""


def _batch_rename_current(
    album_name: str,
    keyword: str,
    page: int,
    only_favorites: bool,
    rename_prefix: str,
):
    cfg = _load_config()
    root = _album_root(cfg)
    album = _sanitize_name(album_name, "")
    if not album:
        gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
        return gallery, info + "\n请先选择相册。", page2, paths
    album_dir = root / album
    files = _scan_album_images(album_dir)
    kw = (keyword or "").strip().lower()
    if kw:
        files = [p for p in files if kw in p.name.lower() or kw in str(p.parent).lower()]
    if only_favorites:
        favs = _load_favorites(album_dir)
        files = [p for p in files if p.relative_to(album_dir).as_posix() in favs]
    prefix = _sanitize_name(rename_prefix, "")
    if not prefix:
        prefix = "img"
    # keep stable order by current name
    files = sorted(files, key=lambda x: x.name.lower())
    mapping: Dict[str, str] = {}
    for i, src in enumerate(files, start=1):
        dst = src.with_name(f"{prefix}_{i:03d}{src.suffix.lower()}")
        if dst == src:
            continue
        # avoid collision
        if dst.exists():
            dst = src.with_name(f"{prefix}_{i:03d}_{datetime.now().strftime('%H%M%S')}{src.suffix.lower()}")
        src.rename(dst)
        mapping[src.relative_to(album_dir).as_posix()] = dst.relative_to(album_dir).as_posix()

    if mapping:
        favs = _load_favorites(album_dir)
        new_favs = set()
        for rel in favs:
            new_favs.add(mapping.get(rel, rel))
        _save_favorites(album_dir, new_favs)

    gallery, info, page2, paths = _build_gallery_for_album(album_name, keyword, page, only_favorites=only_favorites)
    return gallery, info + f"\n已批量重命名 {len(mapping)} 张图片。", page2, paths


def _export_album_zip(album_name: str, only_favorites: bool) -> Tuple[str | None, str]:
    try:
        cfg = _load_config()
        root = _album_root(cfg)
        album = _sanitize_name(album_name, "")
        if not album:
            return None, "请先选择相册。"
        album_dir = root / album
        if not album_dir.exists():
            return None, f"相册不存在: {album}"

        files = _scan_album_images(album_dir)
        if only_favorites:
            favs = _load_favorites(album_dir)
            files = [p for p in files if p.relative_to(album_dir).as_posix() in favs]
        if not files:
            return None, "没有可导出的图片。"

        export_dir = root / "_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = "_favorites" if only_favorites else "_all"
        zip_path = export_dir / f"{album}{suffix}_{ts}.zip"

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in files:
                arcname = p.relative_to(album_dir).as_posix()
                zf.write(p, arcname=arcname)

        return str(zip_path), f"导出完成: {zip_path}（共 {len(files)} 张）"
    except Exception as exc:
        return None, f"导出失败: {exc}\n\n{traceback.format_exc()}"


def _run_single_core(
    image: Image.Image,
    expression_name: str,
    score: float,
    method: str,
    strength_hint: float,
    width: int,
    height: int,
    seed: int,
    save_album: bool,
    album_name: str,
    album_index: int | None = None,
    target_prompt_override: str | None = None,
) -> Tuple[Image.Image, str]:
    cfg = _load_config()
    lib = _load_library(cfg)
    api_workflow = load_json(_resolve_path(str(cfg["api_workflow_path"])))
    client = ComfyClient(base_url=str(cfg["comfy_base_url"]))

    tmp_path = ROOT / "temp" / "ui_input.png"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(tmp_path)
    uploaded_name = client.upload_image(tmp_path)

    target_prompt = target_prompt_override if target_prompt_override else _find_prompt(lib, expression_name, strength_hint)
    neutral_prompt = str(lib.get("neutral_prompt", "Edit the person to show a neutral expression"))

    if seed < 0:
        seed = random.randint(1, 2**31 - 1)

    prompt = _build_prompt(
        api_workflow=api_workflow,
        cfg=cfg,
        image_name=uploaded_name,
        target_prompt=target_prompt,
        neutral_prompt=neutral_prompt,
        score=score,
        method=method,
        width=width,
        height=height,
        seed=seed,
    )

    prompt_id = client.queue_prompt(prompt)
    meta = client.wait_until_done(prompt_id, max_wait_sec=int(cfg.get("max_wait_sec", 600)))
    out = get_first_output_image(meta)
    if not out:
        raise RuntimeError(f"未返回输出图片。prompt_id={prompt_id}")

    filename, subfolder, folder_type = out
    image_bytes = client.fetch_image_bytes(filename, subfolder=subfolder, folder_type=folder_type)
    out_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    save_line = "未保存到相册"
    if save_album:
        out_path = _save_to_album(out_img, cfg, album_name=album_name, expression_name=expression_name, seed=seed, index=album_index)
        save_line = f"已保存到相册: {out_path}"

    msg = (
        f"生成完成。prompt_id={prompt_id}\n"
        f"表情={expression_name}, score={score}, method={method}, seed={seed}\n"
        f"相册={_sanitize_name(album_name, _default_album_name())}\n"
        f"{save_line}\n"
        f"目标提示词={target_prompt}"
    )
    return out_img, msg


def _run_single(
    image: Image.Image,
    expression_name: str,
    score: float,
    method: str,
    strength_hint: float,
    width: int,
    height: int,
    seed: int,
    save_album: bool,
    album_name: str,
) -> Tuple[Image.Image | None, str, List[Tuple[str, str]]]:
    try:
        if image is None:
            raise ValueError("请先上传图片。")
        out_img, msg = _run_single_core(
            image=image,
            expression_name=expression_name,
            score=score,
            method=method,
            strength_hint=strength_hint,
            width=width,
            height=height,
            seed=seed,
            save_album=save_album,
            album_name=album_name,
        )
        return out_img, msg, []
    except Exception as exc:
        return None, f"错误: {exc}\n\n{traceback.format_exc()}", []


def _run_batch_all(
    image: Image.Image,
    score: float,
    method: str,
    strength_hint: float,
    width: int,
    height: int,
    seed: int,
    album_name: str,
) -> Tuple[Image.Image | None, str, List[Tuple[str, str]], gr.Dropdown]:
    try:
        if image is None:
            raise ValueError("请先上传图片。")

        cfg = _load_config()
        expressions = _expression_choices(_load_library(cfg))
        logs: List[str] = [f"开始批量生成，共 {len(expressions)} 张（每个表情 1 张）"]
        gallery: List[Tuple[str, str]] = []

        album = _sanitize_name(album_name, _default_album_name())
        base_seed = int(seed)
        for idx, expr in enumerate(expressions, start=1):
            this_seed = random.randint(1, 2**31 - 1) if base_seed < 0 else base_seed + idx - 1
            out_img, msg = _run_single_core(
                image=image,
                expression_name=expr,
                score=score,
                method=method,
                strength_hint=strength_hint,
                width=width,
                height=height,
                seed=this_seed,
                save_album=True,
                album_name=album,
                album_index=idx,
            )
            gallery.append((out_img, expr))
            logs.append(f"[{idx}/{len(expressions)}] {expr} 完成")
            logs.append(msg)

        first = gallery[0][0] if gallery else None
        logs.append(f"批量任务完成。相册：{album}")
        album_choices = _list_albums(cfg)
        return first, "\n".join(logs), gallery, gr.Dropdown(choices=album_choices, value=album)
    except Exception as exc:
        cfg = _load_config()
        albums = _list_albums(cfg)
        return None, f"批量生成错误: {exc}\n\n{traceback.format_exc()}", [], gr.Dropdown(choices=albums)


def _run_custom_test(
    image: Image.Image,
    custom_name: str,
    custom_prompt: str,
    score: float,
    method: str,
    strength_hint: float,
    width: int,
    height: int,
    seed: int,
    save_album: bool,
    album_name: str,
) -> Tuple[Image.Image | None, str, List[Tuple[str, str]]]:
    try:
        if image is None:
            raise ValueError("请先上传图片。")
        prompt = (custom_prompt or "").strip()
        if not prompt:
            raise ValueError("请先输入自定义表情 Prompt。")
        expr_name = (custom_name or "custom_expression").strip()
        out_img, msg = _run_single_core(
            image=image,
            expression_name=expr_name,
            score=score,
            method=method,
            strength_hint=strength_hint,
            width=width,
            height=height,
            seed=seed,
            save_album=save_album,
            album_name=album_name,
            target_prompt_override=prompt,
        )
        return out_img, f"[自定义测试]\n{msg}", []
    except Exception as exc:
        return None, f"自定义测试错误: {exc}\n\n{traceback.format_exc()}", []


def _save_custom_expression(custom_name: str, custom_prompt: str, strength_hint: float) -> Tuple[gr.Dropdown, str]:
    try:
        cfg = _load_config()
        lib = _load_library(cfg)
        name = (custom_name or "").strip()
        prompt = (custom_prompt or "").strip()
        if not name:
            raise ValueError("请输入自定义表情名称。")
        if not prompt:
            raise ValueError("请输入自定义表情 Prompt。")

        exists = next((x for x in lib["expressions"] if str(x.get("name")) == name), None)
        if exists:
            exists["prompt"] = prompt
            exists["strength_hint"] = float(strength_hint)
            action = "已更新"
        else:
            lib["expressions"].append(
                {
                    "name": name,
                    "prompt": prompt,
                    "strength_hint": float(strength_hint),
                    "sample_count": 0,
                    "avg_intensity": 0.5,
                    "tags": ["custom"],
                    "images": [],
                }
            )
            action = "已新增"

        lib["expressions"] = sorted(lib["expressions"], key=lambda x: str(x.get("name", "")))
        path = _save_library(cfg, lib)
        choices = _expression_choices(lib)
        return gr.Dropdown(choices=choices, value=name), f"{action}自定义表情: {name}\n已写入: {path}"
    except Exception as exc:
        return gr.Dropdown(), f"保存自定义表情失败: {exc}\n\n{traceback.format_exc()}"


def _save_preset(
    preset_name: str,
    expression_name: str,
    score: float,
    method: str,
    strength_hint: float,
    width: int,
    height: int,
) -> Tuple[gr.Dropdown, str]:
    cfg = _load_config()
    name = (preset_name or "").strip()
    if not name:
        return gr.Dropdown(choices=_preset_choices(cfg), value=None), "请先填写参数预设名称。"

    presets = _load_presets(cfg)
    presets[name] = {
        "expression_name": expression_name,
        "score": float(score),
        "method": method,
        "strength_hint": float(strength_hint),
        "width": int(width),
        "height": int(height),
    }
    path = _save_presets(cfg, presets)
    choices = sorted(presets.keys())
    return gr.Dropdown(choices=choices, value=name), f"参数预设已保存: {name}\n{path}"


def _load_preset(preset_name: str):
    cfg = _load_config()
    presets = _load_presets(cfg)
    p = presets.get(preset_name)
    if not p:
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            "未找到参数预设。",
        )
    return (
        p.get("expression_name", ""),
        float(p.get("score", 0.8)),
        p.get("method", "score_one_all"),
        float(p.get("strength_hint", 1.0)),
        int(p.get("width", 768)),
        int(p.get("height", 1152)),
        f"已加载参数预设: {preset_name}",
    )


def _delete_preset(preset_name: str) -> Tuple[gr.Dropdown, str]:
    cfg = _load_config()
    presets = _load_presets(cfg)
    if preset_name in presets:
        del presets[preset_name]
        _save_presets(cfg, presets)
        choices = sorted(presets.keys())
        new_val = choices[0] if choices else None
        return gr.Dropdown(choices=choices, value=new_val), f"已删除参数预设: {preset_name}"
    return gr.Dropdown(choices=sorted(presets.keys()), value=None), "参数预设不存在。"


def build_ui() -> gr.Blocks:
    cfg = _load_config()
    lib = _load_library(cfg)
    expr_choices = _expression_choices(lib)
    default_expr = expr_choices[0]
    preset_choices = _preset_choices(cfg)
    albums = _list_albums(cfg)

    with gr.Blocks(title="iChessGeek表情管理大师") as demo:
        if LOGO_UI.exists():
            gr.Image(value=str(LOGO_UI), show_label=False, interactive=False, height=260)
        gr.Markdown("## iChessGeek表情管理大师")
        gr.Markdown("亮点：历史相册浏览、分页翻阅、点击放大、重命名、删除。")

        gallery_paths_state = gr.State([])
        page_state = gr.State(1)

        with gr.Row():
            with gr.Column(scale=1):
                input_image = gr.Image(type="pil", label="输入图片")
                expression = gr.Dropdown(choices=expr_choices, value=default_expr, label="表情选择")
                score = gr.Slider(0.0, 3.0, value=0.8, step=0.05, label="表情强度（score）")
                method = gr.Dropdown(
                    choices=["score_one_all", "score_one"],
                    value="score_one_all",
                    label="插值方式（method）",
                )
                strength_hint = gr.Slider(0.0, 3.0, value=1.0, step=0.05, label="提示词强度")
                width = gr.Dropdown(choices=[640, 704, 768, 832, 896, 1024], value=768, label="宽度")
                height = gr.Dropdown(choices=[768, 896, 1024, 1152, 1248], value=1152, label="高度")
                seed = gr.Number(value=-1, precision=0, label="随机种子（-1 随机）")
                album_name = gr.Textbox(value=_default_album_name(), label="相册名称（批次）")
                save_album = gr.Checkbox(value=True, label="单张生成后自动保存到相册")

                gr.Markdown("### 参数预设管理")
                preset_name = gr.Textbox(label="参数预设名称", placeholder="例如：开心特写_768x1152")
                preset_dropdown = gr.Dropdown(
                    choices=preset_choices,
                    value=preset_choices[0] if preset_choices else None,
                    label="已保存参数预设",
                )
                with gr.Row():
                    save_preset_btn = gr.Button("保存预设")
                    load_preset_btn = gr.Button("加载预设")
                    delete_preset_btn = gr.Button("删除预设")

                with gr.Row():
                    run_btn = gr.Button("开始生成（单张）", variant="primary")
                    batch_btn = gr.Button("一键批量生成全部表情（保存到相册）", variant="secondary")

                gr.Markdown("### 添加表情（先测试，再入库）")
                custom_name = gr.Textbox(label="自定义表情名称", placeholder="例如：微笑眯眼")
                custom_prompt = gr.Textbox(label="自定义表情 Prompt", lines=3, placeholder="输入用于测试的新表情描述...")
                with gr.Row():
                    custom_test_btn = gr.Button("测试自定义表情")
                    custom_save_btn = gr.Button("保存到表情库")

            with gr.Column(scale=1):
                output_image = gr.Image(type="pil", label="输出图片")
                output_gallery = gr.Gallery(label="本次批量预览", columns=3, height=280)
                logs = gr.Textbox(lines=12, label="运行日志")

                gr.Markdown("### 相册管理（亮点）")
                with gr.Row():
                    album_dropdown = gr.Dropdown(
                        choices=albums,
                        value=albums[0] if albums else None,
                        label="历史相册",
                    )
                    refresh_albums_btn = gr.Button("刷新相册")
                album_keyword = gr.Textbox(label="筛选关键词（文件名/子目录）", placeholder="例如：happy")
                only_favorites = gr.Checkbox(value=False, label="只看收藏")
                with gr.Row():
                    load_album_btn = gr.Button("加载相册")
                    prev_page_btn = gr.Button("上一页")
                    next_page_btn = gr.Button("下一页")
                album_info = gr.Textbox(label="相册信息", lines=2)
                export_zip_file = gr.File(label="相册ZIP下载", interactive=False)
                album_gallery = gr.Gallery(label="相册缩略图", columns=4, height=300)
                selected_preview = gr.Image(type="pil", label="点击放大预览")
                selected_path = gr.Textbox(label="选中文件", interactive=False)
                rename_to = gr.Textbox(label="新文件名（不含扩展名）")
                target_album_name = gr.Textbox(label="目标相册名称（移动）", placeholder="例如：13号_精选")
                rename_prefix = gr.Textbox(label="批量重命名前缀", value="img")
                with gr.Row():
                    rename_btn = gr.Button("重命名")
                    delete_btn = gr.Button("删除")
                    star_btn = gr.Button("收藏/取消收藏")
                with gr.Row():
                    move_btn = gr.Button("移动到目标相册")
                    batch_rename_btn = gr.Button("按当前筛选批量重命名")
                    export_zip_btn = gr.Button("导出相册ZIP")

        save_preset_btn.click(
            fn=_save_preset,
            inputs=[preset_name, expression, score, method, strength_hint, width, height],
            outputs=[preset_dropdown, logs],
        )
        load_preset_btn.click(
            fn=_load_preset,
            inputs=[preset_dropdown],
            outputs=[expression, score, method, strength_hint, width, height, logs],
        )
        delete_preset_btn.click(
            fn=_delete_preset,
            inputs=[preset_dropdown],
            outputs=[preset_dropdown, logs],
        )

        run_btn.click(
            fn=_run_single,
            inputs=[input_image, expression, score, method, strength_hint, width, height, seed, save_album, album_name],
            outputs=[output_image, logs, output_gallery],
        )
        batch_btn.click(
            fn=_run_batch_all,
            inputs=[input_image, score, method, strength_hint, width, height, seed, album_name],
            outputs=[output_image, logs, output_gallery, album_dropdown],
        )

        custom_test_btn.click(
            fn=_run_custom_test,
            inputs=[
                input_image,
                custom_name,
                custom_prompt,
                score,
                method,
                strength_hint,
                width,
                height,
                seed,
                save_album,
                album_name,
            ],
            outputs=[output_image, logs, output_gallery],
        )
        custom_save_btn.click(
            fn=_save_custom_expression,
            inputs=[custom_name, custom_prompt, strength_hint],
            outputs=[expression, logs],
        )

        refresh_albums_btn.click(
            fn=_refresh_album_list,
            inputs=[],
            outputs=[album_dropdown, logs],
        )
        load_album_btn.click(
            fn=_load_album,
            inputs=[album_dropdown, album_keyword, only_favorites],
            outputs=[album_gallery, album_info, page_state, gallery_paths_state, selected_preview, selected_path],
        )
        prev_page_btn.click(
            fn=_album_prev,
            inputs=[album_dropdown, album_keyword, page_state, only_favorites],
            outputs=[album_gallery, album_info, page_state, gallery_paths_state],
        )
        next_page_btn.click(
            fn=_album_next,
            inputs=[album_dropdown, album_keyword, page_state, only_favorites],
            outputs=[album_gallery, album_info, page_state, gallery_paths_state],
        )
        album_gallery.select(
            fn=_on_gallery_select,
            inputs=[gallery_paths_state],
            outputs=[selected_preview, selected_path],
        )
        rename_btn.click(
            fn=_rename_selected,
            inputs=[selected_path, rename_to, album_dropdown, album_keyword, page_state, only_favorites],
            outputs=[album_gallery, album_info, page_state, gallery_paths_state, selected_preview, selected_path],
        )
        delete_btn.click(
            fn=_delete_selected,
            inputs=[selected_path, album_dropdown, album_keyword, page_state, only_favorites],
            outputs=[album_gallery, album_info, page_state, gallery_paths_state, selected_preview, selected_path],
        )
        star_btn.click(
            fn=_toggle_favorite,
            inputs=[selected_path, album_dropdown, album_keyword, page_state, only_favorites],
            outputs=[album_gallery, album_info, page_state, gallery_paths_state],
        )
        move_btn.click(
            fn=_move_selected,
            inputs=[selected_path, target_album_name, album_dropdown, album_keyword, page_state, only_favorites],
            outputs=[album_gallery, album_info, page_state, gallery_paths_state, album_dropdown, selected_preview, selected_path],
        )
        batch_rename_btn.click(
            fn=_batch_rename_current,
            inputs=[album_dropdown, album_keyword, page_state, only_favorites, rename_prefix],
            outputs=[album_gallery, album_info, page_state, gallery_paths_state],
        )
        export_zip_btn.click(
            fn=_export_album_zip,
            inputs=[album_dropdown, only_favorites],
            outputs=[export_zip_file, logs],
        )

    return demo


if __name__ == "__main__":
    cfg = _load_config()
    host = str(cfg.get("ui_host", "127.0.0.1"))
    port = int(cfg.get("ui_port", 7861))
    app = build_ui()
    favicon = str(LOGO_FAVICON) if LOGO_FAVICON.exists() else None
    app.launch(server_name=host, server_port=port, favicon_path=favicon)
