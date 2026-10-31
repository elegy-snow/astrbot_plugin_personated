from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List

try:
    from astrbot.api import logger as astrbot_logger
except Exception:
    import logging as _logging
    astrbot_logger = _logging.getLogger("astrbot.plugin.astrbot_plugin_personated")

LOG_TAG = "[日记系统]"

try:
    from astrbot.api.web import error_response, json_response, request
except Exception:
    def json_response(data: Any, status_code: int = 200):
        return {"status": "ok", "data": data, "_code": status_code}

    def error_response(msg: str, status_code: int = 400):
        return {"status": "error", "message": msg, "_code": status_code}

    request = None  # type: ignore

try:
    from ...utils.time_utils import get_today_str
except (ImportError, ValueError):
    from utils.time_utils import get_today_str

from .model import ContinuityThread, DailyDiaryEntry

if TYPE_CHECKING:
    from .manager import DiaryManager
    from astrbot.api.star import Context

PLUGIN_NAME = "astrbot_plugin_personated"


class DiaryWebApi:
    """Handles Web API routes for Diary system."""

    def __init__(self, manager: DiaryManager, logger: logging.Logger) -> None:
        self.mgr = manager
        self.logger = logger

    def register_routes(self, context: Any) -> None:
        """Register Web API routes with AstrBot context."""
        if not hasattr(context, "register_web_api"):
            self.logger.warning("Context does not support register_web_api. Web API skipped.")
            return

        base_routes = [
            ("diary/entries", self.get_entries, ["GET"], "获取所有日记列表"),
            ("diary/detail", self.get_detail, ["GET"], "获取指定日期的日记详情"),
            ("diary/save", self.save_entry, ["POST"], "保存或更新单篇日记"),
            ("diary/delete", self.delete_entry, ["POST"], "删除指定日期的日记"),
        ]

        for path_part, handler, methods, desc in base_routes:
            for prefix in [f"/{PLUGIN_NAME}/", "/"]:
                full_route = f"{prefix}{path_part}"
                try:
                    context.register_web_api(full_route, handler, methods, desc)
                except Exception as e:
                    self.logger.warning("Failed to register Web API route %s: %s", full_route, e)

        astrbot_logger.info(f"{LOG_TAG} 成功注册 {len(base_routes)} 组日记 Web API 路由")

    async def get_entries(self) -> Any:
        """GET /{PLUGIN_NAME}/diary/entries"""
        entries = self.mgr.list_entries()
        return json_response(
            {
                "count": len(entries),
                "entries": [entry.to_dict() for entry in entries],
            }
        )

    async def get_detail(self) -> Any:
        """GET /{PLUGIN_NAME}/diary/detail?date=YYYY-MM-DD"""
        date_str = ""
        if request and hasattr(request, "query"):
            date_str = str(request.query.get("date") or "").strip()
        if not date_str:
            date_str = get_today_str()

        entry = self.mgr.get_entry(date_str)
        if entry:
            return json_response({"found": True, "entry": entry.to_dict()})
        return json_response(
            {"found": False, "entry": None, "message": f"未找到日期 {date_str} 的日记"},
            404,
        )

    async def save_entry(self) -> Any:
        """POST /{PLUGIN_NAME}/diary/save"""
        if request is None:
            return error_response("Request context unavailable", 500)

        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("Payload must be a JSON object", 400)

        date_val = str(payload.get("date") or "").strip()
        if not date_val:
            return error_response("缺少日期 (date)", 400)

        entry = DailyDiaryEntry.from_dict(payload)
        self.mgr.add_entry(entry)
        return json_response(
            {
                "saved": True,
                "entry": entry.to_dict(),
                "message": f"日期 {date_val} 的日记已成功保存",
            }
        )

    async def delete_entry(self) -> Any:
        """POST /{PLUGIN_NAME}/diary/delete"""
        if request is None:
            return error_response("Request context unavailable", 500)

        payload = await request.json(default={})
        date_val = ""
        if isinstance(payload, dict):
            date_val = str(payload.get("date") or "").strip()
        if not date_val and request and hasattr(request, "query"):
            date_val = str(request.query.get("date") or "").strip()

        if not date_val:
            return error_response("缺少日期 (date)", 400)

        self.mgr.delete_entry(date_val)
        return json_response(
            {
                "deleted": True,
                "date": date_val,
                "message": f"日期 {date_val} 的日记已删除",
            }
        )
