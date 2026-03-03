#!/usr/bin/env python3
"""Gemini image generation helper.

Features:
1) Convert short user idea into refined Chinese image prompt (gemini-3-flash-preview).
2) Compose a background-locked editing prompt for gemini-2.5-flash-image.
3) Generate image-modification suggestions from an input image:
   - physical change prompts
   - position change prompts
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

API_BASE = "https://generativelanguage.googleapis.com/v1beta"


REFINE_SYSTEM_INSTRUCTION = "你是一位专业的提示词工程师。请提取关键点并创建优化的中文图像生成提示词。"

REFINE_PROMPT_TEMPLATE = """作为一名专业的 AI 图像提示词工程师，请分析以下用户指令。
识别关键点（主体、风格、光影、构图）。
为高质量图像生成模型生成一个高度详细、精确且具有描述性的中文提示词。
用户指令: {user_idea}
请以 JSON 格式返回结果：
{{
  "keyPoints": ["关键点 1", "关键点 2"],
  "refinedPrompt": "完整的详细中文提示词"
}}
"""

BACKGROUND_LOCK_TEMPLATE = """【顶级视觉合成指令：局部像素替换 + 全局背景冻结】
原图尺寸为 {size_text}。
任务：基于参考源图，仅修改指令指向的主体。除主体外的所有区域必须与原图保持像素级的一致。
修改任务：{refined_prompt}
核心准则：
1) 背景像素锁定：严禁修改背景中的任何元素、光影或纹理。
2) 尺寸对齐：生成的图像必须与原图的比例和构图完全一致。
3) 身份绝对锁定：保持主体（如杯子）的原始形状和关键特征。
4) 物理级边缘融合：新增元素必须自然贴合在主体表面，具有真实折射、接触阴影和材质互动。
5) 严禁扩图或缩放。
"""

IMAGE_SUGGESTION_PROMPT = """你是图像编辑指导专家。请基于输入图片，输出高质量中文修改建议。
要求：
1) 仅输出 JSON，不要输出多余文字。
2) 分别提供：
   - 物理变化提示（physicalChanges）：关注材质、形变、状态变化、光学效果。
   - 位置变化提示（positionChanges）：关注主体位置、角度、远近、构图重新分布。
3) 每类给出 5 条可直接用于图像编辑模型的提示语。
4) 每条提示语要可执行、明确，避免空泛形容词。
JSON 格式：
{
  "physicalChanges": ["...", "..."],
  "positionChanges": ["...", "..."]
}
"""


@dataclass
class GeminiClient:
    api_key: str

    def _post(self, model: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{API_BASE}/models/{model}:generateContent?key={self.api_key}"
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _extract_text(response_json: Dict[str, Any]) -> str:
        candidates = response_json.get("candidates", [])
        if not candidates:
            raise ValueError(f"Model response missing candidates: {response_json}")
        parts = candidates[0].get("content", {}).get("parts", [])
        text_segments = [p.get("text", "") for p in parts if "text" in p]
        text = "\n".join(seg for seg in text_segments if seg).strip()
        if not text:
            raise ValueError(f"Model response missing text: {response_json}")
        return text

    def refine_prompt(self, user_idea: str) -> Dict[str, Any]:
        payload = {
            "system_instruction": {"parts": [{"text": REFINE_SYSTEM_INSTRUCTION}]},
            "contents": [{"parts": [{"text": REFINE_PROMPT_TEMPLATE.format(user_idea=user_idea)}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        raw = self._post("gemini-3-flash-preview", payload)
        text = self._extract_text(raw)
        return parse_json_from_text(text)

    def generate_image_suggestions(self, image_path: Path) -> Dict[str, List[str]]:
        mime_type, _ = mimetypes.guess_type(str(image_path))
        if not mime_type:
            mime_type = "image/png"
        b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": IMAGE_SUGGESTION_PROMPT},
                        {"inline_data": {"mime_type": mime_type, "data": b64}},
                    ]
                }
            ],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        raw = self._post("gemini-3-flash-preview", payload)
        text = self._extract_text(raw)
        data = parse_json_from_text(text)

        physical = data.get("physicalChanges", [])
        position = data.get("positionChanges", [])
        if not isinstance(physical, list) or not isinstance(position, list):
            raise ValueError(f"Unexpected suggestion format: {data}")
        return {"physicalChanges": physical, "positionChanges": position}


def parse_json_from_text(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def build_background_locked_prompt(refined_prompt: str, width: int, height: int) -> str:
    return BACKGROUND_LOCK_TEMPLATE.format(
        size_text=f"{width}x{height}",
        refined_prompt=refined_prompt,
    )


def nearest_aspect_ratio(width: int, height: int) -> str:
    ratios: List[Tuple[int, int]] = [(1, 1), (4, 3), (3, 4), (16, 9), (9, 16)]
    target = width / height

    def diff(pair: Tuple[int, int]) -> float:
        return abs(target - (pair[0] / pair[1]))

    best = min(ratios, key=diff)
    return f"{best[0]}:{best[1]}"


def run_refine(args: argparse.Namespace) -> None:
    client = GeminiClient(api_key=required_api_key(args.api_key))
    result = client.refine_prompt(args.user_idea)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def run_compose(args: argparse.Namespace) -> None:
    prompt = build_background_locked_prompt(args.refined_prompt, args.width, args.height)
    ratio = nearest_aspect_ratio(args.width, args.height)
    out = {
        "model": "gemini-2.5-flash-image",
        "aspectRatio": ratio,
        "prompt": prompt,
        "retry": 3,
        "inputMode": "inlineData + text",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


def run_suggest(args: argparse.Namespace) -> None:
    image_path = Path(args.image)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    client = GeminiClient(api_key=required_api_key(args.api_key))
    suggestions = client.generate_image_suggestions(image_path)
    print(json.dumps(suggestions, ensure_ascii=False, indent=2))


def required_api_key(cli_value: Optional[str]) -> str:
    value = cli_value or os.getenv("GEMINI_API_KEY")
    if not value:
        raise ValueError("Missing API key. Use --api-key or set GEMINI_API_KEY.")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI image prompt and suggestion tool")
    parser.add_argument("--api-key", help="Gemini API key. Optional if GEMINI_API_KEY is set.")

    sub = parser.add_subparsers(dest="command", required=True)

    p_refine = sub.add_parser("refine", help="Refine a simple idea into a structured Chinese prompt")
    p_refine.add_argument("user_idea", help="Raw user idea")
    p_refine.set_defaults(func=run_refine)

    p_compose = sub.add_parser("compose", help="Compose background-locked visual generation prompt")
    p_compose.add_argument("--refined-prompt", required=True)
    p_compose.add_argument("--width", type=int, required=True)
    p_compose.add_argument("--height", type=int, required=True)
    p_compose.set_defaults(func=run_compose)

    p_suggest = sub.add_parser("suggest", help="Generate physical/position change suggestions from image")
    p_suggest.add_argument("--image", required=True)
    p_suggest.set_defaults(func=run_suggest)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
