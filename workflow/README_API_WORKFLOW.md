# API Workflow 说明

`app.py` 需要的是 **ComfyUI API 格式** 的工作流，不是画布导出的普通 workflow（包含 `nodes` 的那种）。

## 如何导出 API 格式

1. 在 ComfyUI 打开你已经跑通的工作流。
2. 使用“保存（API 格式）”导出 JSON。
3. 保存为：
   - `workflow/qwen_image_edit_api.json`
4. 保持 `config/ui_config.json` 里的节点 ID 与该 API workflow 对应。

## 默认节点 ID（当前模板）

- `load_image`: `129`
- `target_text_encode`: `113`
- `neutral_text_encode`: `248`
- `pixelsmile`: `249`
- `image_scale`: `241`
- `latent`: `119`
- `ksampler`: `133`
