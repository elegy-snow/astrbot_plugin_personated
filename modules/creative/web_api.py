from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List

try:
    from astrbot.api import logger as astrbot_logger
except Exception:
    import logging as _logging
    astrbot_logger = _logging.getLogger("astrbot.plugin.astrbot_plugin_personated")

LOG_TAG = "[创作与书架]"

try:
    from astrbot.api.web import error_response, json_response, request
except Exception:
    def json_response(data: Any, status_code: int = 200):
        return {"status": "ok", "data": data, "_code": status_code}

    def error_response(msg: str, status_code: int = 400):
        return {"status": "error", "message": msg, "_code": status_code}

    request = None  # type: ignore

from .model import CreativeProject, DraftChunk

if TYPE_CHECKING:
    from .manager import CreativeManager
    from astrbot.api.star import Context

PLUGIN_NAME = "astrbot_plugin_personated"


class CreativeWebApi:
    """Handles Web API routes for Bookshelf and Creative writing system."""

    def __init__(self, manager: CreativeManager, logger: logging.Logger) -> None:
        self.mgr = manager
        self.logger = logger

    def register_routes(self, context: Any) -> None:
        """Register Web API routes with AstrBot context."""
        if not hasattr(context, "register_web_api"):
            self.logger.warning("Context does not support register_web_api. Web API skipped.")
            return

        base_routes = [
            ("creative/projects", self.get_projects, ["GET"], "获取所有创作项目列表"),
            ("creative/detail", self.get_detail, ["GET"], "获取创作项目正文与详情"),
            ("creative/save", self.save_project, ["POST"], "保存或更新创作项目"),
            ("creative/delete", self.delete_project, ["POST"], "删除创作项目"),
            ("bookshelf/summary", self.get_bookshelf_summary, ["GET"], "获取书架陈列概要"),
            ("bookshelf/unlock", self.unlock_secret, ["POST"], "解锁私密夹层"),
        ]

        for path_part, handler, methods, desc in base_routes:
            for prefix in [f"/{PLUGIN_NAME}/", "/"]:
                full_route = f"{prefix}{path_part}"
                try:
                    context.register_web_api(full_route, handler, methods, desc)
                except Exception as e:
                    self.logger.warning("Failed to register Web API route %s: %s", full_route, e)

        astrbot_logger.info(f"{LOG_TAG} 成功注册 {len(base_routes)} 组创作与书架 Web API 路由")

    async def get_projects(self) -> Any:
        """GET /{PLUGIN_NAME}/creative/projects"""
        projects = self.mgr.list_projects()
        return json_response(
            {
                "count": len(projects),
                "projects": [p.to_dict() for p in projects],
            }
        )

    async def get_detail(self) -> Any:
        """GET /{PLUGIN_NAME}/creative/detail?id=PROJECT_ID"""
        project_id = ""
        if request and hasattr(request, "query"):
            project_id = str(request.query.get("id") or "").strip()

        if not project_id:
            return error_response("缺少项目 id", 400)

        project = self.mgr.get_project(project_id)
        if project:
            return json_response({"found": True, "project": project.to_dict()})
        return json_response(
            {"found": False, "project": None, "message": f"未找到 id 为 {project_id} 的作品"},
            404,
        )

    async def save_project(self) -> Any:
        """POST /{PLUGIN_NAME}/creative/save"""
        if request is None:
            return error_response("Request context unavailable", 500)

        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("Payload must be a JSON object", 400)

        proj_id = str(payload.get("id") or "").strip()
        if not proj_id:
            return error_response("缺少作品 id", 400)

        project = CreativeProject.from_dict(payload)
        self.mgr.save_project(project)
        return json_response(
            {
                "saved": True,
                "project": project.to_dict(),
                "message": f"作品《{project.title}》已成功保存",
            }
        )

    async def delete_project(self) -> Any:
        """POST /{PLUGIN_NAME}/creative/delete"""
        if request is None:
            return error_response("Request context unavailable", 500)

        payload = await request.json(default={})
        proj_id = ""
        if isinstance(payload, dict):
            proj_id = str(payload.get("id") or "").strip()
        if not proj_id and request and hasattr(request, "query"):
            proj_id = str(request.query.get("id") or "").strip()

        if not proj_id:
            return error_response("缺少作品 id", 400)

        deleted = self.mgr.delete_project(proj_id)
        return json_response(
            {
                "deleted": deleted,
                "id": proj_id,
                "message": f"作品已删除" if deleted else "作品不存在",
            }
        )

    async def get_bookshelf_summary(self) -> Any:
        """GET /{PLUGIN_NAME}/bookshelf/summary"""
        projects = self.mgr.list_projects()
        public_books = [p.to_dict() for p in projects if not p.secret]
        secret_books = [p.to_dict() for p in projects if p.secret]
        return json_response(
            {
                "public_count": len(public_books),
                "secret_count": len(secret_books),
                "public_books": public_books,
                "secret_books": secret_books,
            }
        )

    async def unlock_secret(self) -> Any:
        """POST /{PLUGIN_NAME}/bookshelf/unlock"""
        if request is None:
            return error_response("Request context unavailable", 500)

        payload = await request.json(default={})
        password = ""
        if isinstance(payload, dict):
            password = str(payload.get("password") or "").strip()

        expected_password = str(self.mgr.get_config_val("bookshelf_secret_password", "123456")).strip()
        if password == expected_password:
            return json_response({"unlocked": True, "message": "夹层已成功解锁"})
        return json_response({"unlocked": False, "message": "密码错误，无法打开抽屉"}, 403)
