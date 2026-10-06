from __future__ import annotations

import datetime
import json
import re
from typing import Any, List, Optional

try:
    from ...utils.time_utils import get_today_str, get_weekday_cn
except (ImportError, ValueError):
    from utils.time_utils import get_today_str, get_weekday_cn
from .model import DailySchedule, DailyScheduleItem, ScheduleSegment

DEFAULT_SYSTEM_PROMPT = (
    "你是一个顶级的角色扮演与日程规划专家。"
    "你的任务是为特定人设的角色规划符合其个性特征、生活习惯和作息规律的一日真实生活日程。"
    "严格以纯 JSON 数组形式输出结果，不要输出任何非 JSON 字符或解释说明。"
)

DEFAULT_GENERATION_PROMPT = (
    "你正在为一个具体的人格角色规划一天的真实作息与生活日程。\n"
    "【角色人设】：\n{persona_prompt}\n\n"
    "今天是 {date}（星期{weekday}）。\n"
    "请根据该人设性格、日常喜好、职业/身份特点以及生活节奏，为今天指定的各个时间段分别规划具体的活动事件、心理状态/心情以及细节。\n\n"
    "今天的时间段安排如下：\n{segments_desc}\n\n"
    "【返回规范】：\n"
    "请严格返回 JSON 数组格式（不要包含任何 markdown 代码块包裹，也不要有任何其他文字），数组每个元素对应一个时间段，字段包含：\n"
    "- id: 时间段ID\n"
    "- name: 时间段名称\n"
    "- start: 开始时间\n"
    "- end: 结束时间\n"
    "- activity: 当前具体在做的事情和所处环境（生动拟人化）\n"
    "- state: 当前心情、精神状态与心理活动"
)


def build_schedule_generation_prompt(
    persona_prompt: str,
    segments: List[ScheduleSegment],
    dt: datetime.datetime | None = None,
    template: str | None = None,
) -> tuple[str, str]:
    """Build the system prompt and user prompt for schedule generation.

    Args:
        persona_prompt: The prompt text defining the persona.
        segments: List of defined ScheduleSegment.
        dt: The date to generate for (default now).
        template: Optional custom prompt template.

    Returns:
        tuple (system_prompt, user_prompt)
    """
    if dt is None:
        dt = datetime.datetime.now()

    date_str = get_today_str(dt)
    weekday_str = get_weekday_cn(dt)

    segments_desc_lines = []
    for idx, seg in enumerate(segments, 1):
        segments_desc_lines.append(
            f"{idx}. ID: '{seg.id}' | 名称: '{seg.name}' | 时间段: {seg.start} ~ {seg.end}"
        )
    segments_desc = "\n".join(segments_desc_lines)

    template_to_use = template or DEFAULT_GENERATION_PROMPT
    user_prompt = template_to_use.format(
        persona_prompt=persona_prompt.strip() or "默认智能助手",
        date=date_str,
        weekday=weekday_str,
        segments_desc=segments_desc,
    )

    return DEFAULT_SYSTEM_PROMPT, user_prompt


def parse_schedule_llm_response(
    raw_response: str,
    segments: List[ScheduleSegment],
    date_str: str,
    weekday_str: str,
    persona_id: str,
    provider_used: str,
) -> DailySchedule:
    """Parse raw LLM response text into a validated DailySchedule object.

    Handles markdown fences, extraneous text, and missing keys gracefully.
    """
    cleaned = raw_response.strip()

    # Strip markdown code blocks like ```json ... ``` or ``` ... ```
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if code_block_match:
        cleaned = code_block_match.group(1).strip()

    # Find the outermost JSON array or object
    array_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", cleaned)
    if array_match:
        json_str = array_match.group(0)
    else:
        obj_match = re.search(r"\{[\s\S]*\}", cleaned)
        if obj_match:
            json_str = obj_match.group(0)
        else:
            json_str = cleaned

    parsed_data: Any = None
    try:
        parsed_data = json.loads(json_str)
    except Exception as e:
        # Fallback: if json parsing fails, try relaxed regex or raise
        raise ValueError(f"Failed to parse LLM schedule JSON: {e}. Raw content: {raw_response[:200]}")

    raw_items: list[dict] = []
    if isinstance(parsed_data, list):
        raw_items = parsed_data
    elif isinstance(parsed_data, dict):
        # Maybe wrapped inside a key such as "schedule" or "items"
        for key in ["schedule", "items", "segments", "data"]:
            if key in parsed_data and isinstance(parsed_data[key], list):
                raw_items = parsed_data[key]
                break

    # Map raw items by segment id or index
    raw_by_id: dict[str, dict] = {}
    for item in raw_items:
        if isinstance(item, dict) and "id" in item:
            raw_by_id[str(item["id"])] = item

    schedule_items: List[DailyScheduleItem] = []
    for idx, seg in enumerate(segments):
        matched_dict = raw_by_id.get(seg.id)
        if not matched_dict and idx < len(raw_items) and isinstance(raw_items[idx], dict):
            matched_dict = raw_items[idx]

        if matched_dict:
            activity = str(matched_dict.get("activity") or matched_dict.get("content") or "进行日常活动中")
            state = str(matched_dict.get("state") or matched_dict.get("mood") or "情绪平和自然")
        else:
            activity = f"处于【{seg.name}】时段，进行常规活动与思考"
            state = "精神饱满，状态自然"

        schedule_items.append(
            DailyScheduleItem(
                id=seg.id,
                name=seg.name,
                start=seg.start,
                end=seg.end,
                activity=activity,
                state=state,
            )
        )

    return DailySchedule(
        date=date_str,
        weekday=weekday_str,
        persona_id=persona_id,
        generated_at=datetime.datetime.now().isoformat(),
        provider_used=provider_used,
        items=schedule_items,
    )


def format_injected_schedule_context(
    item: DailyScheduleItem,
    current_time_str: str,
    date_str: str,
    weekday_str: str,
) -> str:
    """Format the schedule context string to inject into the LLM conversation request."""
    return (
        f"<daily_schedule_status>\n"
        f"【角色当前作息与实时状态】\n"
        f"- 现实时间：{date_str} 星期{weekday_str} {current_time_str}\n"
        f"- 当前阶段：【{item.name}】（时段：{item.start} ~ {item.end}）\n"
        f"- 此刻你正在做的事情：{item.activity}\n"
        f"- 此刻你的心情与状态：{item.state}\n"
        f"【交互原则】：你作为拥有真实生活作息的角色参与对话。请在回复中自然流露出当前的时间观念、生活细节与当下心情（如被问及或闲聊时可自然提及正在做的事情），切忌机械性背诵本提示。\n"
        f"</daily_schedule_status>"
    )
