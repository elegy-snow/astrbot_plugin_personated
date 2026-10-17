# -*- coding: utf-8 -*-
"""Web API endpoints for NAI Companion Link management in WebUI."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

try:
    from astrbot.api import logger as astrbot_logger
except Exception:
    import logging as _logging
    astrbot_logger = _logging.getLogger("astrbot.plugin.astrbot_plugin_personated")

try:
    from astrbot.api.web import error_response, json_response, request
except Exception:
    def json_response(data: Any, status_code: int = 200):
        return {"status": "ok", "data": data, "_code": status_code}

    def error_response(msg: str, status_code: int = 400):
        return {"status": "error", "message": msg, "_code": status_code}

    request = None  # type: ignore

if TYPE_CHECKING:
    from .manager import NAIBridgeManager

PLUGIN_NAME = "astrbot_plugin_personated"


class NAIBridgeWebApi:
    """Web API handlers for NAI companion bridge configuration and live testing."""

    def __init__(self, manager: NAIBridgeManager, logger_: logging.Logger) -> None:
        self.mgr = manager
        self.logger = logger_

    def register_routes(self, context: Any) -> None:
        """Register Web API endpoints with AstrBot context."""
        if not hasattr(context, "register_web_api"):
            self.logger.warning("Context does not support register_web_api. NAI Web API skipped.")
            return

        base_routes = [
            ("nai-bridge/status", self.get_status, ["GET"], "获取 NAI 生图插件联动状态与可用能力"),
            ("nai-bridge/config", self.get_config, ["GET"], "获取 NAI 联动配置"),
            ("nai-bridge/config/save", self.save_config, ["POST"], "保存 NAI 联动配置"),
            ("nai-bridge/test-generate", self.test_generate, ["POST"], "在 WebUI 控制台发起一次测试生图"),
        ]

        for path_part, handler, methods, desc in base_routes:
            for prefix in [f"/{PLUGIN_NAME}/", "/"]:
                full_route = f"{prefix}{path_part}"
                try:
                    context.register_web_api(full_route, handler, methods, desc)
                except Exception as e:
                    self.logger.warning("Failed to register Web API route %s: %s", full_route, e)

        astrbot_logger.info(f"[NAI 联动] 成功注册 {len(base_routes)} 组 Web API 路由")

    async def get_status(self) -> Any:
        """GET /{PLUGIN_NAME}/nai-bridge/status"""
        status_info = self.mgr.bridge_client.get_status()
        schedule_hint = self.mgr.get_active_schedule_scene_hint()
        return json_response(
            {
                "status": status_info,
                "current_schedule_scene": schedule_hint,
                "config": self.mgr.config.to_dict(),
            }
        )

    async def get_config(self) -> Any:
        """GET /{PLUGIN_NAME}/nai-bridge/config"""
        return json_response(self.mgr.config.to_dict())

    async def save_config(self) -> Any:
        """POST /{PLUGIN_NAME}/nai-bridge/config/save"""
        if request is None:
            return error_response("Request context unavailable", 500)
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("Payload must be a JSON object", 400)

        ok = self.mgr.save_config(payload)
        if ok:
            return json_response({"saved": True, "message": "NAI 联动配置已保存并生效"})
        return error_response("保存 NAI 联动配置失败", 500)

    async def test_generate(self) -> Any:
        """POST /{PLUGIN_NAME}/nai-bridge/test-generate"""
        if request is None:
            return error_response("Request context unavailable", 500)
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("Payload must be a JSON object", 400)

        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            return error_response("提示词不能为空", 400)

        workflow_kind = str(payload.get("workflow_kind") or "selfie").strip()
        size = str(payload.get("size") or "")
        style = str(payload.get("style") or "")
        negative = payload.get("negative")
        include_schedule = bool(payload.get("include_schedule", True))

        res = await self.mgr.generate_image(
            prompt=prompt,
            workflow_kind=workflow_kind,
            size=size,
            style=style,
            negative=negative,
            include_schedule_scene=include_schedule,
        )

        return json_response(res.to_dict())
