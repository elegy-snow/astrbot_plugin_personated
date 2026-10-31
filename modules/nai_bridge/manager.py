# -*- coding: utf-8 -*-
"""Manager coordinating NAI companion image generation with schedule persona context."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .bridge import NAIBridgeClient
from .model import NAIBridgeConfig, NAIGenerationResult, PromptFormatMode
from .prompt_format import (
    format_prompt_for_backend,
    get_prompt_format_instruction,
    normalize_prompt_format,
)

if TYPE_CHECKING:
    from ..schedule.manager import ScheduleManager

logger = logging.getLogger("astrbot_plugin_personated.nai_manager")


class NAIBridgeManager:
    """Coordinates NAI companion link state, prompt synthesis, and execution."""

    def __init__(
        self,
        context: Any,
        config: Any,
        logger_: logging.Logger,
        schedule_manager: Optional[ScheduleManager] = None,
        data_dir: Optional[Path] = None,
    ) -> None:
        self.context = context
        self.plugin_config = config
        self.logger = logger_
        self.schedule_mgr = schedule_manager
        self.data_dir = data_dir or Path("data/plugin_data/astrbot_plugin_personated")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.data_dir / "nai_bridge_config.json"

        self.bridge_client = NAIBridgeClient(context)
        self.config = NAIBridgeConfig()
        self.load_config()

    def load_config(self) -> None:
        """Load NAI link configuration from disk or default plugin config."""
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.config = NAIBridgeConfig.from_dict(data)
                    return
            except Exception as e:
                self.logger.warning("Failed to load nai_bridge_config.json: %s", e)

        # Fallback to plugin config
        cfg = self.plugin_config or {}
        self.config = NAIBridgeConfig(
            enabled=bool(cfg.get("nai_link_enabled", True)),
            prompt_format=str(cfg.get("nai_prompt_format", PromptFormatMode.NAI.value)),
            default_style=str(cfg.get("nai_default_style", "")),
            default_size=str(cfg.get("nai_default_size", "portrait")),
            enable_schedule_scene_link=bool(cfg.get("nai_enable_schedule_scene_link", True)),
            fixed_positive_prompt=str(cfg.get("nai_fixed_positive_prompt", "")),
            fixed_negative_prompt=str(cfg.get("nai_fixed_negative_prompt", "")),
        )

    def save_config(self, new_cfg: Dict[str, Any]) -> bool:
        """Save updated NAI link configuration."""
        try:
            current = self.config.to_dict()
            current.update(new_cfg)
            self.config = NAIBridgeConfig.from_dict(current)
            self.config_file.write_text(
                json.dumps(self.config.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except Exception as e:
            self.logger.error("Failed to save nai_bridge_config: %s", e)
            return False

    def get_active_schedule_scene_hint(self) -> str:
        """Fetch current schedule/activity state from ScheduleManager to enrich prompt."""
        if not self.config.enable_schedule_scene_link or not self.schedule_mgr:
            return ""

        try:
            today_sched = self.schedule_mgr.today_schedule
            if not today_sched:
                return ""
            active_item = today_sched.find_active_item()
            if not active_item:
                return ""

            activity = (active_item.activity or "").strip()
            state = (active_item.state or "").strip()
            name = (active_item.name or "").strip()

            parts: List[str] = []
            if activity:
                parts.append(activity)
            if state:
                parts.append(state)
            if not parts and name:
                parts.append(name)

            return ", ".join(parts)
        except Exception as e:
            self.logger.debug("Error getting schedule scene hint: %s", e)
            return ""

    def get_tool_instruction(self) -> str:
        """Return the tool prompt instruction based on configured prompt format."""
        return get_prompt_format_instruction(self.config.prompt_format)

    async def generate_image(
        self,
        prompt: str,
        workflow_kind: str = "selfie",
        session_key: str = "",
        size: str = "",
        style: str = "",
        reference_image_paths: Optional[List[str]] = None,
        negative: Optional[str] = None,
        include_schedule_scene: bool = True,
    ) -> NAIGenerationResult:
        """Synthesize prompt with active schedule context and invoke NAI companion link."""
        if not self.config.enabled:
            return NAIGenerationResult(
                success=False,
                backend="NAI 生图",
                note="NAI 陪伴联动功能已在设置中关闭。",
            )

        # 1. Obtain schedule scene context if applicable
        scene_hint = self.get_active_schedule_scene_hint() if include_schedule_scene else ""

        # 2. Format prompt
        prepared_prompt, default_neg = format_prompt_for_backend(
            prompt=prompt,
            mode=self.config.prompt_format,
            fixed_positive=self.config.fixed_positive_prompt,
            fixed_negative=self.config.fixed_negative_prompt,
            scene_hint=scene_hint,
        )

        final_negative = negative if negative is not None else default_neg
        final_size = size or self.config.default_size
        final_style = style or self.config.default_style

        # 3. Assemble request payload for NAIImageCompanionExtensionAPI
        payload: Dict[str, Any] = {
            "prompt_text": prepared_prompt,
            "prompt": prepared_prompt,
            "workflow_kind": workflow_kind,
            "session_key": session_key,
            "size": final_size,
            "style": final_style,
        }
        if final_negative:
            payload["negative"] = final_negative
        if reference_image_paths:
            payload["reference_image_paths"] = reference_image_paths

        # 4. Invoke bridge
        res = await self.bridge_client.generate(payload)
        return NAIGenerationResult(
            success=bool(res.get("success")),
            backend=str(res.get("backend") or "NAI 生图"),
            image_path=str(res.get("image_path") or ""),
            note=str(res.get("note") or ""),
            metadata=res.get("metadata") or {},
        )
