from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


def parse_umo_details(umo: str) -> Dict[str, str]:
    """Parse a unified_msg_origin string into structured platform, chat type, and target ID.

    Examples:
        - "aiocqhttp:GroupMessage:123456789" -> platform: aiocqhttp, chat_type: group, target_id: 123456789
        - "aiocqhttp:FriendMessage:987654321" -> platform: aiocqhttp, chat_type: private, target_id: 987654321
        - "telegram:GroupMessage:-100123456" -> platform: telegram, chat_type: group, target_id: -100123456
        - "webchat:FriendMessage:session-1" -> platform: webchat, chat_type: webchat, target_id: session-1
    """
    umo_str = str(umo or "").strip()
    if not umo_str:
        return {
            "platform": "unknown",
            "platform_name_cn": "未知平台",
            "chat_type": "unknown",
            "chat_type_text": "未知类型",
            "target_id": "",
            "group_id": "",
            "display_badge": "未知",
        }

    parts = umo_str.split(":")
    platform = parts[0] if len(parts) >= 1 else "unknown"
    msg_type = parts[1] if len(parts) >= 2 else "unknown"
    session_id = ":".join(parts[2:]) if len(parts) >= 3 else (parts[1] if len(parts) == 2 else "")

    msg_type_lower = msg_type.lower()
    platform_lower = platform.lower()

    if "group" in msg_type_lower or "channel" in msg_type_lower:
        chat_type = "group"
        chat_type_text = "群聊"
        group_id = session_id
    elif "webchat" in platform_lower or "webchat" in msg_type_lower:
        chat_type = "webchat"
        chat_type_text = "网页会话"
        group_id = ""
    elif "friend" in msg_type_lower or "private" in msg_type_lower or "direct" in msg_type_lower:
        chat_type = "private"
        chat_type_text = "私聊"
        group_id = ""
    else:
        chat_type = "group" if any(k in umo_str.lower() for k in ["group", "grp"]) else "private"
        chat_type_text = "群聊" if chat_type == "group" else "私聊"
        group_id = session_id if chat_type == "group" else ""

    platform_map = {
        "aiocqhttp": "QQ (OneBot)",
        "qq_official": "QQ 官方频道/群",
        "qq_official_webhook": "QQ 官方 Webhook",
        "telegram": "Telegram",
        "wecom": "企业微信",
        "wecom_ai_bot": "企微智能机器人",
        "lark": "飞书",
        "dingtalk": "钉钉",
        "discord": "Discord",
        "slack": "Slack",
        "kook": "KOOK (开黑啦)",
        "satori": "Satori",
        "webchat": "AstrBot 网页端",
    }
    platform_name_cn = platform_map.get(platform, platform)

    if chat_type == "group":
        display_badge = f"{platform_name_cn} · 群 {group_id or session_id}"
    elif chat_type == "private":
        display_badge = f"{platform_name_cn} · 用户 {session_id}"
    else:
        display_badge = f"{platform_name_cn} · {session_id}"

    return {
        "platform": platform,
        "platform_name_cn": platform_name_cn,
        "chat_type": chat_type,
        "chat_type_text": chat_type_text,
        "target_id": session_id,
        "group_id": group_id,
        "display_badge": display_badge,
    }


@dataclass
class UmoPromptRule:
    """Personalized prompt injection rule for a specific conversation (identified by UMO)."""

    umo: str
    name: str = ""
    prompt: str = ""
    enabled: bool = True
    inject_mode: str = "system_prompt"  # "system_prompt" | "extra_user_content" | "prepend_system"
    group_id: str = ""
    chat_type: str = "unknown"
    platform: str = "unknown"
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())

    def __post_init__(self) -> None:
        self.umo = str(self.umo or "").strip()
        parsed = parse_umo_details(self.umo)
        if not self.group_id and parsed.get("group_id"):
            self.group_id = parsed["group_id"]
        if not self.chat_type or self.chat_type == "unknown":
            self.chat_type = parsed["chat_type"]
        if not self.platform or self.platform == "unknown":
            self.platform = parsed["platform"]
        if not self.name:
            self.name = parsed["display_badge"]

    def to_dict(self) -> Dict[str, Any]:
        parsed = parse_umo_details(self.umo)
        data = asdict(self)
        data.update(
            {
                "platform_name_cn": parsed["platform_name_cn"],
                "chat_type_text": parsed["chat_type_text"],
                "target_id": parsed["target_id"],
                "display_badge": parsed["display_badge"],
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UmoPromptRule:
        return cls(
            umo=str(data.get("umo", "")).strip(),
            name=str(data.get("name", "")).strip(),
            prompt=str(data.get("prompt", "")).strip(),
            enabled=bool(data.get("enabled", True)),
            inject_mode=str(data.get("inject_mode", "system_prompt")).strip(),
            group_id=str(data.get("group_id", "")).strip(),
            chat_type=str(data.get("chat_type", "")).strip(),
            platform=str(data.get("platform", "")).strip(),
            created_at=str(data.get("created_at") or datetime.datetime.now().isoformat()),
            updated_at=str(data.get("updated_at") or datetime.datetime.now().isoformat()),
        )
