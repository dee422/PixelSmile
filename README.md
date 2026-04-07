# iChessGeek 表情管理大师（ComfyUI PixelSmile）

一个面向本地工作流的表情编辑项目：
- ComfyUI 自定义节点：`PixelSmile` 插值控制
- 本地表情库：可批量构建、标准化、维护
- 独立中文界面（Gradio）：无需直接操作 ComfyUI 画布
- 相册系统：历史相册、分页、筛选、放大、重命名、删除、收藏、跨相册移动

## 核心能力

### 1) ComfyUI 节点扩展

- `PixelSmileConditioning`
  - 在 `target` 与 `neutral` 两路 conditioning 之间做插值
- `PixelSmileExpressionLibraryLoad`
- `PixelSmileExpressionPromptFromLibrary`
- `PixelSmileExpressionPromptByIndex`
- `PixelSmileExpressionNames`

节点代码：`__init__.py`

### 2) 独立中文界面（主入口）

- 文件：`app.py`
- 启动：`run_pixelsmile_ui.bat`
- 默认地址：`http://127.0.0.1:7861`

功能包括：
- 单张生成
- 一键批量生成全部表情
- 参数预设（保存/加载/删除）
- 自定义表情（先测试再入库）
- 相册管理（亮点）

### 3) 相册管理（亮点）

- 按“相册名称（批次）”归档输出
- 历史相册浏览
- 关键词筛选
- 分页翻阅
- 缩略图点击放大
- 单图重命名 / 删除
- 收藏与“只看收藏”
- 移动到其他相册
- 按当前筛选批量重命名

## 目录结构（关键文件）

- `app.py`：独立 UI
- `comfy_client.py`：ComfyUI API 客户端
- `run_pixelsmile_ui.bat`：UI 一键启动
- `__init__.py`：ComfyUI 自定义节点
- `config/ui_config.json`：UI 运行配置
- `config/ui_presets.json`：参数预设存储
- `expression_library/library.presets.cn.json`：内置多表情预置库
- `scripts/build_expression_library.py`：从图片/Ollama 构建表情库
- `scripts/normalize_expression_library.py`：表情库标准化

## 环境要求

- Windows + NVIDIA GPU（已验证 3070 8GB）
- 已安装 ComfyUI（Windows portable）
- 已放置并可加载相关模型（UNet/LoRA/VAE/Text Encoder）
- Python 3.10 环境（建议）：
  - `C:\Users\deejo\anaconda3\envs\tts\python.exe`

## 快速开始（推荐流程）

### A. 启动 ComfyUI

确保 ComfyUI 正在运行，并可访问：
- `http://127.0.0.1:8188`

### B. 准备 API Workflow

在 ComfyUI 中把可运行流程导出为 **API 格式**，保存为：
- `workflow/qwen_image_edit_api.json`

> 说明文档：`workflow/README_API_WORKFLOW.md`

### C. 启动独立界面

双击：
- `run_pixelsmile_ui.bat`

浏览器打开：
- `http://127.0.0.1:7861`

## 表情库说明

### 内置预置库

默认使用：
- `expression_library/library.presets.cn.json`

包含多种常用表情（如 happy/sad/angry/surprised 等）。

### 自定义入库

UI 中使用“自定义表情”区域：
1. 输入自定义名称与 prompt
2. 点击“测试自定义表情”
3. 满意后点击“保存到表情库”

## 批量生成规则

“一键批量生成全部表情”会：
- 按当前表情库逐个生成
- 每个表情生成 1 张（第一版）
- 统一保存到指定相册名下

路径示例：
- `album/13号/happy/01_happy_seed...png`
- `album/13号/sad/04_sad_seed...png`

## 常见问题

### 1) UI 能打开，但生成时报连接错误

通常是 ComfyUI 地址或端口不对。
检查 `config/ui_config.json`：
- `comfy_base_url` 是否与实际一致（如 `8188` 或 `8189`）

### 2) ComfyUI 报模型不匹配

优先检查：
- Text Encoder / CLIP 节点类型是否与工作流匹配
- 模型文件是否放在对应目录并被 ComfyUI识别

### 3) 比例看起来不对

同步调整：
- `ImageScale` 的 `width/height`
- `Latent` 的 `width/height`
并保持与输入图纵横比一致（例如 768x1152）。

## 版本说明

当前为“第一版可用版本（V1）”：
- 主流程可跑通
- 具备表情库、独立 UI、相册管理全链路
- 后续可继续扩展：多图批量、导出 ZIP、审核流等
