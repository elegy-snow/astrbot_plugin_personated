from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List

try:
    from ...utils.time_utils import parse_time_str
except (ImportError, ValueError):
    from utils.time_utils import parse_time_str
from .model import DailyScheduleItem, ScheduleSegment

try:
    from astrbot.api.web import error_response, json_response, request
except Exception:
    # Graceful fallbacks for testing or environments outside active AstrBot Web runtime
    def json_response(data: Any, status_code: int = 200):
        return {"status": "ok", "data": data, "_code": status_code}

    def error_response(msg: str, status_code: int = 400):
        return {"status": "error", "message": msg, "_code": status_code}

    request = None  # type: ignore

if TYPE_CHECKING:
    from .manager import ScheduleManager

PLUGIN_NAME = "astrbot_plugin_personated"


class ScheduleWebApi:
    """Web API handlers for the Personated Schedule UI."""

    def __init__(self, manager: ScheduleManager, logger: logging.Logger) -> None:
        self.mgr = manager
        self.logger = logger

    def register_routes(self, context: Any) -> None:
        """Register Web API endpoints with AstrBot context."""
        if not hasattr(context, "register_web_api"):
            self.logger.warning("Context does not support register_web_api. Web API skipped.")
            return

        routes = [
            (f"/{PLUGIN_NAME}/schedule/config", self.get_config, ["GET"], "获取日程配置与可用模型"),
            (f"/{PLUGIN_NAME}/schedule/config/save", self.save_config, ["POST"], "保存日程配置"),
            (f"/{PLUGIN_NAME}/schedule/today", self.get_today, ["GET"], "获取今日日程及当前生效状态"),
            (f"/{PLUGIN_NAME}/schedule/generate", self.generate_today, ["POST"], "立即触发重新生成今日日程"),
            (f"/{PLUGIN_NAME}/schedule/item/update", self.update_item, ["POST"], "实时编辑今日某个时段的活动与状态"),
        ]

        for route, handler, methods, desc in routes:
            try:
                context.register_web_api(route, handler, methods, desc)
                self.logger.debug("Registered Web API: %s %s", methods, route)
            except Exception as e:
                self.logger.warning("Failed to register Web API route %s: %s", route, e)

    async def get_config(self) -> Any:
        """GET /{PLUGIN_NAME}/schedule/config"""
        # Retrieve available chat providers in AstrBot
        available_providers: List[Dict[str, str]] = []
        try:
            pm = getattr(self.mgr.context, "provider_manager", None)
            if pm and hasattr(pm, "providers") and isinstance(pm.providers, dict):
                for pid, prov in pm.providers.items():
                    name = getattr(prov, "name", pid) or pid
                    available_providers.append({"id": pid, "name": f"{name} ({pid})"})
        except Exception as e:
            self.logger.warning("Error enumerating providers: %s", e)

        segments = [seg.to_dict() for seg in self.mgr.schedule_segments]

        return json_response(
            {
                "daily_generate_time": self.mgr.daily_generate_time,
                "schedule_provider_id": self.mgr.schedule_provider_id,
                "inject_context_enabled": self.mgr.inject_context_enabled,
                "inject_mode": self.mgr.inject_mode,
                "schedule_segments": segments,
                "custom_prompt_template": self.mgr.custom_prompt_template,
                "available_providers": available_providers,
            }
        )

    async def save_config(self) -> Any:
        """POST /{PLUGIN_NAME}/schedule/config/save"""
        if request is None:
            return error_response("Request context unavailable", 500)

        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("Payload must be a JSON object", 400)

        # 1. Validate daily_generate_time
        gen_time = str(payload.get("daily_generate_time", "04:00")).strip()
        try:
            parse_time_str(gen_time)
        except ValueError as e:
            return error_response(f"每日生成时间格式错误：{e}", 400)

        # 2. Validate segments
        raw_segments = payload.get("schedule_segments")
        if not isinstance(raw_segments, list) or len(raw_segments) == 0:
            return error_response("时间段划分列表不能为空", 400)

        sanitized_segments: List[dict] = []
        for idx, item in enumerate(raw_segments):
            if not isinstance(item, dict):
                continue
            seg_id = str(item.get("id") or f"seg_{idx + 1}").strip()
            name = str(item.get("name") or f"时段 {idx + 1}").strip()
            start = str(item.get("start", "")).strip()
            end = str(item.get("end", "")).strip()

            try:
                parse_time_str(start)
                parse_time_str(end)
            except ValueError as e:
                return error_response(f"时段【{name}】的时间格式无效：{e}", 400)

            sanitized_segments.append(
                {
                    "id": seg_id,
                    "name": name,
                    "start": start,
                    "end": end,
                }
            )

        if not sanitized_segments:
            return error_response("没有合法的时间段定义", 400)

        # 3. Apply configurations
        cfg = self.mgr.config
        cfg["daily_generate_time"] = gen_time
        cfg["schedule_provider_id"] = str(payload.get("schedule_provider_id", "")).strip()
        cfg["inject_context_enabled"] = bool(payload.get("inject_context_enabled", True))

        inject_mode = str(payload.get("inject_mode", "extra_user_content")).strip()
        if inject_mode in ["extra_user_content", "system_prompt"]:
            cfg["inject_mode"] = inject_mode

        cfg["schedule_segments"] = sanitized_segments

        custom_prompt = payload.get("custom_prompt_template")
        if custom_prompt is not None and isinstance(custom_prompt, str):
            cfg["custom_prompt_template"] = custom_prompt.strip()

        # Persist to AstrBot config file
        if hasattr(cfg, "save_config"):
            try:
                cfg.save_config()
                self.logger.info("Saved plugin configurations to persistent storage.")
            except Exception as e:
                self.logger.error("Failed to invoke save_config(): %s", e)

        return json_response({"saved": True, "message": "配置已成功保存！"})

    async def get_today(self) -> Any:
        """GET /{PLUGIN_NAME}/schedule/today"""
        status = self.mgr.get_status_info()
        return json_response(status)

    async def generate_today(self) -> Any:
        """POST /{PLUGIN_NAME}/schedule/generate"""
        try:
            schedule = await self.mgr.generate_today_schedule(force=True)
            return json_response(
                {
                    "success": True,
                    "schedule": schedule.to_dict(),
                    "message": f"成功生成 {len(schedule.items)} 个时段日程！",
                }
            )
        except Exception as e:
            self.logger.error("API error generating schedule: %s", e, exc_info=True)
            return error_response(f"生成日程失败: {e}", 500)

    async def update_item(self) -> Any:
        """POST /{PLUGIN_NAME}/schedule/item/update"""
        if request is None:
            return error_response("Request context unavailable", 500)

        payload = await request.json(default={})
        item_id = str(payload.get("id", "")).strip()
        activity = str(payload.get("activity", "")).strip()
        state = str(payload.get("state", "")).strip()

        if not item_id:
            return error_response("缺少时段 ID (id)", 400)

        schedule = self.mgr._current_schedule
        if not schedule:
            return error_response("今日尚未生成日程", 400)

        target_item = None
        for item in schedule.items:
            if item.id == item_id:
                target_item = item
                break

        if not target_item:
            return error_response(f"未找到 ID 为 '{item_id}' 的时段", 404)

        if activity:
            target_item.activity = activity
        if state:
            target_item.state = state

        # Persist updated schedule
        self.mgr._schedules_history[schedule.date] = schedule.to_dict()
        self.mgr._save_to_storage()

        return json_response(
            {
                "updated": True,
                "item": target_item.to_dict(),
                "message": "时段活动与状态更新成功！",
            }
        )
