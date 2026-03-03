# Faye

一个基于 Gemini 的两阶段图像编辑辅助工具：

1. **提示词优化**：将简短中文想法转成专业图像提示词。
2. **背景锁定指令拼装**：把优化提示词嵌入“局部替换 + 全局背景冻结”模板。
3. **图片修改建议**：当你提供图片后，自动分别生成：
   - 物理变化提示（材质/形变/光学）
   - 位置变化提示（构图/位置/角度）

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 环境变量

```bash
export GEMINI_API_KEY="你的 API Key"
```

## 用法

### 1) 将简单想法优化为专业中文提示词

```bash
python image_tool.py refine "给杯子加水珠"
```

输出示例：

```json
{
  "keyPoints": ["主体：透明玻璃杯", "效果：杯壁冷凝水珠"],
  "refinedPrompt": "..."
}
```

### 2) 生成视觉模型用的“背景锁定”完整 prompt

```bash
python image_tool.py compose --refined-prompt "在玻璃杯外壁生成真实冷凝水珠..." --width 1920 --height 1080
```

输出包含：
- `model`: `gemini-2.5-flash-image`
- `aspectRatio`: 自动匹配最近比例（如 16:9）
- `prompt`: 可直接发送给视觉模型的完整中文指令
- `retry`: 默认 3

### 3) 输入图片，生成两类修改建议（你新增需求）

```bash
python image_tool.py suggest --image ./example.jpg
```

输出 JSON：

```json
{
  "physicalChanges": ["...5 条..."],
  "positionChanges": ["...5 条..."]
}
```

## 设计说明

- `refine` 与 `suggest` 均使用文本模型返回 JSON，避免额外解析噪声。
- `compose` 只负责构建稳定的编辑指令和配置，不直接生成图片。
- 图片生成时需由调用方把：
  1) 原图（二进制 inlineData）
  2) `compose` 输出的 `prompt`
  3) `aspectRatio`
  一起发送给 `gemini-2.5-flash-image`。
