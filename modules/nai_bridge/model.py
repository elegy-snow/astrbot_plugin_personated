# -*- coding: utf-8 -*-
"""Data models and constants for NAI image generation companion link."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PromptFormatMode(str, Enum):
    """Prompt format mode for image generation."""
    NAI = "nai"  # NovelAI 4/4.5 tag syntax with weights, multi-character blocks, etc.
    NATURAL_LANGUAGE = "natural_language"  # English descriptive natural language
    TRADITIONAL = "traditional"  # Positive prompt / Negative prompt comma-separated


@dataclass
class NAIBridgeConfig:
    """Configuration for NAI image companion link."""
    enabled: bool = True
    prompt_format: str = PromptFormatMode.NAI.value
    default_style: str = ""
    default_size: str = "portrait"  # 竖图 / portrait / 832x1216
    enable_schedule_scene_link: bool = True  # Link active schedule/activity into selfie scene
    fixed_positive_prompt: str = ""  # Default character/visual tags
    fixed_negative_prompt: str = ""  # Default negative tags
    command_alias: str = "/nai"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "prompt_format": self.prompt_format,
            "default_style": self.default_style,
            "default_size": self.default_size,
            "enable_schedule_scene_link": self.enable_schedule_scene_link,
            "fixed_positive_prompt": self.fixed_positive_prompt,
            "fixed_negative_prompt": self.fixed_negative_prompt,
            "command_alias": self.command_alias,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NAIBridgeConfig:
        return cls(
            enabled=bool(data.get("enabled", True)),
            prompt_format=str(data.get("prompt_format", PromptFormatMode.NAI.value)),
            default_style=str(data.get("default_style", "")),
            default_size=str(data.get("default_size", "portrait")),
            enable_schedule_scene_link=bool(data.get("enable_schedule_scene_link", True)),
            fixed_positive_prompt=str(data.get("fixed_positive_prompt", "")),
            fixed_negative_prompt=str(data.get("fixed_negative_prompt", "")),
            command_alias=str(data.get("command_alias", "/nai")),
        )


@dataclass
class NAIGenerationResult:
    """Result of an image generation request."""
    success: bool
    backend: str = "NAI 生图"
    image_path: str = ""
    note: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "backend": self.backend,
            "image_path": self.image_path,
            "note": self.note,
            "metadata": self.metadata,
        }
