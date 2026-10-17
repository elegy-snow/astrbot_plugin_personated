# -*- coding: utf-8 -*-
"""Prompt formatting utilities for NAI image companion linkage.

Faithfully implements the NovelAI 4/4.5 tag formatting and natural language
formatting rules extracted and adapted from companion plugins.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from .model import PromptFormatMode


def normalize_prompt_format(value: Any) -> str:
    """Normalize input mode string to canonical PromptFormatMode value."""
    text = str(value or "nai").strip().lower().replace("-", "_")
    if text in {"nai", "novelai", "nai4", "nai_4", "nai45", "nai_diffusion", "naidiffusion", "nai联动", "nai插件联动"}:
        return PromptFormatMode.NAI.value
    if text in {"natural", "natural_language", "description", "prose", "自然语言", "自然语言描述"}:
        return PromptFormatMode.NATURAL_LANGUAGE.value
    return PromptFormatMode.TRADITIONAL.value


def get_prompt_format_instruction(mode: str) -> str:
    """Return LLM system prompt / tool description instructions for the given mode."""
    canonical = normalize_prompt_format(mode)
    if canonical == PromptFormatMode.NAI.value:
        return (
            "使用 NAI（NovelAI 4/4.5）联动写法：以英文 danbooru 风格标签为主、逗号分隔，"
            "精简到能讲清构图即可，不堆砌重复或无意义 tag。"
            "加权用花括号 {tag} 提升、方括号 [tag] 降低，可叠层；也可用 权重::标签:: "
            "对一个或多个标签整体加权（示例 1.5::red dress, long dress::）。"
            "移除物体或翻转概念用负向权重（示例 -1::unwanted object::）。"
            "已知二次元角色用 角色名 (作品名) 形式（示例 texas the omertosa (arknights)）。"
            "多角色时分别用 {人物 [该角色的画风/动作/神态/外貌 tags] 人物} 包裹，"
            "角色专属负面词条写 ntags = [tags]；角色互动使用 source#/target#/mutual#。"
            "需要画面英文文字用 Text: 内容, ；不需要文字加 no text, 。"
            "直接输出可投喂生图后端的提示词字符串，不要输出 Positive prompt/Negative prompt 标题，"
            "也不要写解释性段落。"
        )
    if canonical == PromptFormatMode.NATURAL_LANGUAGE.value:
        return (
            "自然语言描述：连贯具体的英文句子，覆盖主体、外观、动作、场景、光线、镜头、构图与风格；"
            "不要标签堆或权重语法；要避免的内容在末句用 Avoid ... 表达。"
        )
    return (
        "传统文生图写法：英文短词组按主体、外观、服装、场景、光线、镜头、构图、风格排列，逗号分隔；"
        "用 Positive prompt: ... Negative prompt: ... 结构，不写解释段落。"
    )


def extract_positive_negative(prompt_text: str) -> Tuple[str, str]:
    """Extract positive and negative clauses from a raw prompt string."""
    prompt = str(prompt_text or "").strip()
    if not prompt:
        return "", ""

    positive_match = re.search(
        r"positive\s+prompt\s*:\s*(.*?)(?=negative\s+prompt\s*:|$)",
        prompt,
        flags=re.I | re.S,
    )
    negative_match = re.search(r"negative\s+prompt\s*:\s*(.*)$", prompt, flags=re.I | re.S)

    if positive_match or negative_match:
        pos = positive_match.group(1).strip() if positive_match else ""
        neg = negative_match.group(1).strip() if negative_match else ""
        if not pos and negative_match:
            pos = prompt[: negative_match.start()].strip(" \t\r\n,;。；")
        return pos, neg

    return prompt, ""


def format_prompt_for_backend(
    prompt: str,
    mode: str = PromptFormatMode.NAI.value,
    fixed_positive: str = "",
    fixed_negative: str = "",
    scene_hint: str = "",
) -> Tuple[str, Optional[str]]:
    """Format and synthesize prompt and negative prompt for NAI backend.

    Returns:
        (prepared_prompt, negative_prompt)
    """
    canonical_mode = normalize_prompt_format(mode)
    raw_prompt = str(prompt or "").strip()
    pos_part, neg_part = extract_positive_negative(raw_prompt)

    # Combine negative parts
    neg_list: List[str] = []
    if fixed_negative.strip():
        neg_list.append(fixed_negative.strip())
    if neg_part.strip():
        neg_list.append(neg_part.strip())
    combined_negative = ", ".join(neg_list) if neg_list else None

    # Combine positive parts
    pos_list: List[str] = []
    if fixed_positive.strip():
        pos_list.append(fixed_positive.strip())
    if scene_hint.strip():
        pos_list.append(scene_hint.strip())
    if pos_part.strip():
        pos_list.append(pos_part.strip())

    if canonical_mode == PromptFormatMode.NAI.value:
        # NovelAI 4/4.5 syntax:
        # If negative prompt was provided in positive text (e.g. negative prompt: xxx)
        # NAI inline syntax supports -1.5::xxx:: or separate negative
        prepared = ", ".join(filter(bool, pos_list))
        return prepared, combined_negative

    elif canonical_mode == PromptFormatMode.NATURAL_LANGUAGE.value:
        # Natural language mode (en)
        content = ", ".join(filter(bool, pos_list)) or "a beautiful portrait"
        if not content.lower().startswith("create") and not content.lower().startswith("a "):
            sentence = f"A high quality illustration depicting {content}."
        else:
            sentence = content
        if combined_negative:
            sentence += f" Avoid {combined_negative}."
        return sentence, None

    else:
        # Traditional
        pos_str = ", ".join(filter(bool, pos_list)) or "1girl, masterpiece"
        return f"Positive prompt: {pos_str}.", combined_negative
